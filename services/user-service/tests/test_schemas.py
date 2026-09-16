"""schemas 与安全工具的纯内存测试；不依赖数据库与 Nacos。"""

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.core.password import hash_password, verify_password
from app.schemas import (
    ApiKeyCreatedOut,
    ApiKeyOut,
    LoginOut,
    PointsDeductRequest,
    ProfileUpdateRequest,
    RegisterRequest,
    UserCheckOut,
)


# ---------------------------------------------------------------- 口令哈希


def test_password_hash_is_salted_and_verifiable() -> None:
    """同一口令两次哈希不同（加了随机盐），但都能校验通过。"""

    first = hash_password("demo123456")
    second = hash_password("demo123456")

    assert first != second
    assert verify_password("demo123456", first)
    assert verify_password("demo123456", second)


def test_password_hash_never_contains_plaintext() -> None:
    assert "demo123456" not in hash_password("demo123456")


def test_verify_password_rejects_wrong_and_malformed_hash() -> None:
    stored = hash_password("demo123456")

    assert not verify_password("wrong-password", stored)
    assert not verify_password("demo123456", "not-a-hash")
    assert not verify_password("demo123456", "bcrypt$10$abc$def")
    assert not verify_password("demo123456", "")


# ---------------------------------------------------------------- 注册 / 登录


@pytest.mark.parametrize("username", ["ab", "a" * 33, "has space", "中文名", "with@sign"])
def test_register_rejects_invalid_username(username: str) -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(username=username, password="demo123456")


@pytest.mark.parametrize("password", ["short", "a" * 129])
def test_register_rejects_invalid_password(password: str) -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(username="qauser", password=password)


def test_register_nickname_is_optional() -> None:
    payload = RegisterRequest(username="qauser", password="demo123456")

    assert payload.nickname is None


def test_login_out_serializes_expire_at_by_contract() -> None:
    payload = LoginOut(
        token="token",
        expire_at=datetime(2026, 9, 16, 10, 30, 0),
        user_id=1,
        username="qauser",
    )

    dumped = payload.model_dump()
    assert dumped["expire_at"] == "2026-09-16 10:30:00"
    assert dumped["token_type"] == "Bearer"


# ---------------------------------------------------------------- 资料


def test_profile_update_requires_nickname() -> None:
    with pytest.raises(ValidationError):
        ProfileUpdateRequest()


def test_profile_update_rejects_explicit_null() -> None:
    with pytest.raises(ValidationError):
        ProfileUpdateRequest(nickname=None)


# ---------------------------------------------------------------- API Key


def test_api_key_out_never_exposes_secret_hash() -> None:
    """列表出参只允许出现掩码，绝不能带出 secret_hash。"""

    exposed = set(ApiKeyOut.model_fields)
    assert "secret_hash" not in exposed
    assert "secret_key" not in exposed
    assert {"id", "access_key", "secret_mask", "status", "expire_time"} <= exposed

    created = set(ApiKeyCreatedOut.model_fields)
    assert "secret_key" in created  # 仅创建响应返回一次完整密钥
    assert "secret_hash" not in created


# ---------------------------------------------------------------- 积分


def test_deduct_request_rejects_non_positive_amount() -> None:
    with pytest.raises(ValidationError):
        PointsDeductRequest(user_id=1, amount=0, request_id="qa-1")


def test_deduct_request_requires_request_id() -> None:
    with pytest.raises(ValidationError):
        PointsDeductRequest(user_id=1, amount=1, request_id="")


def test_deduct_request_defaults_to_call_biz_type() -> None:
    payload = PointsDeductRequest(user_id=1, amount=1, request_id="qa-1")

    assert payload.biz_type.value == "call"


def test_user_check_out_exposes_availability() -> None:
    payload = UserCheckOut(
        user_id=1,
        username="qauser",
        status="normal",
        balance=10,
        points_cost=3,
        available=True,
    )

    assert payload.model_dump()["available"] is True
