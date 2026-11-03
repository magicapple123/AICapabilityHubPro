"""P14 pure unit checks: no database, HTTP or password material."""

import importlib
from types import SimpleNamespace

import pytest

from app.core.exceptions import BizException
from app.schemas import LoginRequest
from app.service.login_protection import LoginProtection, fingerprint
from app.service.user_service import UserService
from app.core.security import UserContext


def assert_locked(guard, account, peer):
    with pytest.raises(BizException) as error:
        guard.check(account, peer)
    assert error.value.code == 4001
    assert "锁定" in error.value.message


def test_five_failures_lock_sixth_even_from_another_ip():
    guard = LoginProtection()
    for index in range(5):
        guard.check("member", f"peer-{index}")
        guard.failed("member", f"peer-{index}")
    assert_locked(guard, "member", "new-peer")
    guard.check("different-member", "new-peer")


def test_account_case_variants_share_a_window():
    guard = LoginProtection(account_limit=1)
    guard.failed("Member", "peer")
    assert_locked(guard, "MEMBER", "other-peer")


def test_ip_window_blocks_spraying_other_accounts():
    guard = LoginProtection(ip_limit=3)
    for index in range(3):
        guard.failed(f"member-{index}", "peer")
    assert_locked(guard, "new-member", "peer")
    guard.check("new-member", "another-peer")


def test_cooldown_expiry_unlocks_account_and_ip():
    now = [100.0]
    guard = LoginProtection(account_limit=1, ip_limit=1, clock=lambda: now[0])
    guard.failed("member", "peer")
    assert_locked(guard, "member", "peer")
    now[0] += 901
    guard.check("member", "peer")


def test_old_failures_leave_sliding_window():
    now = [100.0]
    guard = LoginProtection(clock=lambda: now[0])
    for _ in range(4):
        guard.failed("member", "peer")
    now[0] += 301
    guard.failed("member", "peer")
    guard.check("member", "peer")


def test_success_clears_account_but_not_ip_failure_budget():
    guard = LoginProtection(account_limit=2, ip_limit=2)
    guard.failed("member", "peer")
    guard.succeeded("member", "peer")
    guard.failed("member", "peer")
    guard.check("member", "another-peer")
    assert_locked(guard, "other-member", "peer")


def test_storage_retains_only_fingerprints():
    guard = LoginProtection()
    guard.failed("synthetic-account", "203.0.113.4")
    keys = str(list(guard._windows))
    assert "synthetic-account" not in keys
    assert "203.0.113.4" not in keys
    assert fingerprint("synthetic-account") in keys


def test_storage_full_fails_closed_and_expired_entries_are_reclaimed():
    now = [100.0]
    guard = LoginProtection(max_entries=2, clock=lambda: now[0])
    guard.failed("member", "peer")
    with pytest.raises(BizException) as error:
        guard.check("new-member", "peer")
    assert error.value.code == 4001
    now[0] += 301
    guard.check("new-member", "peer")
    assert len(guard._windows) == 2


def test_login_lock_prevents_password_hash_work(monkeypatch):
    module = importlib.import_module("app.service.user_service")
    guard = LoginProtection(account_limit=1)
    guard.failed("synthetic-account", "peer")
    monkeypatch.setattr(module, "login_protection", guard)
    audits = []
    monkeypatch.setattr(module, "record_failure", lambda db, **data: audits.append(data))

    class Users:
        def find_by_username(self, db, username):
            pytest.fail("locked login must stop before user lookup/password hashing")

    with pytest.raises(BizException) as error:
        UserService(users=Users()).login(
            object(), LoginRequest(username="synthetic-account", password="test-only-value"),
            peer_ip="peer",
        )
    assert error.value.code == 4001
    assert audits[0]["reason"] == "locked"


def test_failure_audit_has_no_raw_account_or_credentials(monkeypatch):
    module = importlib.import_module("app.service.login_audit")
    staged = []
    monkeypatch.setattr(module, "stage", lambda db, **data: staged.append(data))
    commits = []
    db = SimpleNamespace(commit=lambda: commits.append(True))
    module.record_failure(
        db, username="synthetic-account", peer_ip="203.0.113.4",
        reason="invalid_credentials", user_id=42,
    )
    assert commits == [True]
    assert staged[0]["action"] == "login_failed"
    assert staged[0]["resource_id"] == 42
    assert staged[0]["actor"].user_id == "anonymous"
    assert "synthetic-account" not in str(staged)
    assert "203.0.113.4" not in str(staged)
    assert set(staged[0]["after"]) == {"reason", "account_fingerprint", "peer_fingerprint"}


def test_authenticated_dependency_checks_current_account_state(monkeypatch):
    deps = importlib.import_module("app.api.v1.deps")
    seen = []
    db = object()

    def active(session, user_id):
        seen.append((session, user_id))

    monkeypatch.setattr(deps, "require_available_user", active)
    assert deps.current_user_id(UserContext(user_id="42"), db) == 42
    assert seen == [(db, 42)]


def test_authenticated_dependency_rejects_disabled_account(monkeypatch):
    deps = importlib.import_module("app.api.v1.deps")

    def disabled(session, user_id):
        raise BizException(1005, "用户不存在或已被禁用")

    monkeypatch.setattr(deps, "require_available_user", disabled)
    with pytest.raises(BizException) as error:
        deps.current_user_id(UserContext(user_id="42"), object())
    assert error.value.code == 1005


@pytest.mark.parametrize("raw", ["", "0", "-1", "invalid"])
def test_authenticated_dependency_rejects_invalid_identity_before_db(raw, monkeypatch):
    deps = importlib.import_module("app.api.v1.deps")

    def unexpected(*args):
        pytest.fail("malformed identity must not read account state")

    monkeypatch.setattr(deps, "require_available_user", unexpected)
    with pytest.raises(BizException) as error:
        deps.current_user_id(UserContext(user_id=raw), object())
    assert error.value.code == 1001
