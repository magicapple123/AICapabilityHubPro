"""Fixture tests never connect to a service, Docker or any database."""
from subprocess import CompletedProcess

import pytest

from leader_e2e import browser_accounts as accounts


@pytest.fixture()
def setup(monkeypatch):
    state = {"registered": {"user_id": 42, "role": "user"},
             "login": {"user_id": 42, "role": "admin", "token": "qa-token-in-memory"},
             "profile": {"user_id": 42, "role": "admin", "status": "normal"},
             "http": [], "sql": [], "rows": "ROW_COUNT()\n1\n"}

    class Api:
        def __init__(self, base, token=None):
            self.token = token

        def ok(self, method, path, payload=None):
            state["http"].append((method, path))
            key = {"/api/user/register": "registered", "/api/user/login": "login",
                   "/api/user/profile": "profile"}[path]
            if key == "registered":
                assert set(payload) == {"username", "password"}
                state["username"] = payload["username"]
            if key == "profile":
                assert self.token == state["login"]["token"]
            return {"data": state[key]}, {}

    def sql(statement):
        state["sql"].append(statement)
        return CompletedProcess([], 0, state["rows"], "")

    monkeypatch.setattr(accounts, "Api", Api)
    return state, sql


def prepare(sql, **changes):
    options = {"gateway": "http://127.0.0.1:19191", "sql": sql,
               "container_name": "aihub-pro-leader-qa-unit", "owned": True}
    return accounts.prepare_browser_admin(**{**options, **changes})


def test_only_newly_registered_qa_row_can_be_promoted(setup):
    state, sql = setup
    account = prepare(sql)
    assert account.user_id == 42 and account.username.startswith("qabr")
    assert len(account.password) >= 24
    assert account.password not in repr(account)
    assert len(state["sql"]) == 1
    statement = state["sql"][0]
    assert "id=42" in statement and f"username='{account.username}'" in statement
    assert "role='user' AND status='normal'" in statement
    assert state["http"] == [("POST", "/api/user/register"), ("POST", "/api/user/login"),
                             ("GET", "/api/user/profile")]


@pytest.mark.parametrize("changes", [
    {"owned": False}, {"container_name": "aihub-pro-mysql"},
    {"gateway": "http://127.0.0.1:8080"}, {"gateway": "https://example.com:19191"},
    {"gateway": "http://127.0.0.1:19191/api"},
    {"gateway": "http://name:password@127.0.0.1:19191"},
])
def test_non_owned_or_developer_targets_fail_before_any_io(setup, changes):
    state, sql = setup
    with pytest.raises(RuntimeError, match="owned isolated"):
        prepare(sql, **changes)
    assert state["http"] == state["sql"] == []


@pytest.mark.parametrize("user_id", [None, 0, "42", True])
def test_registration_must_return_a_positive_integer_identity(setup, user_id):
    state, sql = setup
    state["registered"]["user_id"] = user_id
    with pytest.raises(RuntimeError, match="registration"):
        prepare(sql)
    assert state["sql"] == []


def test_registration_cannot_start_as_admin(setup):
    state, sql = setup
    state["registered"]["role"] = "admin"
    with pytest.raises(RuntimeError, match="registration"):
        prepare(sql)
    assert state["sql"] == []


@pytest.mark.parametrize("rows", ["ROW_COUNT()\n0\n", "ROW_COUNT()\n2\n", ""])
def test_promotion_requires_exactly_one_affected_row(setup, rows):
    state, sql = setup
    state["rows"] = rows
    with pytest.raises(RuntimeError, match="exactly one"):
        prepare(sql)
    assert len(state["http"]) == 1


def test_promotion_errors_do_not_continue_to_login(setup):
    state, _ = setup

    def fail(_):
        raise RuntimeError("controlled QA SQL failure")

    with pytest.raises(RuntimeError, match="SQL failure"):
        prepare(fail)
    assert len(state["http"]) == 1


@pytest.mark.parametrize("part, field, value", [
    ("login", "role", "user"), ("login", "token", ""), ("login", "user_id", 99),
    ("profile", "role", "user"), ("profile", "status", "disabled"),
    ("profile", "user_id", 99),
])
def test_login_and_current_profile_must_confirm_the_same_admin(setup, part, field, value):
    state, sql = setup
    state[part][field] = value
    with pytest.raises(RuntimeError, match="administrator"):
        prepare(sql)
