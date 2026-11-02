import importlib
from unittest.mock import AsyncMock
import pytest
from app.core.config import ModelRuntimeSettings, settings
from app.core.exceptions import BizException
from app.core.constants import DEGRADED_REPLY
from app.schemas.capability import CapabilityDefinition
from app.service.model_client import ModelReply
from tests.conftest import USER_HEADERS

module = importlib.import_module("app.service.chat_service")


def definition(capability_id=1, **changes):
    data = {"id": capability_id, "code": "long-summary" if capability_id == 2 else "chat-completions",
            "status": "online", "price_per_call": 3 if capability_id == 2 else 5,
            "param_schema": {"type": "object"}}
    return CapabilityDefinition(**{**data, **changes})


@pytest.fixture()
def chain(monkeypatch):
    calls = []
    async def catalog(capability_id):
        calls.append(("catalog", capability_id))
        return definition(capability_id)
    async def internal(service, method, path, **kwargs):
        calls.append((path, kwargs))
        if path == "/internal/user/check":
            return {"user_id": int(kwargs["params"]["user_id"]), "status": "normal",
                    "balance": 100, "available": True, "points_cost": kwargs["params"]["points_cost"]}
        body = kwargs["json"]
        return {"record_id": 41, "request_id": body["request_id"], "user_id": body["user_id"],
                "capability_id": body["capability_id"], "cost": body["points"], "call_status": body["status"]}
    monkeypatch.setattr(settings, "enable_internal_chain", True)
    monkeypatch.setattr(module.capability_client, "fetch", catalog)
    monkeypatch.setattr(module, "call_internal", internal)
    monkeypatch.setattr(module.model_runtime_config, "snapshot", lambda: ModelRuntimeSettings(
        use_mock=True, model_base_url="http://never-called", model_api_key="test-only"))
    return calls


@pytest.mark.parametrize("case,expected", [("offline", 2002), ("unsupported", 2008),
    ("schema", 2001), ("insufficient", 3001), ("disabled", 1005), ("catalog-failure", 4002)])
def test_rejections_never_invoke_model_or_billing(api, monkeypatch, chain, case, expected):
    async def catalog(capability_id):
        if case == "catalog-failure": raise BizException(4002, "unavailable")
        changes = {}
        if case == "offline": changes["status"] = "offline"
        if case == "unsupported": changes["code"] = "vision-parse"
        if case == "schema": changes["param_schema"] = {"type": "object", "required": ["text"]}
        return definition(**changes)
    monkeypatch.setattr(module.capability_client, "fetch", catalog)
    if case in {"insufficient", "disabled"}:
        async def denied(*args, **kwargs):
            raise BizException(3001 if case == "insufficient" else 1005, "denied")
        monkeypatch.setattr(module, "call_internal", denied)
    execute = AsyncMock(side_effect=AssertionError("Model must not be invoked"))
    monkeypatch.setattr(module, "execute_prepared", execute)
    response = api.post("/api/chat/completions", headers=USER_HEADERS,
                        json={"messages": [{"role": "user", "content": "hello"}]})
    assert response.json()["code"] == expected
    execute.assert_not_awaited()
    assert not any(item[0] == "/internal/billing/record" for item in chain)


@pytest.mark.parametrize("capability_id,price,payload", [
    (1, 5, {"messages": [{"role": "user", "content": "你好"}]}),
    (2, 3, {"text": "团队已经完成公共环境。接下来完善业务并开展联调。", "max_length": 50}),
])
def test_approved_execution_uses_catalog_price_identity_and_request_id(client, chain, capability_id, price, payload):
    response = client.post("/api/chat/completions", headers={**USER_HEADERS, "X-Request-Id": "execution-chain"},
                           json={"capability_id": capability_id, "input": payload})
    body = response.json()
    assert body["code"] == 0, body
    data = body["data"]
    assert data["capability_id"] == capability_id
    assert data["price_per_call"] == data["cost"] == price
    assert data["request_id"] == body["requestId"] == "execution-chain"
    assert data["record_id"] == 41 and data["billing_status"] == "recorded"
    assert [item[0] for item in chain] == ["catalog", "/internal/user/check", "/internal/billing/record"]
    assert chain[1][1]["params"]["points_cost"] == price
    billing = chain[2][1]["json"]
    assert billing["unit_price"] == price and billing["capability_id"] == capability_id
    assert billing["request_id"] == data["request_id"] and billing["duration_ms"] >= 0
    if capability_id == 2:
        assert "团队" in data["choices"][0]["message"]["content"]
    history = client.get(f"/api/chat/sessions/{data['session_id']}/messages", headers=USER_HEADERS).json()
    assert history["data"]["total"] == 2


def test_billing_failure_keeps_user_turn_and_marks_failure(client, monkeypatch, chain):
    """A1 语义变更：用户消息已在前一个事务提交，账单失败只回滚助手消息。

    断言从"会话=0"改为"会话=1、消息=2（user + failed 占位）"，
    这样既保留"账单失败不留下已扣费内容"的意图，也验证了失败标记不会被静默丢弃。
    """
    previous = module.call_internal
    async def fail(service, method, path, **kwargs):
        if path == "/internal/billing/record": raise BizException(4002, "billing down")
        return await previous(service, method, path, **kwargs)
    monkeypatch.setattr(module, "call_internal", fail)
    body = client.post("/api/chat/completions", headers=USER_HEADERS,
                       json={"messages": [{"role": "user", "content": "rollback"}]}).json()
    assert body["code"] == 4002
    sessions = client.get("/api/chat/sessions", headers=USER_HEADERS).json()["data"]
    assert sessions["total"] == 1
    messages = client.get(f"/api/chat/sessions/{sessions['list'][0]['id']}/messages",
                          headers=USER_HEADERS).json()["data"]
    assert messages["total"] == 2
    assert [item["role"] for item in messages["list"]] == ["user", "assistant"]
    assert messages["list"][1]["call_status"] == "failed"
    assert messages["list"][1]["error_code"] == 4002


def test_inconsistent_billing_receipt_is_not_reported_as_success(client, monkeypatch, chain):
    previous = module.call_internal
    async def wrong(service, method, path, **kwargs):
        reply = await previous(service, method, path, **kwargs)
        if path == "/internal/billing/record": reply["capability_id"] = 999
        return reply
    monkeypatch.setattr(module, "call_internal", wrong)
    body = client.post("/api/chat/completions", headers=USER_HEADERS,
                       json={"messages": [{"role": "user", "content": "receipt"}]}).json()
    assert body["code"] == 4002
    sessions = client.get("/api/chat/sessions", headers=USER_HEADERS).json()["data"]
    assert sessions["total"] == 1
    messages = client.get(f"/api/chat/sessions/{sessions['list'][0]['id']}/messages",
                          headers=USER_HEADERS).json()["data"]
    assert messages["list"][-1]["call_status"] == "failed"
    assert messages["list"][-1]["error_code"] == 4002


def test_summary_degradation_preserves_unit_price_and_records_zero_cost(client, monkeypatch, chain):
    monkeypatch.setattr(module, "execute_prepared", AsyncMock(return_value=ModelReply(
        content=DEGRADED_REPLY, call_status="degraded", model_name="test-model",
        usage_source="missing", error_code=5001)))
    body = client.post("/api/chat/completions", headers=USER_HEADERS,
                       json={"capability_id": 2, "input": {"text": "输入正文"}}).json()
    assert body["code"] == 0
    assert body["data"]["price_per_call"] == 3 and body["data"]["cost"] == 0
    assert body["data"]["degraded"] and body["data"]["error_code"] == 5001
    assert chain[-1][1]["json"]["unit_price"] == 3
    assert chain[-1][1]["json"]["points"] == 0


def test_summary_cannot_reuse_chat_session(api, chain):
    body = api.post("/api/chat/completions", headers=USER_HEADERS,
                    json={"capability_id": 2, "session_id": 1, "input": {"text": "正文"}}).json()
    assert body["code"] == 2001
    assert [item[0] for item in chain] == ["catalog"]


# ------------------------------------------------- C2 双轨计费 / A1 事务边界（本批新增）

def _token_chain(monkeypatch, *, prompt, completion, raise_on_model=None, prices=None):
    """构造按 token 计费能力的完整链路替身。

    与 `chain` fixture 的区别：billing 桩会回显 token 明细，
    用于验证"收据 token 与本次调用一致"这条强校验。
    """

    calls: list[tuple] = []
    cap = CapabilityDefinition(**{
        "id": 3, "code": "chat-completions", "status": "online",
        "param_schema": {"type": "object"}, "price_per_call": 0,
        "billing_mode": "per_token",
        **(prices or {"price_per_1k_input": 1, "price_per_1k_output": 1}),
    })

    async def catalog(capability_id):
        calls.append(("catalog", capability_id))
        return cap

    async def internal(service, method, path, **kwargs):
        calls.append((path, kwargs))
        if path == "/internal/user/check":
            return {"user_id": int(kwargs["params"]["user_id"]), "status": "normal",
                    "balance": 1000, "available": True,
                    "points_cost": kwargs["params"]["points_cost"]}
        body = kwargs["json"]
        return {"record_id": 7, "request_id": body["request_id"], "user_id": body["user_id"],
                "capability_id": body["capability_id"], "cost": body["points"],
                "call_status": body["status"], "billing_mode": body["billing_mode"],
                "prompt_tokens": body["prompt_tokens"],
                "completion_tokens": body["completion_tokens"], "units": body["units"]}

    async def execute(execution, *, runtime, model_client, **_kwargs):
        if raise_on_model is not None:
            raise raise_on_model
        return ModelReply(content="答案", call_status="success", model_name="upstream",
                          prompt_tokens=prompt, completion_tokens=completion,
                          usage_source="upstream" if prompt + completion > 0 else "missing")

    monkeypatch.setattr(settings, "enable_internal_chain", True)
    monkeypatch.setattr(module.capability_client, "fetch", catalog)
    monkeypatch.setattr(module, "call_internal", internal)
    monkeypatch.setattr(module, "execute_prepared", execute)
    return calls


def test_per_token_capability_reports_usage_and_charges_by_tokens(client, monkeypatch):
    calls = _token_chain(monkeypatch, prompt=3000, completion=1050)
    body = client.post("/api/chat/completions", headers=USER_HEADERS,
                       json={"capability_id": 3,
                             "messages": [{"role": "user", "content": "hi"}]}).json()
    assert body["code"] == 0, body
    data = body["data"]
    assert data["usage"] == {"prompt_tokens": 3000, "completion_tokens": 1050,
                             "total_tokens": 4050}
    assert data["usage_source"] == "upstream"
    # 4050 tokens，1000 tokens = 1 积分 -> 4.05 向上取整 5
    assert data["cost"] == 5 and data["billing_mode"] == "per_token"
    billing = [item for item in calls if item[0] == "/internal/billing/record"][0][1]["json"]
    assert billing["billing_mode"] == "per_token"
    assert billing["unit_price"] is None
    assert (billing["prompt_tokens"], billing["completion_tokens"]) == (3000, 1050)
    assert billing["token_source"] == "upstream"
    assert billing["points"] == 5


def test_per_token_without_upstream_usage_fails_closed_without_billing(client, monkeypatch):
    """上游没给 usage 时不能按 0 元记账，也不能编一个 token 数。"""

    calls = _token_chain(monkeypatch, prompt=0, completion=0)
    body = client.post("/api/chat/completions", headers=USER_HEADERS,
                       json={"capability_id": 3,
                             "messages": [{"role": "user", "content": "hi"}]}).json()
    assert body["code"] == 5002
    assert not [item for item in calls if item[0] == "/internal/billing/record"]
    sessions = client.get("/api/chat/sessions", headers=USER_HEADERS).json()["data"]
    assert sessions["total"] == 1
    messages = client.get(f"/api/chat/sessions/{sessions['list'][0]['id']}/messages",
                          headers=USER_HEADERS).json()["data"]["list"]
    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert messages[-1]["call_status"] == "failed" and messages[-1]["error_code"] == 5002
    assert messages[-1]["token_count"] == 0


def test_mock_usage_is_labelled_and_never_claimed_as_upstream(client, monkeypatch):
    """Mock 分支必须自报 usage_source=mock，避免被当成上游真值用于核算。"""

    monkeypatch.setattr(settings, "enable_internal_chain", False)
    async def catalog(capability_id):
        return CapabilityDefinition(id=1, code="chat-completions", status="online",
                                    param_schema={"type": "object"}, price_per_call=5)
    monkeypatch.setattr(module.capability_client, "fetch", catalog)
    body = client.post("/api/chat/completions", headers=USER_HEADERS,
                       json={"messages": [{"role": "user", "content": "你好"}]}).json()
    assert body["code"] == 0
    assert body["data"]["mock"] is True
    assert body["data"]["usage_source"] == "mock"
    assert body["data"]["usage"]["total_tokens"] > 0


def test_hard_model_failure_keeps_user_turn_and_writes_failed_placeholder(client, monkeypatch):
    """A1：模型抛异常时用户消息已提交，必须留下 failed 占位而不是"只有提问"。"""

    _token_chain(monkeypatch, prompt=1, completion=1, raise_on_model=RuntimeError("boom"))
    body = client.post("/api/chat/completions", headers=USER_HEADERS,
                       json={"capability_id": 3,
                             "messages": [{"role": "user", "content": "hi"}]}).json()
    assert body["code"] == 4003
    sessions = client.get("/api/chat/sessions", headers=USER_HEADERS).json()["data"]
    assert sessions["total"] == 1
    messages = client.get(f"/api/chat/sessions/{sessions['list'][0]['id']}/messages",
                          headers=USER_HEADERS).json()["data"]["list"]
    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "hi"
    assert messages[-1]["call_status"] == "failed" and messages[-1]["error_code"] == 4003


def test_connection_is_not_held_across_the_model_call(client, monkeypatch):
    """A1 的可验证形式：模型调用期间没有已开启的事务。

    用独立会话的 `in_transaction()` 做探针——模型调用若仍在旧事务里，
    这里会是 True，正是"连接被 3–10 秒上游调用占住"的根因。
    """

    observed: list[bool] = []
    from app.db.session import SessionLocal

    async def execute(execution, *, runtime, model_client, **_kwargs):
        probe = SessionLocal()
        try:
            observed.append(probe.in_transaction())
        finally:
            probe.close()
        return ModelReply(content="ok", call_status="success", model_name="m",
                          prompt_tokens=1, completion_tokens=1, usage_source="upstream")

    monkeypatch.setattr(settings, "enable_internal_chain", False)
    async def catalog(capability_id):
        return CapabilityDefinition(id=1, code="chat-completions", status="online",
                                    param_schema={"type": "object"}, price_per_call=5)
    monkeypatch.setattr(module.capability_client, "fetch", catalog)
    monkeypatch.setattr(module, "execute_prepared", execute)
    body = client.post("/api/chat/completions", headers=USER_HEADERS,
                       json={"messages": [{"role": "user", "content": "probe"}]}).json()
    assert body["code"] == 0
    assert observed == [False]

