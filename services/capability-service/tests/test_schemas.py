"""schemas 层校验测试；纯内存校验，不依赖数据库与 Nacos。"""

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.core.constants import CapabilityStatus, CategoryStatus
from app.models import Capability
from app.schemas import (
    CapabilityCreateRequest,
    CapabilityInternalOut,
    CapabilityMarketOut,
    CapabilityStatusUpdateRequest,
    CapabilityUpdateRequest,
    CategoryCreateRequest,
    CategoryUpdateRequest,
)


def test_category_create_applies_defaults() -> None:
    payload = CategoryCreateRequest(name="语言处理", code="nlp")
    assert payload.sort == 0
    assert payload.status is CategoryStatus.ENABLED


@pytest.mark.parametrize("code", ["NLP-1", "nlp_1", "-nlp", "nlp 1", ""])
def test_category_create_rejects_invalid_code(code: str) -> None:
    with pytest.raises(ValidationError):
        CategoryCreateRequest(name="语言处理", code=code)


def test_category_update_requires_at_least_one_field() -> None:
    with pytest.raises(ValidationError):
        CategoryUpdateRequest()


def test_category_update_rejects_explicit_null() -> None:
    with pytest.raises(ValidationError):
        CategoryUpdateRequest(name=None)


def test_category_update_keeps_unset_fields_out_of_dump() -> None:
    payload = CategoryUpdateRequest(status=CategoryStatus.DISABLED)
    assert payload.model_dump(exclude_unset=True) == {
        "status": CategoryStatus.DISABLED
    }


def test_capability_update_does_not_accept_status() -> None:
    """status 只能走 PUT /api/capability/{id}/status，单独提交 status 应被拒绝。"""

    with pytest.raises(ValidationError):
        CapabilityUpdateRequest(status="online")


def test_capability_create_defaults_to_draft() -> None:
    payload = CapabilityCreateRequest(
        category_id=1,
        name="多轮对话",
        code="chat-completions",
        service_name="ai-chat-service",
        path="/api/chat/completions",
    )
    assert payload.status is CapabilityStatus.DRAFT
    assert payload.price_per_call == 0
    assert payload.description == ""


@pytest.mark.parametrize("status", ["bad", "ONLINE", "published", ""])
def test_status_update_rejects_unknown_status(status: str) -> None:
    with pytest.raises(ValidationError):
        CapabilityStatusUpdateRequest(status=status)


def test_capability_create_rejects_negative_price() -> None:
    with pytest.raises(ValidationError):
        CapabilityCreateRequest(
            category_id=1,
            name="多轮对话",
            code="chat-completions",
            service_name="ai-chat-service",
            path="/api/chat/completions",
            price_per_call=-1,
        )


def test_market_out_never_exposes_internal_fields() -> None:
    """市场接口属网关白名单，出参不得包含内部地址与状态字段。"""

    exposed = set(CapabilityMarketOut.model_fields)
    assert "service_name" not in exposed
    assert "path" not in exposed
    assert "status" not in exposed
    assert {"id", "name", "code", "category_id", "category_name", "price_per_call"} <= exposed


def test_market_out_serializes_datetime_by_contract() -> None:
    payload = CapabilityMarketOut(
        id=1,
        name="多轮对话",
        code="chat-completions",
        category_id=1,
        category_name="语言处理",
        description="",
        price_per_call=5,
        update_time=datetime(2026, 9, 15, 10, 30, 0),
    )
    assert payload.model_dump()["update_time"] == "2026-09-15 10:30:00"


def _valid_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "messages": {
                "type": "array",
                "minItems": 1,
                "maxItems": 40,
                "items": {
                    "type": "object",
                    "properties": {
                        "role": {"type": "string", "enum": ["user", "assistant"]},
                        "content": {"type": "string", "maxLength": 12000},
                    },
                    "required": ["role", "content"],
                },
            }
        },
        "required": ["messages"],
        "additionalProperties": False,
    }


def test_capability_create_accepts_inline_object_schema() -> None:
    payload = CapabilityCreateRequest(
        category_id=1,
        name="多轮对话",
        code="chat-completions",
        service_name="ai-chat-service",
        path="/api/chat/completions",
        param_schema=_valid_schema(),
    )
    assert payload.param_schema == _valid_schema()


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "array"},
        {"type": "object", "properties": {"x": {"$ref": "#/x"}}},
        {"type": "object", "properties": {"x": {"$dynamicRef": "#x"}}},
        {"type": "object", "properties": {"x": {"$recursiveRef": "#"}}},
        {"type": "object", "properties": {"x": {"$id": "https://example.test"}}},
        {"properties": {}},
    ],
)
def test_capability_create_rejects_incompatible_schema(schema: dict) -> None:
    """只接受对象根类型且不含引用关键字的内联 Schema。"""

    with pytest.raises(ValidationError):
        CapabilityCreateRequest(
            category_id=1,
            name="多轮对话",
            code="chat-completions",
            service_name="ai-chat-service",
            path="/api/chat/completions",
            param_schema=schema,
        )


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "properties": []},
        {"type": "object", "properties": {"x": {"type": "not-a-real-type"}}},
        {"type": "object", "required": "messages"},
    ],
)
def test_capability_create_rejects_invalid_draft_schema(schema: dict) -> None:
    """非法 Draft 2020-12 关键字必须在登记时拒绝，而不是留到执行期。"""

    with pytest.raises(ValidationError):
        CapabilityCreateRequest(
            category_id=1,
            name="多轮对话",
            code="chat-completions",
            service_name="ai-chat-service",
            path="/api/chat/completions",
            param_schema=schema,
        )


def test_capability_create_rejects_price_over_limit() -> None:
    with pytest.raises(ValidationError):
        CapabilityCreateRequest(
            category_id=1,
            name="多轮对话",
            code="chat-completions",
            service_name="ai-chat-service",
            path="/api/chat/completions",
            price_per_call=1_000_001,
        )


def test_internal_out_requires_object_schema_and_known_status() -> None:
    payload = {
        "id": 1,
        "name": "多轮对话",
        "code": "chat-completions",
        "status": "online",
        "param_schema": _valid_schema(),
        "price_per_call": 5,
    }
    assert CapabilityInternalOut.model_validate(payload).status == "online"

    with pytest.raises(ValidationError):
        CapabilityInternalOut.model_validate({**payload, "param_schema": None})
    with pytest.raises(ValidationError):
        CapabilityInternalOut.model_validate({**payload, "param_schema": {"type": "array"}})
    with pytest.raises(ValidationError):
        CapabilityInternalOut.model_validate({**payload, "status": "published"})
    with pytest.raises(ValidationError):
        CapabilityInternalOut.model_validate({**payload, "price_per_call": -1})


def test_internal_out_from_row_excludes_target_configuration() -> None:
    capability = Capability(
        id=1,
        category_id=1,
        name="多轮对话",
        code="chat-completions",
        service_name="ai-chat-service",
        path="/api/chat/completions",
        param_schema=_valid_schema(),
        price_per_call=5,
        status="online",
        description="",
    )

    data = CapabilityInternalOut.from_row(capability).model_dump()

    assert set(data) == {
        "id",
        "name",
        "code",
        "status",
        "param_schema",
        "price_per_call",
    }
    assert "service_name" not in data
    assert "path" not in data
