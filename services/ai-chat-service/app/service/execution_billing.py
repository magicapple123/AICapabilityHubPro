"""Trusted points preflight and settlement; never accepts a browser supplied price."""
from app.core.config import settings
from app.core.exceptions import BizException
from app.core.logging import get_request_id
from app.schemas.capability import CapabilityDefinition
from app.service.model_client import ModelReply


async def check_points(user_id: str, price: int, *, call_internal) -> None:
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


async def report_execution(
    user_id: str, definition: CapabilityDefinition, reply: ModelReply,
    duration_ms: int, *, call_internal,
) -> dict:
    request_id = get_request_id()
    points = 0 if reply.degraded else definition.price_per_call
    payload = {
        "request_id": request_id, "user_id": int(user_id),
        "capability_id": definition.id, "unit_price": definition.price_per_call,
        "service_name": settings.service_name, "model": reply.model_name,
        "points": points, "status": reply.call_status, "duration_ms": duration_ms,
        "remark": f"{definition.code} price={definition.price_per_call}"
                  + (f" degraded={reply.error_code}" if reply.degraded else ""),
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
    return receipt
