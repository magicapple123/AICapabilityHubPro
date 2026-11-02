"""Project one settled execution into the compatible completion response."""
import time
from uuid import uuid4
from app.core.logging import get_request_id


def completion_result(*, definition, session, message, reply, duration_ms, receipt) -> dict:
    """组装对外的 completion 响应。

    `usage` 三个字段全部来自上游 `usage`（C1），`usage_source` 明确区分
    "上游真值 / Mock 估算 / 上游未给"，便于调用方判断 token 数可否用于核算。
    旧字段（`price_per_call` / `cost` / `record_id` / `billing_status`）保持不变。
    """

    prompt_tokens = reply.prompt_tokens
    completion_tokens = reply.completion_tokens
    return {
        "id": f"chatcmpl-{uuid4().hex}", "object": "chat.completion",
        "created": int(time.time()), "model": reply.model_name,
        "choices": [{
            "index": 0,
            # E2：message 里回传 tool_calls，finish_reason 为 tool_calls。
            "message": {
                "role": "assistant",
                "content": reply.content,
                **({"tool_calls": reply.tool_calls} if reply.tool_calls else {}),
            },
            "finish_reason": reply.finish_reason,
            # D3：文生图结果（url 列表）；文本执行器不带该字段。
            **({"images": reply.images} if reply.images else {}),
        }],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                  "total_tokens": prompt_tokens + completion_tokens},
        "usage_source": reply.usage_source,
        "session_id": session.id, "message_id": message.id,
        "mock": reply.mock, "call_status": reply.call_status,
        "degraded": reply.degraded, "error_code": reply.error_code,
        "duration_ms": duration_ms, "request_id": get_request_id(),
        "capability_id": definition.id, "capability_code": definition.code,
        "price_per_call": definition.price_per_call,
        "billing_mode": definition.billing_mode,
        "cost": receipt["cost"] if receipt else 0,
        "record_id": receipt["record_id"] if receipt else None,
        "billing_status": "recorded" if receipt else "not_reported",
        "catalog_source": definition.catalog_source,
    }
