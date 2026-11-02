"""计价：唯一的价格计算入口，禁止在 service 里散落 `price_per_call` 乘法。

三套模式（C2 冻结）：
- `per_call`  ：按次，`price_per_call`，旧能力零变化；
- `per_token` ：`ceil((prompt*price_1k_in + completion*price_1k_out) / 1000)`，
                基准 **1000 tokens = 1 积分**；
- `per_unit`  ：按件（如"张"），`price_per_unit * units`。

整数运算：不使用 float，`ceil` 由 `-(-a // b)` 实现，避免 0.1+0.2 类误差导致
少扣或多扣。降级/失败一律 0（沿用既有"降级不计费"语义）。
"""

from app.core.constants import BillingMode
from app.schemas.capability import CapabilityDefinition

TOKENS_PER_PRICE_UNIT = 1000


def _ceil_div(numerator: int, denominator: int) -> int:
    """整数向上取整；numerator 非负、denominator 为正。"""

    if numerator <= 0:
        return 0
    return -(-numerator // denominator)


def units_for(billing_mode: str, units: int | None) -> int:
    """单次调用的计件数量；非 per_unit 模式恒为 1。"""

    if billing_mode != BillingMode.PER_UNIT.value:
        return 1
    return units if isinstance(units, int) and units >= 1 else 1


def preflight_points(definition: CapabilityDefinition, *, units: int = 1) -> int:
    """预检时要求的最低余额。

    `per_token` 在执行前无法预知 token 数，因此改为"够 1k token"的门槛：
    取输入/输出单价的较大者，保证低价方向不会把门槛压到 0。
    """

    mode = definition.billing_mode
    if mode == BillingMode.PER_TOKEN.value:
        return max(1, max(definition.price_per_1k_input, definition.price_per_1k_output))
    if mode == BillingMode.PER_UNIT.value:
        return definition.price_per_unit * units_for(mode, units)
    return definition.price_per_call


def call_cost(
    definition: CapabilityDefinition,
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    units: int = 1,
    billable: bool = True,
) -> int:
    """本次调用的积分费用；`billable=False`（降级/失败）恒为 0。"""

    if not billable:
        return 0
    mode = definition.billing_mode
    if mode == BillingMode.PER_TOKEN.value:
        weighted = (
            prompt_tokens * definition.price_per_1k_input
            + completion_tokens * definition.price_per_1k_output
        )
        return _ceil_div(weighted, TOKENS_PER_PRICE_UNIT)
    if mode == BillingMode.PER_UNIT.value:
        return definition.price_per_unit * units_for(mode, units)
    return definition.price_per_call
