"""user-service 数据库行为测试。

覆盖 team-tasks 第 4.1 节要求的注册、登录、重复扣分、余额不足与禁用用户，
并补充 API Key、资料、积分流水与内部链路身份校验。

所有用例通过真实接口调用并连接真实 MySQL（表由 `sql/01_init.sql` 创建），
数据库不可用时整组自动跳过，原因见 `tests/conftest.py`。
"""

import jwt
import pytest

from app.core.constants import ApiKeyStatus, PointBizType, PointDirection, UserStatus
from app.core.config import settings
from tests.conftest import (
    DB_REASON,
    DB_READY,
    TEST_JWT_SECRET,
    QaUser,
    count_points_logs,
    read_balance,
    set_user_status,
)

pytestmark = pytest.mark.skipif(not DB_READY, reason=f"需要可用的 user_db：{DB_REASON}")


# ---------------------------------------------------------------- 注册 / 登录


def test_register_creates_account_with_initial_points(qa: QaUser) -> None:
    """注册即创建积分账户并赠送初始积分，同时落一条收入流水。"""

    data = qa.register()

    assert data["username"] == qa.username
    assert data["balance"] == settings.initial_points == data["initial_points"]

    assert qa.points()["data"]["balance"] == settings.initial_points

    logs = qa.logs()["data"]
    assert logs["total"] == 1
    entry = logs["list"][0]
    assert entry["direction"] == PointDirection.IN.value
    assert entry["biz_type"] == PointBizType.REGISTER.value
    assert entry["amount"] == settings.initial_points
    assert entry["request_id"] == f"register-{qa.user_id}"


def test_register_duplicate_username_returns_1004(qa: QaUser) -> None:
    qa.register()

    body = qa.register_raw()
    assert body["code"] == 1004
    assert body["data"] is None


def test_login_returns_gateway_compatible_jwt(qa: QaUser) -> None:
    """签发的 JWT 必须能被网关同款校验规则解析（iss + sub + username）。"""

    qa.register()
    body = qa.login_raw()

    assert body["code"] == 0
    token = body["data"]["token"]
    claims = jwt.decode(
        token,
        TEST_JWT_SECRET,
        algorithms=["HS256"],
        issuer=settings.jwt_issuer,
    )

    assert claims["sub"] == str(qa.user_id)
    assert claims["username"] == qa.username
    assert body["data"]["expire_at"]


def test_login_with_wrong_password_returns_1003(qa: QaUser) -> None:
    qa.register()

    assert qa.login_raw(password="wrong-password")["code"] == 1003


def test_login_with_unknown_username_returns_1003(qa: QaUser) -> None:
    assert qa.login_raw(username=f"{qa.username}none")["code"] == 1003


def test_disabled_user_cannot_login(qa: QaUser) -> None:
    qa.register()
    set_user_status(qa.user_id, UserStatus.DISABLED.value)

    body = qa.login_raw()
    assert body["code"] == 1005
    assert body["data"] is None


# ---------------------------------------------------------------- 资料


def test_profile_read_and_update(qa: QaUser) -> None:
    qa.register()

    profile = qa.profile()["data"]
    assert profile["username"] == qa.username
    assert profile["status"] == UserStatus.NORMAL.value
    assert "password_hash" not in profile and "password" not in profile

    updated = qa.update_profile("新昵称")
    assert updated["code"] == 0
    assert updated["data"]["nickname"] == "新昵称"
    assert qa.profile()["data"]["nickname"] == "新昵称"


def test_profile_of_disabled_user_returns_1005(qa: QaUser) -> None:
    qa.register()
    set_user_status(qa.user_id, UserStatus.DISABLED.value)

    assert qa.profile()["code"] == 1005


# ---------------------------------------------------------------- API Key


def test_create_api_key_returns_secret_only_once(qa: QaUser) -> None:
    qa.register()

    created = qa.create_key("首个 Key")["data"]
    assert created["access_key"].startswith("ak_")
    assert created["secret_key"].startswith("sk_")
    assert created["secret_mask"].endswith(created["secret_key"][-4:])
    assert created["status"] == ApiKeyStatus.ENABLED.value

    listed = qa.list_keys()["data"]["list"]
    assert len(listed) == 1
    # 列表不再回传完整密钥与摘要
    assert "secret_key" not in listed[0]
    assert "secret_hash" not in listed[0]
    assert listed[0]["secret_mask"] == created["secret_mask"]


def test_disable_api_key_is_idempotent(qa: QaUser) -> None:
    qa.register()
    key_id = qa.create_key()["data"]["id"]

    first = qa.disable_key(key_id)
    second = qa.disable_key(key_id)

    assert first["code"] == 0 and second["code"] == 0
    assert second["data"]["status"] == ApiKeyStatus.DISABLED.value
    assert qa.list_keys()["data"]["list"][0]["status"] == ApiKeyStatus.DISABLED.value


def test_cannot_disable_another_users_api_key(qa: QaUser) -> None:
    """访问他人 Key 与访问不存在的 Key 返回同一错误码，不暴露存在性。"""

    qa.register()
    key_id = qa.create_key()["data"]["id"]

    other = QaUser(qa.client)
    other.register()

    assert other.disable_key(key_id)["code"] == 1006
    # 原持有者的 Key 未被改动
    assert qa.list_keys()["data"]["list"][0]["status"] == ApiKeyStatus.ENABLED.value


# ---------------------------------------------------------------- 积分流水


def test_points_logs_pagination_and_filter(qa: QaUser) -> None:
    qa.register()
    qa.deduct(amount=1)

    first_page = qa.logs(page=1, page_size=1)["data"]
    assert first_page["total"] == 2
    assert len(first_page["list"]) == 1
    assert first_page["page"] == 1 and first_page["page_size"] == 1

    only_out = qa.logs(direction="out")["data"]
    assert only_out["total"] == 1
    assert only_out["list"][0]["direction"] == PointDirection.OUT.value

    only_in = qa.logs(direction="in")["data"]
    assert only_in["total"] == 1
    assert only_in["list"][0]["direction"] == PointDirection.IN.value


# ---------------------------------------------------------------- 内部校验


def test_internal_check_returns_balance_and_availability(qa: QaUser) -> None:
    qa.register()

    body = qa.check(points_cost=settings.initial_points)
    assert body["code"] == 0
    assert body["data"]["available"] is True
    assert body["data"]["balance"] == settings.initial_points
    assert body["data"]["status"] == UserStatus.NORMAL.value


def test_internal_check_rejects_insufficient_points(qa: QaUser) -> None:
    qa.register()

    body = qa.check(points_cost=settings.initial_points + 1)
    assert body["code"] == 3001
    assert body["data"] is None


def test_internal_check_rejects_disabled_user(qa: QaUser) -> None:
    qa.register()
    set_user_status(qa.user_id, UserStatus.DISABLED.value)

    assert qa.check()["code"] == 1005


def test_internal_check_rejects_unknown_user(qa: QaUser) -> None:
    qa.register()

    assert qa.check(user_id=99_999_999)["code"] == 1005


# ---------------------------------------------------------------- 扣分


def test_deduct_reduces_balance_and_writes_log(qa: QaUser) -> None:
    qa.register()
    request_id = qa.next_request_id()

    body = qa.deduct(amount=5, request_id=request_id)

    assert body["code"] == 0
    assert body["data"]["balance_after"] == settings.initial_points - 5
    assert body["data"]["duplicated"] is False
    assert read_balance(qa.user_id) == settings.initial_points - 5

    entry = qa.logs(direction="out")["data"]["list"][0]
    assert entry["request_id"] == request_id
    assert entry["amount"] == 5
    assert entry["balance_after"] == settings.initial_points - 5


def test_repeated_deduct_with_same_request_id_is_idempotent(qa: QaUser) -> None:
    """重复扣分（billing 重试）只扣一次费，返回首次结果。"""

    qa.register()
    request_id = qa.next_request_id()

    first = qa.deduct(amount=5, request_id=request_id)
    second = qa.deduct(amount=5, request_id=request_id)

    assert first["code"] == 0 and second["code"] == 0
    assert second["data"]["duplicated"] is True
    assert second["data"]["balance_after"] == first["data"]["balance_after"]
    assert read_balance(qa.user_id) == settings.initial_points - 5

    logs = qa.logs(direction="out")["data"]
    assert logs["total"] == 1


def test_deduct_rejects_insufficient_balance_without_side_effect(qa: QaUser) -> None:
    """余额不足返回 3001，余额与流水都不变化（不留半成功状态）。"""

    qa.register()

    body = qa.deduct(amount=settings.initial_points + 1)

    assert body["code"] == 3001
    assert body["data"] is None
    assert read_balance(qa.user_id) == settings.initial_points
    assert qa.logs(direction="out")["data"]["total"] == 0


def test_deduct_rejects_disabled_user(qa: QaUser) -> None:
    qa.register()
    set_user_status(qa.user_id, UserStatus.DISABLED.value)

    assert qa.deduct(amount=1)["code"] == 1005
    # 禁用后读接口同样被拦（见下方参数化用例），因此直接读库确认没有扣分流水。
    assert count_points_logs(qa.user_id, direction="out") == 0


def test_balance_never_goes_negative_under_sequential_deducts(qa: QaUser) -> None:
    """条件更新保证余额不会为负：扣到刚好为 0 后继续扣返回 3001。"""

    qa.register()
    total = settings.initial_points

    assert qa.deduct(amount=total)["code"] == 0
    assert read_balance(qa.user_id) == 0

    assert qa.deduct(amount=1)["code"] == 3001
    assert read_balance(qa.user_id) == 0


# ---------------------------------------------------------------- 禁用用户统一拦截

# 受保护接口清单。网关只校验 JWT 签名与有效期、不知道账号已被禁用，因此禁用账号
# 的旧 Token 在过期前仍能通过网关；这些接口必须自行校验账号状态并返回 1005。
DISABLED_BLOCKED_ENDPOINTS: list[tuple[str, str, dict[str, str] | None]] = [
    ("GET", "/api/user/profile", None),
    ("PUT", "/api/user/profile", {"nickname": "禁用后改昵称"}),
    ("GET", "/api/user/apikeys", None),
    ("POST", "/api/user/apikeys", {"name": "禁用后新建"}),
    # 禁用后按 id 禁用 Key 也被拦：账号状态校验先于 1006 的存在性校验。
    ("PUT", "/api/user/apikeys/1/disable", None),
    ("GET", "/api/user/points", None),
    ("GET", "/api/user/points/logs", None),
]


@pytest.mark.parametrize(("method", "path", "payload"), DISABLED_BLOCKED_ENDPOINTS)
def test_disabled_user_is_blocked_on_every_protected_endpoint(
    qa: QaUser, method: str, path: str, payload: dict[str, str] | None
) -> None:
    qa.register()
    set_user_status(qa.user_id, UserStatus.DISABLED.value)

    body = qa.client.request(method, path, headers=qa.headers, json=payload).json()

    assert body["code"] == 1005
    assert body["data"] is None


def test_disabled_user_create_api_key_leaves_no_new_key(qa: QaUser) -> None:
    """禁用账号创建 Key 被拦后，库里不应多出凭据。"""

    qa.register()
    key_id = qa.create_key()["data"]["id"]
    set_user_status(qa.user_id, UserStatus.DISABLED.value)

    assert qa.create_key("禁用后新建")["code"] == 1005

    # 恢复后才能观察：列表仍只有禁用前创建的那一把
    set_user_status(qa.user_id, UserStatus.NORMAL.value)
    keys = qa.list_keys()["data"]
    assert keys["total"] == 1
    assert keys["list"][0]["id"] == key_id


def test_access_is_restored_after_user_is_reenabled(qa: QaUser) -> None:
    """恢复 normal 后同一个 Token 又能访问，证明拦截只取决于账号状态。"""

    qa.register()
    set_user_status(qa.user_id, UserStatus.DISABLED.value)
    assert qa.points()["code"] == 1005

    set_user_status(qa.user_id, UserStatus.NORMAL.value)
    body = qa.points()

    assert body["code"] == 0
    assert body["data"]["balance"] == settings.initial_points
