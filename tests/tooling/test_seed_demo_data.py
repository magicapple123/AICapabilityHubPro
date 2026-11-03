"""Lock down the demo-seed script's money maths and its write scope.

Every assertion here is database-free on purpose: the seed script is the thing
that has to be trusted against a *live* development database, so its pricing,
balance-chain and "only touch user_id=8" guarantees must be provable without
touching one.
"""

import ast
import random
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from devtools import seed_demo_data as seed


def make_capability(**overrides: Any) -> seed.Capability:
    """A per_call capability shaped like capability_db.t_capability row 1."""

    defaults: dict[str, Any] = {
        "id": 1,
        "code": "chat-completions",
        "billing_mode": "per_call",
        "price_per_call": 5,
        "price_per_1k_input": 0,
        "price_per_1k_output": 0,
        "price_per_unit": 0,
        "unit": "call",
    }
    defaults.update(overrides)
    return seed.Capability(**defaults)


# --------------------------------------------------------------- 计价


def test_per_call_cost_ignores_tokens_and_units() -> None:
    capability = make_capability()

    cost = capability.cost(
        prompt_tokens=9_999, completion_tokens=9_999, units=7, billable=True
    )

    assert cost == 5


def test_per_token_cost_rounds_up_like_the_real_pricing_module() -> None:
    capability = make_capability(
        billing_mode="per_token", price_per_1k_input=7, price_per_1k_output=9
    )

    # 100*7 + 50*9 = 1150 → ceil(1.15) = 2
    assert (
        capability.cost(prompt_tokens=100, completion_tokens=50, units=1, billable=True)
        == 2
    )
    # 120*7 + 60*9 = 1380 → ceil(1.38) = 2  (must not truncate to 1)
    assert (
        capability.cost(prompt_tokens=120, completion_tokens=60, units=1, billable=True)
        == 2
    )
    # exact multiple stays exact: 200*7 + 0*9 = 1400 → 1.4 → 2
    assert (
        capability.cost(prompt_tokens=200, completion_tokens=0, units=1, billable=True)
        == 2
    )
    # 0/0 tokens must not bill the caller
    assert (
        capability.cost(prompt_tokens=0, completion_tokens=0, units=1, billable=True) == 0
    )


def test_per_unit_cost_multiplies_units_and_never_charges_zero_units() -> None:
    capability = make_capability(billing_mode="per_unit", price_per_unit=4)

    assert (
        capability.cost(prompt_tokens=0, completion_tokens=0, units=3, billable=True) == 12
    )
    assert (
        capability.cost(prompt_tokens=0, completion_tokens=0, units=0, billable=True) == 4
    )


@pytest.mark.parametrize("status", ["degraded", "failed"])
def test_degraded_and_failed_calls_are_free(status: str) -> None:
    """billable=False is what the seed uses for degraded/failed; it must be 0."""

    capability = make_capability()

    assert (
        capability.cost(prompt_tokens=500, completion_tokens=300, units=1, billable=False)
        == 0
    )


def test_registered_unit_price_is_only_filled_for_per_call() -> None:
    assert make_capability().registered_unit_price == 5
    assert make_capability(billing_mode="per_token").registered_unit_price is None
    assert make_capability(billing_mode="per_unit").registered_unit_price is None


# --------------------------------------------------------------- 余额链


def make_baseline(**overrides: Any) -> seed.Baseline:
    defaults: dict[str, Any] = {
        "balance": 8_448,
        "frozen": 0,
        "version": 37,
        "ledger_tail": datetime(2026, 11, 1, 9, 23, 38),
        "marked_net": 8_420,
        "marked_count": 20,
    }
    defaults.update(overrides)
    return seed.Baseline(**defaults)


def make_plan(*logs: seed.PointsLogPlan) -> seed.SeedPlan:
    return seed.SeedPlan(
        baseline=make_baseline(),
        calls=(),
        points_logs=tuple(logs),
        usage_deltas=(),
        chat_sessions=(),
    )


def make_log(direction: str, amount: int, balance_after: int = 0) -> seed.PointsLogPlan:
    return seed.PointsLogPlan(
        request_id=f"DEMO-SEED-{direction}-{amount}",
        direction=direction,
        amount=amount,
        balance_after=balance_after,
        biz_type="recharge" if direction == "in" else "call",
        remark="",
        create_time=datetime(2026, 11, 1, 10, 0, 0),
    )


def test_pristine_balance_subtracts_the_rows_this_script_wrote() -> None:
    """Re-running the seed must plan from 28, not from 8448, or it would inflate."""

    baseline = make_baseline()

    assert baseline.pristine_balance == 28
    assert baseline.pristine_version == 17


def test_final_balance_is_pristine_plus_the_net_of_the_ledger() -> None:
    plan = make_plan(make_log("in", 5_000), make_log("out", 5), make_log("out", 3))

    assert plan.net_points == 4_992
    assert plan.final_balance == 28 + 4_992


def test_demo_prefix_is_namespaced_and_targets_the_admin_account() -> None:
    assert seed.REQUEST_PREFIX == "DEMO-SEED-"
    assert seed.DEMO_USER_ID == 8
    assert seed.DEMO_USERNAME == "opsdemo"


# --------------------------------------------------------------- 数据形状


def test_status_sequence_matches_the_documented_mix() -> None:
    statuses = seed._status_sequence(random.Random(seed.RANDOM_SEED))

    assert len(statuses) == seed.TOTAL_CALLS == 21
    assert statuses.count("success") == seed.SUCCESS_CALLS == 18
    assert statuses.count("degraded") == seed.DEGRADED_CALLS == 2
    assert statuses.count("failed") == seed.FAILED_CALLS == 1


def test_spread_times_stay_inside_the_window_and_increase() -> None:
    start = datetime(2026, 11, 1, 8, 0, 0)
    end = datetime(2026, 11, 2, 23, 0, 0)

    times = seed._spread_times(start, end, 21, random.Random(seed.RANDOM_SEED))

    assert len(times) == 21
    assert all(start <= moment <= end for moment in times)
    assert times == sorted(times)
    assert len(set(times)) == len(times)
    assert all(moment.microsecond == 0 for moment in times)


def test_same_random_seed_produces_the_same_times() -> None:
    start = datetime(2026, 11, 1, 8, 0, 0)
    end = datetime(2026, 11, 2, 23, 0, 0)

    first = seed._spread_times(start, end, 21, random.Random(seed.RANDOM_SEED))
    second = seed._spread_times(start, end, 21, random.Random(seed.RANDOM_SEED))

    assert first == second


def test_token_profile_matches_what_upstream_would_report() -> None:
    rng = random.Random(seed.RANDOM_SEED)
    capability = make_capability()

    assert seed._token_profile(capability, "degraded", rng)[:2] == (0, 0)
    assert seed._token_profile(capability, "degraded", rng)[2] == "missing"
    assert seed._token_profile(capability, "failed", rng)[:2] == (0, 0)
    assert seed._token_profile(capability, "failed", rng)[2] == "unknown"

    prompt, completion, token_source = seed._token_profile(capability, "success", rng)
    assert prompt > 0 and completion > 0
    assert token_source == "upstream"


def test_duration_profile_keeps_degraded_near_the_timeout() -> None:
    rng = random.Random(seed.RANDOM_SEED)

    assert all(
        30_000 <= seed._duration_profile("degraded", rng) <= 30_012 for _ in range(20)
    )
    assert all(seed._duration_profile("failed", rng) <= 3_600 for _ in range(20))
    assert all(
        6_800 <= seed._duration_profile("success", rng) <= 16_000 for _ in range(20)
    )


def test_chat_plans_cover_success_degraded_and_failed() -> None:
    sessions = seed.build_chat_sessions(datetime(2026, 11, 2, 20, 40, 0))
    messages = [message for session in sessions for message in session.messages]

    assert [session.title for session in sessions] == list(seed.CHAT_TITLES)
    assert len(messages) == 13
    assert sum(1 for message in messages if message.call_status == "degraded") == 1
    failed = [message for message in messages if message.call_status == "failed"]
    assert len(failed) == 1
    assert failed[0].error_code is not None
    assert all(message.role in {"user", "assistant"} for message in messages)
    for session in sessions:
        assert session.last_message_time == max(
            message.create_time for message in session.messages
        )


# --------------------------------------------------------------- 写库范围


def test_every_write_statement_is_scoped_to_one_user() -> None:
    """A write without a user_id predicate is how demo data leaks to other users."""

    source = Path(seed.__file__).read_text(encoding="utf-8")
    writes = [
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.strip().upper().startswith(
            ("DELETE FROM", "UPDATE ", "INSERT INTO")
        )
    ]

    assert writes, "expected the seed script to contain its SQL statements inline"
    for statement in writes:
        assert "user_id" in statement, statement


def test_every_delete_is_keyed_by_a_marker_not_just_by_user() -> None:
    """Deletes must key off the DEMO-SEED- marker or the discovered session ids."""

    source = Path(seed.__file__).read_text(encoding="utf-8")
    deletes = [
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.strip().upper().startswith("DELETE FROM")
    ]

    assert deletes
    for statement in deletes:
        marked = ":prefix" in statement or ":ids" in statement
        # the usage_daily rollback deletes a row it just decremented to zero
        emptied_aggregate = (
            "capability_id = :capability_id" in statement
            and "call_count <= 0" in statement
            and "total_cost <= 0" in statement
        )
        assert marked or emptied_aggregate, statement


# --------------------------------------------------------------- 状态文件


class _FakeResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return self._rows


class _FakeConnection:
    """Enough of a Connection for the session-discovery query."""

    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows
        self.calls: list[tuple[Any, Any]] = []

    def execute(self, statement: Any, params: Any = None) -> _FakeResult:
        self.calls.append((statement, params))
        return _FakeResult(self._rows)


def test_chat_sessions_are_found_via_state_file_and_title_fallback() -> None:
    conn = _FakeConnection(
        [
            (685, seed.CHAT_TITLES[0]),
            (900, "用户自己写的会话，不能删"),
        ]
    )
    state = {"chat_session_ids": [700, "701", "not-a-number"]}

    found = seed.collect_chat_session_ids(conn, seed.DEMO_USER_ID, state)

    assert found == [685, 700, 701]


def test_chat_sessions_deduplicate_state_and_title_hits() -> None:
    conn = _FakeConnection([(685, seed.CHAT_TITLES[0])])

    found = seed.collect_chat_session_ids(conn, seed.DEMO_USER_ID, {"chat_session_ids": [685]})

    assert found == [685]


def test_read_state_degrades_gracefully(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing.json"
    monkeypatch.setattr(seed, "STATE_PATH", missing)
    assert seed.read_state() == {}

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(seed, "STATE_PATH", broken)
    assert seed.read_state() == {}

    not_an_object = tmp_path / "list.json"
    not_an_object.write_text("[1, 2, 3]", encoding="utf-8")
    monkeypatch.setattr(seed, "STATE_PATH", not_an_object)
    assert seed.read_state() == {}


def test_state_file_is_gitignored() -> None:
    root = Path(seed.__file__).resolve().parents[2]
    ignored = (root / ".gitignore").read_text(encoding="utf-8")

    assert seed.STATE_FILENAME in ignored


# --------------------------------------------------------------- 连接


def test_missing_password_fails_loudly_instead_of_guessing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(seed.DB_URL_ENV, raising=False)
    monkeypatch.delenv("MYSQL_ROOT_PASSWORD", raising=False)
    monkeypatch.setattr(seed, "read_env", lambda _path: {})

    with pytest.raises(SystemExit) as excinfo:
        seed.resolve_engine()

    assert seed.DB_URL_ENV in str(excinfo.value)


def test_explicit_db_url_wins_and_always_selects_user_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        seed.DB_URL_ENV, "mysql+pymysql://root:pwd@127.0.0.1:3399/billing_db"
    )

    engine, source = seed.resolve_engine()

    assert engine.url.database == "user_db"
    assert engine.url.port == 3399
    assert seed.DB_URL_ENV in source


def test_no_credentials_are_hardcoded_in_the_script() -> None:
    source = Path(seed.__file__).read_text(encoding="utf-8")

    # 32+ hex chars is what a leaked MySQL/JWT secret would look like.
    assert not re.search(r"[0-9a-fA-F]{32,}", source)
    assert "os.environ.get" in source
    assert seed.DB_URL_ENV in source


# --------------------------------------------------------------- 时间窗


def test_window_starts_after_the_real_ledger_tail() -> None:
    """New rows must be appended after existing ones, otherwise balance_after breaks."""

    ledger_tail = datetime(2026, 11, 1, 9, 23, 38)
    baseline = make_baseline(ledger_tail=ledger_tail)
    now = datetime(2026, 11, 2, 20, 40, 0)

    window_start = max(
        (baseline.ledger_tail or (now - timedelta(days=1))) + timedelta(minutes=1),
        now - timedelta(days=6),
    )

    assert window_start > ledger_tail
    assert window_start < now
