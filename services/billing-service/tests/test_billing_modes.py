"""C1/C2 计量扩展测试：token 明细落库、按 token / 按件计价的校验与幂等。

两条防线：
1. `BillingRecordRequest` 在**入口**就按模式复算一次实扣金额（防止上游算错价）；
2. `t_call_record` 保留 token 明细，可按 requestId 复核（人工对账）。
"""

from datetime import date

import pytest

from app.schemas.internal import BillingRecordRequest

TODAY = date.today()


def _body(**extra):
    body = {"request_id": "qa-mode-1", "user_id": 1, "points": 0, "status": "success"}
    body.update(extra)
    return body


# ---------------------------------------------------------------- 入口校验（纯模型）


def test_per_call_keeps_legacy_equality_rule():
    assert BillingRecordRequest(**_body(points=5, unit_price=5)).points == 5
    with pytest.raises(ValueError):
        BillingRecordRequest(**_body(points=4, unit_price=5))


def test_per_call_degraded_must_be_zero():
    assert BillingRecordRequest(
        **_body(points=0, unit_price=5, status="degraded")
    ).points == 0
    with pytest.raises(ValueError):
        BillingRecordRequest(**_body(points=5, unit_price=5, status="degraded"))


def test_per_token_recomputes_cost_from_detail():
    payload = _body(
        billing_mode="per_token", prompt_tokens=3000, completion_tokens=1050,
        price_per_1k_input=1, price_per_1k_output=1, points=5,
    )
    assert BillingRecordRequest(**payload).points == 5
    # 4.05 必须向上取整为 5；报 4 属于少扣，入口直接拒绝。
    with pytest.raises(ValueError):
        BillingRecordRequest(**{**payload, "points": 4})


def test_per_token_rejects_zero_tokens_on_success():
    with pytest.raises(ValueError):
        BillingRecordRequest(**_body(
            billing_mode="per_token", prompt_tokens=0, completion_tokens=0,
            price_per_1k_input=1, price_per_1k_output=1, points=0,
        ))


def test_per_token_without_price_copy_skips_recompute():
    """旧调用方不带单价副本时跳过复算，保持历史兼容。"""

    payload = _body(billing_mode="per_token", prompt_tokens=10, completion_tokens=10, points=3)
    assert BillingRecordRequest(**payload).points == 3


def test_per_unit_requires_price_times_units():
    payload = _body(
        billing_mode="per_unit", units=3, price_per_unit=4, points=12,
    )
    assert BillingRecordRequest(**payload).units == 3
    with pytest.raises(ValueError):
        BillingRecordRequest(**{**payload, "points": 11})


def test_legacy_body_without_any_new_field_still_valid():
    """红线 3：旧调用方只发老字段，必须继续被接受。"""

    parsed = BillingRecordRequest(**_body(points=1, unit_price=1))
    assert parsed.billing_mode == "per_call"
    assert parsed.units == 1
    assert parsed.token_source == "unknown"


# ---------------------------------------------------------------- 落库与幂等（连库）


def test_token_detail_is_persisted_and_echoed(qa, fake_user_service):
    request_id = qa.next_request_id()
    body = qa.record(
        points=5, request_id=request_id, capability_id=3,
        billing_mode="per_token", prompt_tokens=3000, completion_tokens=1050,
        token_source="upstream", price_per_1k_input=1, price_per_1k_output=1,
    )
    assert body["code"] == 0, body
    data = body["data"]
    assert data["billing_mode"] == "per_token"
    assert (data["prompt_tokens"], data["completion_tokens"]) == (3000, 1050)
    assert data["token_source"] == "upstream"
    assert data["cost"] == 5

    # 通过对外查询验证真的落库了，而不是只在响应里回显
    listed = qa.records(start_date=TODAY.isoformat(), end_date=TODAY.isoformat())
    row = [item for item in listed["data"]["list"] if item["request_id"] == request_id][0]
    assert row["billing_mode"] == "per_token"
    assert (row["prompt_tokens"], row["completion_tokens"]) == (3000, 1050)
    assert row["token_source"] == "upstream"


def test_per_unit_record_persists_units(qa, fake_user_service):
    request_id = qa.next_request_id()
    body = qa.record(
        points=12, request_id=request_id, capability_id=4,
        billing_mode="per_unit", units=3, price_per_unit=4, unit_price=None,
    )
    assert body["code"] == 0, body
    assert body["data"]["units"] == 3 and body["data"]["cost"] == 12


def test_replay_with_different_token_detail_is_rejected(qa, fake_user_service):
    """同一 requestId 但 token 明细不同 -> 3002，不能静默改写已落的账。"""

    request_id = qa.next_request_id()
    first = qa.record(
        points=5, request_id=request_id, billing_mode="per_token",
        prompt_tokens=3000, completion_tokens=1050,
        price_per_1k_input=1, price_per_1k_output=1,
    )
    assert first["code"] == 0

    replay = qa.record(
        points=6, request_id=request_id, billing_mode="per_token",
        prompt_tokens=6000, completion_tokens=0,
        price_per_1k_input=1, price_per_1k_output=1,
    )
    assert replay["code"] == 3002


def test_replay_identical_token_detail_is_idempotent(qa, fake_user_service):
    request_id = qa.next_request_id()
    payload = dict(
        points=5, request_id=request_id, billing_mode="per_token",
        prompt_tokens=3000, completion_tokens=1050,
        price_per_1k_input=1, price_per_1k_output=1,
    )
    first = qa.record(**payload)
    second = qa.record(**payload)
    assert first["code"] == 0 and second["code"] == 0
    assert second["data"]["duplicated"] is True
    assert second["data"]["record_id"] == first["data"]["record_id"]
