"""C2 计价公式的纯函数测试（不连数据库、不连上游）。"""

import pytest

from app.schemas.capability import CapabilityDefinition
from app.service.pricing import call_cost, preflight_points, units_for


def definition(**changes):
    data = {
        "id": 1, "code": "chat-completions", "status": "online",
        "param_schema": {"type": "object"}, "price_per_call": 5,
    }
    return CapabilityDefinition(**{**data, **changes})


def test_per_call_keeps_legacy_price_and_is_not_affected_by_tokens():
    cap = definition()
    assert call_cost(cap, prompt_tokens=9999, completion_tokens=9999) == 5
    assert preflight_points(cap) == 5


def test_per_call_ignores_units():
    """按次计费与件数无关：传了 units 也只扣一次的钱。"""

    cap = definition(price_per_call=5)
    assert units_for("per_call", 3) == 1
    assert call_cost(cap, units=3) == 5
    assert preflight_points(cap, units=3) == 5


def test_per_token_rounds_up_once_over_the_weighted_sum():
    """1000 tokens = 1 积分：4050 tokens 应为 5 积分（4.05 向上取整）。"""

    cap = definition(
        billing_mode="per_token", price_per_call=0,
        price_per_1k_input=1, price_per_1k_output=1,
    )
    assert call_cost(cap, prompt_tokens=3000, completion_tokens=1050) == 5


def test_per_token_respects_direction_prices():
    cap = definition(
        billing_mode="per_token", price_per_call=0,
        price_per_1k_input=2, price_per_1k_output=8,
    )
    # 1000*2 + 500*8 = 6000 -> 6 积分；不能把两个方向混成一个平均价。
    assert call_cost(cap, prompt_tokens=1000, completion_tokens=500) == 6


def test_per_token_zero_tokens_costs_zero():
    cap = definition(billing_mode="per_token", price_per_call=0, price_per_1k_input=3)
    assert call_cost(cap, prompt_tokens=0, completion_tokens=0) == 0


def test_per_token_single_token_still_costs_one_unit():
    cap = definition(billing_mode="per_token", price_per_call=0, price_per_1k_input=1)
    assert call_cost(cap, prompt_tokens=1, completion_tokens=0) == 1


def test_per_unit_multiplies_units():
    cap = definition(
        billing_mode="per_unit", price_per_call=0, price_per_unit=4, unit="张",
    )
    assert call_cost(cap, units=3) == 12
    assert units_for("per_unit", 3) == 3
    assert units_for("per_unit", 0) == 1  # 非法件数回落 1，不允许 0 元出图


def test_per_token_preflight_uses_one_k_token_threshold():
    cap = definition(
        billing_mode="per_token", price_per_call=0,
        price_per_1k_input=2, price_per_1k_output=9,
    )
    # 够 1k token 的门槛取较大方向，避免用低价方向把门槛压到 2。
    assert preflight_points(cap) == 9


def test_per_token_preflight_never_zero():
    cap = definition(billing_mode="per_token", price_per_call=0, price_per_1k_input=0,
                     price_per_1k_output=0)
    assert preflight_points(cap) == 1


def test_per_unit_preflight_multiplies_units():
    cap = definition(billing_mode="per_unit", price_per_call=0, price_per_unit=6, unit="张")
    assert preflight_points(cap, units=2) == 12


def test_degraded_call_is_never_billed():
    cap = definition()
    assert call_cost(cap, prompt_tokens=100, completion_tokens=100, billable=False) == 0
    token_cap = definition(billing_mode="per_token", price_per_call=0, price_per_1k_input=5)
    assert call_cost(token_cap, prompt_tokens=1000, completion_tokens=1000, billable=False) == 0
