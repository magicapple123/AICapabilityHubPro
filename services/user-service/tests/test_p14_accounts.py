"""P14 independent-MySQL account lifecycle acceptance assertions."""

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import OperationLog
from app.service.login_protection import fingerprint
from tests.conftest import QaUser, set_user_status


def test_sixth_failed_login_is_locked_and_failures_are_audited(qa: QaUser):
    qa.register()
    for _ in range(5):
        assert qa.login_raw(password="synthetic-wrong-value")["code"] == 1003
    sixth = qa.login_raw(password=qa.password)
    assert sixth["code"] == 4001
    assert "锁定" in sixth["message"]
    assert sixth["data"] is None

    account_fingerprint = fingerprint(qa.username.casefold())
    with SessionLocal() as db:
        rows = list(db.scalars(select(OperationLog).where(
            OperationLog.action == "login_failed",
            OperationLog.resource_id.in_([str(qa.user_id), account_fingerprint]),
        )))
    assert len(rows) == 6
    assert [row.after_json["reason"] for row in rows].count("invalid_credentials") == 5
    assert [row.after_json["reason"] for row in rows].count("locked") == 1
    for row in rows:
        assert row.operator_id == "anonymous"
        assert set(row.after_json) == {"reason", "account_fingerprint", "peer_fingerprint"}
        assert qa.username not in str(row.after_json)
        assert qa.password not in str(row.after_json)
        assert "synthetic-wrong-value" not in str(row.after_json)


def test_disabled_identity_is_blocked_across_authenticated_user_routes(qa: QaUser):
    qa.register()
    assert qa.login_raw()["code"] == 0
    headers = qa.headers
    set_user_status(qa.user_id, "disabled")
    for route in (
        "/api/user/profile", "/api/user/apikeys", "/api/user/points",
        "/api/user/points/logs", "/api/user/admin/users",
    ):
        response = qa.client.get(route, headers=headers).json()
        assert response["code"] == 1005, route
        assert response["data"] is None
    set_user_status(qa.user_id, "normal")
    assert qa.client.get("/api/user/profile", headers=headers).json()["code"] == 0


def test_success_between_failures_resets_account_attempts(qa: QaUser):
    qa.register()
    for _ in range(4):
        assert qa.login_raw(password="synthetic-wrong-value")["code"] == 1003
    assert qa.login_raw()["code"] == 0
    for _ in range(4):
        assert qa.login_raw(password="synthetic-wrong-value")["code"] == 1003
    assert qa.login_raw()["code"] == 0
