"""P6 Key 归因：`X-User-Key-Id` → `UserContext` → 账单上报体（`api_key_id` / `entrypoint`）。

两条入口各断言一次，全部用替身，不碰真实 Secret、不连真实下游：

1. 平台 API（`/api/chat/completions`，网关注入 `X-User-Key-Id`）：
   带该头 → `api_key_id` 为整数且 `entrypoint == "platform_api"`；
   不带该头 → `api_key_id is None`（**不能变成 0**）且 `entrypoint == "web"`。
2. OpenAI 兼容（`/v1/chat/completions`，`Bearer sk_...`）：
   `api_key_id` 等于 `/internal/user/apikey/verify` 返回的 `key_id`，
   `entrypoint == "openai_compat"`。

实现口径按现成接口：`security.current_user` 解析头、`logging.use_identity` 透传 Key、
`execution_billing.report_execution` 写进上报体。这些文件都不在本用例的改动范围。
"""

import importlib

import pytest

from app.api.v1 import openai_compat
from app.core.config import settings
from app.service.catalog_cache import OpenAIModelCatalog
from tests.conftest import TEST_USER_ID, USER_HEADERS

# `app.service` 包导出的 `chat_service` 是实例，会遮蔽同名模块；
# monkeypatch 必须打在模块里的符号上。
chat_module = importlib.import_module("app.service.chat_service")

KEY_HEADERS = {**USER_HEADERS, "X-User-Key-Id": "42"}
ANON_HEADERS = dict(USER_HEADERS)
COMPAT_HEADERS = {"Authorization": "Bearer sk_test-only-secret-value"}

CAPABILITY_SCHEMA = {
    "type": "object",
    "required": ["messages"],
    "properties": {"messages": {"type": "array", "minItems": 1}},
}


def _internal_reply(path, kwargs):
    """user check / billing record 的最小可信响应。"""

    if path == "/internal/user/check":
        params = kwargs["params"]
        return {
            "user_id": int(params["user_id"]), "status": "normal",
            "balance": 100, "available": True, "points_cost": params["points_cost"],
        }
    payload = kwargs["json"]
    return {
        "record_id": 1, "request_id": payload["request_id"], "user_id": payload["user_id"],
        "capability_id": payload["capability_id"], "cost": payload["points"],
        "call_status": payload["status"],
    }


@pytest.fixture(autouse=True)
def catalog(monkeypatch):
    """只替换目录边界；执行链、计费、落库都是真实代码。"""

    from app.schemas.capability import CapabilityDefinition

    def definition(capability_id):
        return CapabilityDefinition(
            id=capability_id, code="chat-completions", status="online",
            price_per_call=5, param_schema=CAPABILITY_SCHEMA,
        )

    async def fetch(capability_id):
        return definition(capability_id)

    async def openai_model_catalog():
        return OpenAIModelCatalog({"deepseek-flash": 1}, frozenset({1}))

    monkeypatch.setattr(chat_module.capability_client, "fetch", fetch)
    monkeypatch.setattr(
        openai_compat.capability_client, "openai_model_catalog", openai_model_catalog,
    )
    monkeypatch.setattr(openai_compat, "expected_internal_token", lambda: "token")
    monkeypatch.setattr(settings, "enable_internal_chain", True)


class _Recorder:
    """把内部调用记下来，供断言检查账单上报体。"""

    def __init__(self) -> None:
        self.billing: list[dict] = []

    async def fake_call_internal(self, service_name, method, path, **kwargs):
        if path == "/internal/billing/record":
            self.billing.append(kwargs["json"])
        return _internal_reply(path, kwargs)


# ---------------------------------------------------------------- 平台 API 入口


def test_platform_api_reports_key_id_and_entrypoint(client, monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(chat_module, "call_internal", recorder.fake_call_internal)

    response = client.post(
        "/api/chat/completions",
        headers=KEY_HEADERS,
        json={"messages": [{"role": "user", "content": "带 Key 身份的一次调用"}]},
    )
    body = response.json()
    assert body["code"] == 0, body

    assert len(recorder.billing) == 1
    payload = recorder.billing[0]
    assert type(payload["api_key_id"]) is int
    assert payload["api_key_id"] == 42
    assert payload["entrypoint"] == "platform_api"


def test_platform_api_without_key_header_reports_null_not_zero(client, monkeypatch):
    """网页调试台没有 Key 身份：必须是 None（billing 落 NULL），不能伪造成 0。"""

    recorder = _Recorder()
    monkeypatch.setattr(chat_module, "call_internal", recorder.fake_call_internal)

    response = client.post(
        "/api/chat/completions",
        headers=ANON_HEADERS,
        json={"messages": [{"role": "user", "content": "没有 Key 身份的一次调用"}]},
    )
    body = response.json()
    assert body["code"] == 0, body

    payload = recorder.billing[0]
    assert payload["api_key_id"] is None
    assert payload["api_key_id"] != 0
    assert payload["entrypoint"] == "web"


def test_invalid_key_header_is_treated_as_no_key():
    """`X-User-Key-Id` 非法（非数字/0/空）时降级成"没有 Key 身份"，不阻断请求。"""

    from app.core.security import current_user

    def resolve(key_id: str = ""):
        # `current_user` 是 FastAPI 依赖：参数默认值是 Header(...) 描述对象，
        # 直调时必须把四个参数都显式给出，否则其余参数会拿到 Header 实例并被 Pydantic 拒绝。
        return current_user(
            x_user_id="1", x_user_name="tester", x_request_id="qa",
            x_user_key_id=key_id,
        )

    assert resolve("abc").api_key_id is None
    assert resolve("0").api_key_id is None
    assert resolve("").api_key_id is None
    assert resolve("7").api_key_id == 7
    assert resolve("").entrypoint == "web"
    assert resolve("7").entrypoint == "platform_api"


# ---------------------------------------------------------------- OpenAI 兼容入口


def test_openai_compat_reports_key_id_and_entrypoint(client, monkeypatch):
    """`/v1/**` 用 API Key 接入：账单必须记为 openai_compat + verify 返回的 key_id。"""

    recorder = _Recorder()
    verified: list[dict] = []

    async def fake_call_internal(service_name, method, path, **kwargs):
        if path == "/internal/user/apikey/verify":
            verified.append(kwargs["json"])
            return {
                "user_id": int(TEST_USER_ID), "username": "qa-runner", "role": "user",
                "key_id": 77, "access_key": "ak_test",
            }
        return await recorder.fake_call_internal(service_name, method, path, **kwargs)

    monkeypatch.setattr(openai_compat, "call_internal", fake_call_internal)
    monkeypatch.setattr(chat_module, "call_internal", fake_call_internal)

    response = client.post(
        "/v1/chat/completions",
        headers=COMPAT_HEADERS,
        json={"model": "deepseek-flash", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 200, response.text

    # 只推 secret 的 sha256，不出现明文（这也是兼容层唯一的凭据通道）。
    assert verified and set(verified[0]) == {"secret_hash"}
    assert "sk_test-only-secret-value" not in str(verified[0])

    assert len(recorder.billing) == 1
    payload = recorder.billing[0]
    assert type(payload["api_key_id"]) is int
    assert payload["api_key_id"] == 77
    assert payload["entrypoint"] == "openai_compat"
