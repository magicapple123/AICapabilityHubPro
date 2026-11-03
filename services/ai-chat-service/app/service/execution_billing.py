"""Trusted points preflight and settlement; never accepts a browser supplied price."""
from app.core.config import settings
from app.core.constants import BillingMode, TokenSource
from app.core.exceptions import BizException
from app.core.logging import get_request_id
from app.schemas.capability import CapabilityDefinition
from app.service.model_client import ModelReply
from app.service.pricing import call_cost, preflight_points, units_for

# 上游没给 usage 时无法按 token 计价：失败关闭，宁可不让调用成功也不产生糊涂账。
MISSING_USAGE_CODE = 5002
MISSING_USAGE_MESSAGE = "上游未返回 token 用量，无法按 token 计费，已拒绝结算"


async def check_points(
    user_id: str, definition: CapabilityDefinition, *, units: int = 1, call_internal,
) -> int:
    """预检余额，返回本次要求的最低余额门槛。"""

    price = preflight_points(definition, units=units)
    data = await call_internal(
        settings.user_service_name, "GET", "/internal/user/check",
        params={"user_id": user_id, "points_cost": price},
    )
    if not isinstance(data, dict) or data.get("user_id") != int(user_id):
        raise BizException(4002, "积分校验响应格式错误")
    if data.get("status") != "normal":
        raise BizException(1005, "用户不存在或已被禁用")
    if type(data.get("balance")) is not int or data.get("points_cost") != price:
        raise BizException(4002, "积分校验响应格式错误")
    if data.get("available") is not True or data["balance"] < price:
        raise BizException(3001, "积分不足")
    return price


async def report_execution(
    user_id: str, definition: CapabilityDefinition, reply: ModelReply,
    duration_ms: int, *, units: int = 1, call_internal,
    api_key_id: int | None = None, entrypoint: str = "web",
) -> dict:
    request_id = get_request_id()
    billable = not reply.degraded
    if (
        billable
        and definition.billing_mode == BillingMode.PER_TOKEN.value
        and reply.usage_source != TokenSource.UPSTREAM.value
    ):
        # Mock 与"上游未给 usage"都不能按 token 结算：前者不是真值，后者无依据。
        raise BizException(MISSING_USAGE_CODE, MISSING_USAGE_MESSAGE)

    effective_units = units_for(definition.billing_mode, units)
    points = call_cost(
        definition,
        prompt_tokens=reply.prompt_tokens,
        completion_tokens=reply.completion_tokens,
        units=effective_units,
        billable=billable,
    )
    payload = {
        "request_id": request_id, "user_id": int(user_id),
        "capability_id": definition.id,
        # per_call 保持"单价=实扣"的旧语义；按 token / 按件时单价不是实扣金额。
        "unit_price": definition.price_per_call
        if definition.billing_mode == BillingMode.PER_CALL.value else None,
        "billing_mode": definition.billing_mode,
        "units": effective_units,
        "prompt_tokens": reply.prompt_tokens,
        "completion_tokens": reply.completion_tokens,
        "token_source": reply.usage_source,
        # 单价副本：billing 侧独立复算，避免算错价后静默记账。
        "price_per_1k_input": definition.price_per_1k_input,
        "price_per_1k_output": definition.price_per_1k_output,
        "price_per_unit": definition.price_per_unit,
        "service_name": settings.service_name, "model": reply.model_name,
        "points": points, "status": reply.call_status, "duration_ms": duration_ms,
        # D3：文生图的图片产物随收据一起上报，调用记录才能事后预览。
        # 只上报结构化字段（url / revised_prompt），不传二进制；非文生图为空列表。
        "images": [
            {
                "url": str(item.get("url") or ""),
                "revised_prompt": str(item.get("revised_prompt") or ""),
            }
            for item in (reply.images or [])
            if isinstance(item, dict) and item.get("url")
        ],
        "remark": f"{definition.code} mode={definition.billing_mode} price={points}"
                  + (f" degraded={reply.error_code}" if reply.degraded else ""),
        # P6：Key 身份与入口。没有 Key 身份时为 None（billing 落 NULL），
        # 不能用 0 占位——按 Key 聚合并不会把 0 当"未知"。
        "api_key_id": api_key_id,
        "entrypoint": entrypoint,
    }
    receipt = await call_internal(
        settings.billing_service_name, "POST", "/internal/billing/record", json=payload,
    )
    if (
        not isinstance(receipt, dict)
        or type(receipt.get("record_id")) is not int or receipt["record_id"] < 1
        or receipt.get("request_id") != request_id
        or receipt.get("user_id") != int(user_id)
        or receipt.get("capability_id") != definition.id
        or receipt.get("cost") != points
        or receipt.get("call_status") != reply.call_status
    ):
        raise BizException(4002, "计费收据与当前能力调用不一致，请按 requestId 核对")
    if definition.billing_mode == BillingMode.PER_TOKEN.value and billable:
        if (
            receipt.get("prompt_tokens") != reply.prompt_tokens
            or receipt.get("completion_tokens") != reply.completion_tokens
        ):
            raise BizException(4002, "计费收据 token 明细与本次调用不一致，请按 requestId 核对")
    return receipt
