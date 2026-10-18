"""Project one settled execution into the compatible completion response."""
import time
from uuid import uuid4
from app.core.logging import get_request_id


def completion_result(*, definition, session, message, reply, prompt_tokens, duration_ms, receipt) -> dict:
    return {
        "id": f"chatcmpl-{uuid4().hex}", "object": "chat.completion",
        "created": int(time.time()), "model": reply.model_name,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": reply.content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": reply.token_count,
                  "total_tokens": prompt_tokens + reply.token_count},
        "session_id": session.id, "message_id": message.id,
        "mock": reply.mock, "call_status": reply.call_status,
        "degraded": reply.degraded, "error_code": reply.error_code,
        "duration_ms": duration_ms, "request_id": get_request_id(),
        "capability_id": definition.id, "capability_code": definition.code,
        "price_per_call": definition.price_per_call,
        "cost": receipt["cost"] if receipt else 0,
        "record_id": receipt["record_id"] if receipt else None,
        "billing_status": "recorded" if receipt else "not_reported",
        "catalog_source": definition.catalog_source,
    }
