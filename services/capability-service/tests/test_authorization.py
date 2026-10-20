"""运营接口的实时管理员授权测试。

覆盖共享授权的调用参数、成功放行、普通用户/撤权拒绝、账号禁用、身份不匹配、
响应格式异常和依赖故障失败关闭。跨服务调用边界用 mock 替换，但断言的是真实的
请求路径、查询参数与决策逻辑；真实 user-service 联调依赖见本人任务记录。
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import BizException
from app.main import app
from app.service import authorization_service

client = TestClient(app)

HEADERS = {"X-User-Id": "7", "X-User-Name": "qa-admin", "X-Request-Id": "qa-auth"}


def _admin_data(user_id: int = 7) -> dict:
    return {
        "user_id": user_id,
        "status": "normal",
        "role": "admin",
        "authorized": True,
    }


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    data: object = None,
    error: Exception | None = None,
    recorder: dict | None = None,
) -> None:
    async def fake_call(
        service_name,
        method,
        path,
        *,
        json=None,
        params=None,
        headers=None,
        timeout=None,
    ):
        if recorder is not None:
            recorder.update(
                service_name=service_name, method=method, path=path, params=params
            )
        if error is not None:
            raise error
        return data

    monkeypatch.setattr(authorization_service, "call_internal", fake_call)


def _require_admin(monkeypatch: pytest.MonkeyPatch, **kwargs) -> None:
    _install(monkeypatch, **kwargs)
    asyncio.run(authorization_service.require_admin("7"))


def _denied(monkeypatch: pytest.MonkeyPatch, **kwargs) -> int:
    _install(monkeypatch, **kwargs)
    with pytest.raises(BizException) as raised:
        asyncio.run(authorization_service.require_admin("7"))
    return raised.value.code


# ---------------------------------------------------------------- 调用契约


def test_authorization_uses_shared_internal_contract(monkeypatch) -> None:
    """必须调用 user-service 的固定内部路径，并带当前用户与 required_role。"""

    recorder: dict = {}
    _require_admin(monkeypatch, data=_admin_data(), recorder=recorder)

    assert recorder == {
        "service_name": "user-service",
        "method": "GET",
        "path": "/internal/user/authorization",
        "params": {"user_id": 7, "required_role": "admin"},
    }


def test_admin_authorization_passes(monkeypatch) -> None:
    _require_admin(monkeypatch, data=_admin_data())


# ---------------------------------------------------------------- 拒绝


def test_permission_denied_code_maps_to_2007(monkeypatch) -> None:
    assert _denied(monkeypatch, error=BizException(1007, "权限不足")) == 2007


def test_legacy_permission_code_is_still_a_denial(monkeypatch) -> None:
    """旧 user 构建可能返回 1006；只作为拒绝码兼容，绝不据此放行。"""

    assert _denied(monkeypatch, error=BizException(1006, "权限不足")) == 2007


def test_ordinary_user_payload_is_denied(monkeypatch) -> None:
    data = {
        "user_id": 7,
        "status": "normal",
        "role": "user",
        "authorized": False,
    }
    assert _denied(monkeypatch, data=data) == 2007


def test_revoked_role_is_denied_after_previously_allowed(monkeypatch) -> None:
    """同一用户先被允许、随后撤权：每次请求重新校验，不使用本地缓存。"""

    _require_admin(monkeypatch, data=_admin_data())
    data = {"user_id": 7, "status": "normal", "role": "user", "authorized": False}
    assert _denied(monkeypatch, data=data) == 2007


# ---------------------------------------------------------------- 失败关闭


@pytest.mark.parametrize("code", [1001, 1005])
def test_identity_or_account_errors_fail_closed(monkeypatch, code: int) -> None:
    assert _denied(monkeypatch, error=BizException(code, "拒绝")) == 4002


def test_authorization_service_failure_fails_closed(monkeypatch) -> None:
    assert _denied(monkeypatch, error=RuntimeError("discovery unavailable")) == 4002


@pytest.mark.parametrize(
    "data",
    [
        None,
        [],
        {"user_id": "7", "status": "normal", "role": "admin", "authorized": True},
        {"user_id": 8, "status": "normal", "role": "admin", "authorized": True},
        {"user_id": 7, "status": "normal", "role": "admin", "authorized": "true"},
        {"user_id": 7, "role": "admin"},
    ],
)
def test_untrusted_authorization_payload_fails_closed(monkeypatch, data) -> None:
    assert _denied(monkeypatch, data=data) == 4002


@pytest.mark.parametrize("user_id", ["", "abc", "0", "-3"])
def test_invalid_current_identity_fails_closed(monkeypatch, user_id: str) -> None:
    _install(monkeypatch, data=_admin_data())
    with pytest.raises(BizException) as raised:
        asyncio.run(authorization_service.require_admin(user_id))
    assert raised.value.code == 4002


# ---------------------------------------------------------------- API 拒绝路径


def test_manage_returns_2007_for_ordinary_user(monkeypatch) -> None:
    _install(monkeypatch, error=BizException(1007, "权限不足"))

    body = client.get("/api/capability/manage", headers=HEADERS).json()

    assert body["code"] == 2007
    assert body["data"] is None
    assert "管理员" in body["message"]


def test_manage_returns_4002_when_dependency_unavailable(monkeypatch) -> None:
    _install(monkeypatch, error=TimeoutError("authorization timeout"))

    body = client.get("/api/capability/manage", headers=HEADERS).json()

    assert body["code"] == 4002
    assert "已拒绝" in body["message"]


def test_forged_role_headers_cannot_bypass_realtime_check(monkeypatch) -> None:
    """客户端伪造 role / X-User-Role 不参与决策，仍以 user-service 结果为准。"""

    _install(monkeypatch, error=BizException(1007, "权限不足"))
    forged = {**HEADERS, "X-User-Role": "admin", "role": "admin"}

    body = client.get("/api/capability/manage", headers=forged).json()

    assert body["code"] == 2007


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        (
            "post",
            "/api/capability",
            {
                "category_id": 1,
                "name": "越权能力",
                "code": "qa-denied-cap",
                "service_name": "ai-chat-service",
                "path": "/api/chat/completions",
            },
        ),
        ("put", "/api/capability/1", {"name": "越权编辑"}),
        ("delete", "/api/capability/1", None),
        ("put", "/api/capability/1/status", {"status": "online"}),
        (
            "post",
            "/api/capability/categories",
            {"name": "越权分类", "code": "qa-denied-cat"},
        ),
        ("put", "/api/capability/categories/1", {"sort": 1}),
        ("delete", "/api/capability/categories/1", None),
    ],
)
def test_write_endpoints_reject_ordinary_user(monkeypatch, method, path, payload) -> None:
    """普通用户直接请求管理 API 也在服务端被拒绝，而不是依赖前端隐藏按钮。"""

    _install(monkeypatch, error=BizException(1007, "权限不足"))

    response = client.request(method, path, headers=HEADERS, json=payload)

    assert response.status_code == 200
    assert response.json()["code"] == 2007
