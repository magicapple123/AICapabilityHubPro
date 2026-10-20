"""内部能力详情与目录 Schema/价格边界。

覆盖 `GET /internal/capability/{id}` 的字段契约、真实状态、未知/软删除、
身份要求、目录配置损坏时的失败关闭，以及市场响应字段最小化。
数据库不可用时整组跳过，原因见 `tests/conftest.py`。
"""

import pytest
from sqlalchemy import text

from app.db.session import engine
from tests.conftest import DB_REASON, DB_READY, USER_HEADERS, QaCatalog

pytestmark = pytest.mark.skipif(
    not DB_READY, reason=f"需要可用的 capability_db：{DB_REASON}"
)

CHAT_SCHEMA = {
    "type": "object",
    "properties": {
        "messages": {
            "type": "array",
            "minItems": 1,
            "maxItems": 40,
            "items": {
                "type": "object",
                "properties": {
                    "role": {
                        "type": "string",
                        "enum": ["system", "user", "assistant"],
                    },
                    "content": {"type": "string", "minLength": 1, "maxLength": 12000},
                },
                "required": ["role", "content"],
                "additionalProperties": False,
            },
        },
        "temperature": {"type": "number", "minimum": 0, "maximum": 2},
    },
    "required": ["messages"],
    "additionalProperties": False,
}


def _create_online(qa: QaCatalog, *, price: int = 5) -> dict:
    category = qa.category()
    body = qa.create_capability_raw(
        category["id"],
        code=qa.code("internal"),
        name=f"QAInternal-{qa.token}",
        status="online",
        price=price,
        param_schema=CHAT_SCHEMA,
    )
    assert body["code"] == 0, body
    return body["data"]


def _update_row(capability_id: int, assignment: str, value=None) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(f"UPDATE t_capability SET {assignment} = :value WHERE id = :id"),
            {"value": value, "id": capability_id},
        )


# ---------------------------------------------------------------- 字段契约


def test_internal_detail_returns_contract_fields(qa: QaCatalog) -> None:
    capability = _create_online(qa, price=5)

    body = qa.internal_detail(capability["id"])

    assert body["code"] == 0
    assert body["requestId"] == USER_HEADERS["X-Request-Id"]
    data = body["data"]
    assert data["id"] == capability["id"]
    assert data["name"] == capability["name"]
    assert data["code"] == capability["code"]
    assert data["status"] == "online"
    assert data["price_per_call"] == 5
    assert data["param_schema"] == CHAT_SCHEMA
    # 内部详情不提供 service_name / path 等可被任意代理的配置。
    assert set(data) == {
        "id",
        "name",
        "code",
        "status",
        "param_schema",
        "price_per_call",
    }


def test_internal_detail_requires_trusted_identity(qa: QaCatalog) -> None:
    capability = _create_online(qa)

    body = qa.internal_detail(capability["id"], headers={})

    assert body["code"] == 1001


# ---------------------------------------------------------------- 状态


@pytest.mark.parametrize("status", ["draft", "offline"])
def test_internal_detail_keeps_real_status(qa: QaCatalog, status: str) -> None:
    """草稿/下架必须如实返回状态，由执行器拒绝，不能伪装成 online。"""

    category = qa.category()
    body = qa.create_capability_raw(
        category["id"],
        code=qa.code("state"),
        status=status,
        price=4,
        param_schema=CHAT_SCHEMA,
    )
    capability = body["data"]

    detail = qa.internal_detail(capability["id"])

    assert detail["code"] == 0
    assert detail["data"]["status"] == status


def test_status_change_is_visible_on_next_read(qa: QaCatalog) -> None:
    """内部详情不缓存，上下架后下一次读取立即生效。"""

    capability = _create_online(qa)
    assert qa.set_status(capability["id"], "offline")["code"] == 0

    assert qa.internal_detail(capability["id"])["data"]["status"] == "offline"


# ---------------------------------------------------------------- 不存在


def test_unknown_capability_returns_2002(qa: QaCatalog) -> None:
    body = qa.internal_detail(999_999_999)

    assert body["code"] == 2002
    assert body["data"] is None


def test_soft_deleted_capability_returns_2002(qa: QaCatalog) -> None:
    capability = _create_online(qa)
    assert qa.delete_capability(capability["id"])["code"] == 0

    body = qa.internal_detail(capability["id"])

    assert body["code"] == 2002
    assert qa.market_detail(capability["id"])["code"] == 2002


# ---------------------------------------------------------------- 配置边界


def test_missing_schema_fails_closed(qa: QaCatalog) -> None:
    capability = _create_online(qa)
    _update_row(capability["id"], "param_schema", None)

    body = qa.internal_detail(capability["id"])

    assert body["code"] == 4002


def test_schema_with_reference_fails_closed(qa: QaCatalog) -> None:
    capability = _create_online(qa)
    _update_row(
        capability["id"],
        "param_schema",
        '{"type":"object","properties":{"x":{"$ref":"https://evil.example/schema"}}}',
    )

    assert qa.internal_detail(capability["id"])["code"] == 4002


def test_negative_price_fails_closed(qa: QaCatalog) -> None:
    capability = _create_online(qa)
    _update_row(capability["id"], "price_per_call", -1)

    assert qa.internal_detail(capability["id"])["code"] == 4002


def test_unknown_status_fails_closed(qa: QaCatalog) -> None:
    capability = _create_online(qa)
    _update_row(capability["id"], "status", "published")

    assert qa.internal_detail(capability["id"])["code"] == 4002


@pytest.mark.parametrize("price", [0, 1_000_000])
def test_internal_detail_accepts_price_boundaries(qa: QaCatalog, price: int) -> None:
    capability = _create_online(qa, price=price)

    detail = qa.internal_detail(capability["id"])

    assert detail["code"] == 0
    assert detail["data"]["price_per_call"] == price


@pytest.mark.parametrize("price", [-1, 1_000_001])
def test_registration_rejects_out_of_range_price(qa: QaCatalog, price: int) -> None:
    category = qa.category()

    body = qa.create_capability_raw(
        category["id"], code=qa.code("badprice"), price=price
    )

    assert body["code"] == 2001


# ---------------------------------------------------------------- Schema 登记边界


def test_registration_accepts_inline_object_schema(qa: QaCatalog) -> None:
    capability = _create_online(qa)

    assert capability["param_schema"] == CHAT_SCHEMA


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "array", "items": {"type": "string"}},
        {"type": "object", "properties": {"x": {"$ref": "#/definitions/x"}}},
        {"type": "object", "properties": {"x": {"$id": "remote"}}},
        "not-an-object",
        {"properties": {}},
    ],
)
def test_registration_rejects_incompatible_schema(qa: QaCatalog, schema) -> None:
    """只接受对象根类型的内联 Schema，引用关键字与远程 ID 一律拒绝。"""

    category = qa.category()

    body = qa.create_capability_raw(
        category["id"], code=qa.code("badschema"), param_schema=schema
    )

    assert body["code"] == 2001


def test_registration_rejects_excessive_depth(qa: QaCatalog) -> None:
    category = qa.category()
    schema: dict = {"type": "object"}
    for _ in range(22):
        schema = {"type": "object", "properties": {"nested": schema}}

    body = qa.create_capability_raw(
        category["id"], code=qa.code("deep"), param_schema=schema
    )

    assert body["code"] == 2001


def test_registration_rejects_oversized_schema(qa: QaCatalog) -> None:
    category = qa.category()
    schema = {"type": "object", "description": "x" * 40_000}

    body = qa.create_capability_raw(
        category["id"], code=qa.code("large"), param_schema=schema
    )

    assert body["code"] == 2001


# ---------------------------------------------------------------- 市场最小暴露


def test_market_detail_hides_internal_configuration(qa: QaCatalog) -> None:
    capability = _create_online(qa)

    body = qa.market_detail(capability["id"])

    assert body["code"] == 0
    assert set(body["data"]) == {
        "id",
        "name",
        "code",
        "category_id",
        "category_name",
        "description",
        "price_per_call",
        "update_time",
        "param_schema",
    }
    assert "service_name" not in body["data"]
    assert "path" not in body["data"]
    assert "status" not in body["data"]
