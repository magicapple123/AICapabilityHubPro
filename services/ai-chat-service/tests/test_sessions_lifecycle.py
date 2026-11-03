"""P14 session reads fail closed when account state changes."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import sessions
from app.core.config import settings
from app.core.exceptions import BizException
from app.core.security import UserContext
from app.main import app


@pytest.mark.parametrize("path", ["/api/chat/sessions", "/api/chat/sessions/123/messages"])
def test_disabled_existing_identity_cannot_read_sessions(path, monkeypatch):
    calls = []

    async def disabled(service, method, route, **kwargs):
        calls.append((service, method, route, kwargs))
        raise BizException(1005, "用户不存在或已被禁用")

    monkeypatch.setattr(sessions, "call_internal", disabled)
    # Account security must still apply when the optional settlement chain is off.
    monkeypatch.setattr(settings, "enable_internal_chain", False)
    body = TestClient(app).get(path, headers={
        "X-User-Id": "123", "X-User-Name": "member", "X-Request-Id": "lifecycle-check",
    }).json()
    assert body["code"] == 1005
    assert body["data"] is None
    assert len(calls) == 1
    assert calls[0][2] == "/internal/user/check"
    assert calls[0][3]["params"] == {"user_id": "123", "points_cost": 0}


@pytest.mark.parametrize("raw", ["", "0", "-1", "forged"])
def test_session_identity_is_validated_before_remote_check(raw, monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("malformed identity must not query user-service")

    monkeypatch.setattr(sessions, "call_internal", forbidden)
    with pytest.raises(BizException) as error:
        asyncio.run(sessions._required_user(UserContext(user_id=raw)))
    assert error.value.code == 1001


@pytest.mark.parametrize("data,code", [
    (None, 4002), ({"user_id": 999, "status": "normal"}, 4002),
    ({"user_id": 123, "status": "disabled"}, 1005),
])
def test_remote_state_response_must_match_identity_and_be_active(data, code, monkeypatch):
    async def state(*args, **kwargs):
        return data

    monkeypatch.setattr(sessions, "call_internal", state)
    with pytest.raises(BizException) as error:
        asyncio.run(sessions._required_user(UserContext(user_id="123")))
    assert error.value.code == code


def test_active_account_is_usable_immediately_after_reenable(monkeypatch):
    state = ["disabled"]

    async def current_state(*args, **kwargs):
        return {"user_id": 123, "status": state[0]}

    monkeypatch.setattr(sessions, "call_internal", current_state)
    user = UserContext(user_id="123")
    with pytest.raises(BizException):
        asyncio.run(sessions._required_user(user))
    state[0] = "normal"
    assert asyncio.run(sessions._required_user(user)) == "123"
