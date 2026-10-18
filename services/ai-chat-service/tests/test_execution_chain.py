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


def test_billing_failure_rolls_back_messages(client, monkeypatch, chain):
    previous = module.call_internal
    async def fail(service, method, path, **kwargs):
        if path == "/internal/billing/record": raise BizException(4002, "billing down")
        return await previous(service, method, path, **kwargs)
    monkeypatch.setattr(module, "call_internal", fail)
    body = client.post("/api/chat/completions", headers=USER_HEADERS,
                       json={"messages": [{"role": "user", "content": "rollback"}]}).json()
    assert body["code"] == 4002
    assert client.get("/api/chat/sessions", headers=USER_HEADERS).json()["data"]["total"] == 0


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
    assert client.get("/api/chat/sessions", headers=USER_HEADERS).json()["data"]["total"] == 0


def test_summary_degradation_preserves_unit_price_and_records_zero_cost(client, monkeypatch, chain):
    monkeypatch.setattr(module, "execute_prepared", AsyncMock(return_value=ModelReply(
        DEGRADED_REPLY, "degraded", len(DEGRADED_REPLY), "test-model", error_code=5001)))
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
