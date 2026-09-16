"""ai-chat-service 的接口与落库行为测试。

分层约定：
- 不依赖数据库的用例使用 `api` fixture（参数校验、健康检查）；
- 需要落库或内部链路的用例使用 `client` fixture，数据库不可用时自动跳过
  （见 `tests/conftest.py`）。
"""

import importlib

from app.core.config import settings
from app.core.constants import DEGRADED_REPLY, CallStatus, ModelErrorCode
from app.service.model_client import ModelReply
from tests.conftest import OTHER_HEADERS, USER_HEADERS

# `app.service` 包导出的 `chat_service` 是实例，会遮蔽同名模块属性；
# 这里用 importlib 直接取模块对象，保证 monkeypatch 打在服务真正使用的符号上。
chat_module = importlib.import_module("app.service.chat_service")


class _FakeSnapshot:
    """模拟 Nacos 热更新快照：关闭 Mock，走真实模型分支。"""

    use_mock = False
    model_base_url = "http://127.0.0.1:1/v1"
    model_api_key = "test-key"


class _FakeRuntimeConfig:
    def snapshot(self) -> _FakeSnapshot:
        return _FakeSnapshot()


def test_health_has_unified_result(api) -> None:
    response = api.get("/health")
    body = response.json()
    assert response.status_code == 200
    assert body["code"] == 0
    assert body["data"]["status"] == "UP"
    assert body["requestId"]


def test_invalid_completion_uses_business_validation_code(api) -> None:
    """参数校验失败返回 2001；该分支不访问数据库。"""

    response = api.post(
        "/api/chat/completions",
        headers=USER_HEADERS,
        json={"messages": []},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["code"] == 2001
    assert body["data"] is None


def test_completion_persists_session_and_messages(client, monkeypatch) -> None:
    """一次 Mock 对话应落库一个会话 + 两条消息，并可被会话接口查回。"""

    monkeypatch.setattr(settings, "enable_internal_chain", False)
    response = client.post(
        "/api/chat/completions",
        headers=USER_HEADERS,
        json={"messages": [{"role": "user", "content": "你好，帮我写一句摘要"}]},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["code"] == 0
    data = body["data"]
    assert data["mock"] is True
    assert data["call_status"] == CallStatus.SUCCESS.value
    session_id = data["session_id"]
    assert session_id > 0

    sessions = client.get("/api/chat/sessions", headers=USER_HEADERS).json()
    assert sessions["code"] == 0
    assert sessions["data"]["total"] == 1
    assert sessions["data"]["list"][0]["id"] == session_id
    # 首条用户消息生成标题，超长部分被截断。
    assert sessions["data"]["list"][0]["title"].startswith("你好，帮我写一句摘要")
    assert sessions["data"]["list"][0]["last_message_time"]

    messages = client.get(
        f"/api/chat/sessions/{session_id}/messages", headers=USER_HEADERS
    ).json()
    assert messages["code"] == 0
    assert messages["data"]["total"] == 2
    roles = [item["role"] for item in messages["data"]["list"]]
    assert roles == ["user", "assistant"]
    assistant = messages["data"]["list"][1]
    assert assistant["call_status"] == CallStatus.SUCCESS.value
    assert assistant["token_count"] > 0


def test_completion_continues_existing_session(client, monkeypatch) -> None:
    """传入 session_id 时复用会话，不新建，消息持续追加。"""

    monkeypatch.setattr(settings, "enable_internal_chain", False)
    first = client.post(
        "/api/chat/completions",
        headers=USER_HEADERS,
        json={"messages": [{"role": "user", "content": "第一轮"}]},
    ).json()
    session_id = first["data"]["session_id"]

    second = client.post(
        "/api/chat/completions",
        headers=USER_HEADERS,
        json={
            "session_id": session_id,
            "messages": [
                {"role": "user", "content": "第一轮"},
                {"role": "assistant", "content": "收到"},
                {"role": "user", "content": "第二轮"},
            ],
        },
    ).json()
    assert second["code"] == 0
    assert second["data"]["session_id"] == session_id

    sessions = client.get("/api/chat/sessions", headers=USER_HEADERS).json()
    assert sessions["data"]["total"] == 1

    messages = client.get(
        f"/api/chat/sessions/{session_id}/messages", headers=USER_HEADERS
    ).json()
    # 两轮对话：2 条用户 + 2 条助手。
    assert messages["data"]["total"] == 4
    contents = [item["content"] for item in messages["data"]["list"]]
    assert "第二轮" in contents


def test_completion_rejects_other_users_session(client, monkeypatch) -> None:
    """访问他人会话返回 4004，不暴露资源归属。"""

    monkeypatch.setattr(settings, "enable_internal_chain", False)
    created = client.post(
        "/api/chat/completions",
        headers=USER_HEADERS,
        json={"messages": [{"role": "user", "content": "私有会话"}]},
    ).json()
    session_id = created["data"]["session_id"]

    response = client.post(
        "/api/chat/completions",
        headers=OTHER_HEADERS,
        json={"session_id": session_id, "messages": [{"role": "user", "content": "越权"}]},
    ).json()
    assert response["code"] == 4004

    messages = client.get(
        f"/api/chat/sessions/{session_id}/messages", headers=OTHER_HEADERS
    ).json()
    assert messages["code"] == 4004


def test_internal_chain_forwards_request_id(client, monkeypatch) -> None:
    """内部链路按“先校验积分、后上报计费”的顺序调用，并透传 requestId。"""

    calls: list[tuple[str, str, str, dict]] = []

    async def fake_call_internal(service_name, method, path, **kwargs):
        calls.append((service_name, method, path, kwargs))
        return {"available": True}

    monkeypatch.setattr(settings, "enable_internal_chain", True)
    monkeypatch.setattr(chat_module, "call_internal", fake_call_internal)
    response = client.post(
        "/api/chat/completions",
        headers={**USER_HEADERS, "X-Request-Id": "chain-request"},
        json={"messages": [{"role": "user", "content": "hello"}]},
    )
    assert response.status_code == 200
    assert response.json()["code"] == 0
    assert [item[2] for item in calls] == [
        "/internal/user/check",
        "/internal/billing/record",
    ]
    billing_payload = calls[1][3]["json"]
    assert billing_payload["request_id"] == "chain-request"
    assert billing_payload["status"] == CallStatus.SUCCESS.value
    assert billing_payload["points"] == settings.points_cost
    assert billing_payload["duration_ms"] >= 0


def test_degraded_model_reply_is_reported_without_charge(client, monkeypatch) -> None:
    """真实模型超时：返回 5xxx 降级话术，计费上报 points=0 但仍留流水。"""

    class _DegradedModelClient:
        async def complete(self, messages, *, model, temperature, runtime):
            return ModelReply(
                content=DEGRADED_REPLY,
                call_status=CallStatus.DEGRADED.value,
                token_count=len(DEGRADED_REPLY),
                model_name=model,
                error_code=int(ModelErrorCode.TIMEOUT),
            )

    billing_calls: list[dict] = []

    async def fake_call_internal(service_name, method, path, **kwargs):
        if path == "/internal/billing/record":
            billing_calls.append(kwargs["json"])
        return {"available": True}

    monkeypatch.setattr(settings, "enable_internal_chain", True)
    monkeypatch.setattr(chat_module, "call_internal", fake_call_internal)
    monkeypatch.setattr(chat_module, "model_client", _DegradedModelClient())
    monkeypatch.setattr(chat_module, "model_runtime_config", _FakeRuntimeConfig())

    response = client.post(
        "/api/chat/completions",
        headers=USER_HEADERS,
        json={"messages": [{"role": "user", "content": "请总结这段材料"}]},
    )
    body = response.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["call_status"] == CallStatus.DEGRADED.value
    assert data["degraded"] is True
    assert data["error_code"] == int(ModelErrorCode.TIMEOUT)
    assert data["choices"][0]["message"]["content"] == DEGRADED_REPLY

    assert len(billing_calls) == 1
    assert billing_calls[0]["points"] == 0
    assert billing_calls[0]["status"] == CallStatus.DEGRADED.value

    # 降级消息同样落库，会话可查回。
    messages = client.get(
        f"/api/chat/sessions/{data['session_id']}/messages", headers=USER_HEADERS
    ).json()
    assert messages["data"]["total"] == 2
    assert messages["data"]["list"][1]["call_status"] == CallStatus.DEGRADED.value
