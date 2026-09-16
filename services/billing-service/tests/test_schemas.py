"""schemas 纯内存测试；不依赖数据库、Nacos 与 user-service。"""

from datetime import date, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.core.constants import CallStatus, DEFAULT_CAPABILITY_ID
from app.core.exceptions import BizException
from app.schemas import BillingRecordRequest, CallRecordOut, UsageDailyOut
from app.schemas.common import STAT_DEFAULT_RANGE_DAYS, resolve_date_range


# ---------------------------------------------------------------- 记账入参


def test_record_request_accepts_ai_chat_payload() -> None:
    """接受 ai-chat-service 实际上报的字段组合。"""

    payload = BillingRecordRequest.model_validate(
        {
            "request_id": "chain-request",
            "user_id": "1",
            "service_name": "ai-chat-service",
            "model": "mock-model",
            "points": 1,
            "status": "success",
        }
    )

    assert payload.user_id == 1
    assert payload.points == 1
    assert payload.status is CallStatus.SUCCESS
    # ai-chat 未上报能力 ID 与耗时，按契约缺省为 0
    assert payload.capability_id == DEFAULT_CAPABILITY_ID
    assert payload.duration_ms == 0


@pytest.mark.parametrize("points", [-1, 1_000_001])
def test_record_request_rejects_out_of_range_points(points: int) -> None:
    with pytest.raises(ValidationError):
        BillingRecordRequest(request_id="qa-1", user_id=1, points=points)


def test_record_request_requires_request_id() -> None:
    with pytest.raises(ValidationError):
        BillingRecordRequest(request_id="", user_id=1)


def test_record_request_requires_positive_user_id() -> None:
    with pytest.raises(ValidationError):
        BillingRecordRequest(request_id="qa-1", user_id=0)


@pytest.mark.parametrize("status", ["ok", "SUCCESS", "published", ""])
def test_record_request_rejects_unknown_status(status: str) -> None:
    with pytest.raises(ValidationError):
        BillingRecordRequest(request_id="qa-1", user_id=1, status=status)


# ---------------------------------------------------------------- 统计时间范围


def test_date_range_defaults_to_recent_window() -> None:
    start, end = resolve_date_range(None, None)

    assert end == date.today()
    assert (end - start).days == STAT_DEFAULT_RANGE_DAYS - 1


def test_date_range_accepts_explicit_window() -> None:
    start, end = resolve_date_range(date(2026, 9, 1), date(2026, 9, 15))

    assert (start, end) == (date(2026, 9, 1), date(2026, 9, 15))


def test_date_range_rejects_inverted_window() -> None:
    with pytest.raises(BizException) as error:
        resolve_date_range(date(2026, 9, 16), date(2026, 9, 1))

    assert error.value.code == 2001


def test_date_range_rejects_too_wide_window() -> None:
    end = date(2026, 9, 16)
    with pytest.raises(BizException) as error:
        resolve_date_range(end - timedelta(days=400), end)

    assert error.value.code == 2001


# ---------------------------------------------------------------- 出参序列化


def test_call_record_out_serializes_time_by_contract() -> None:
    payload = CallRecordOut(
        id=1,
        request_id="qa-1",
        user_id=1,
        capability_id=0,
        service_name="ai-chat-service",
        cost=5,
        call_status="success",
        duration_ms=120,
        model_name="mock-model",
        create_time=datetime(2026, 9, 16, 10, 30, 0),
    )

    assert payload.model_dump()["create_time"] == "2026-09-16 10:30:00"


def test_usage_daily_out_serializes_date() -> None:
    payload = UsageDailyOut(stat_date=date(2026, 9, 16), call_count=3, total_cost=15)

    assert payload.model_dump()["stat_date"] == "2026-09-16"
