"""能力参数 Schema 的内联结构约束。

AI 执行器使用 Draft 2020-12 校验输入，并拒绝远程/内部引用。目录侧在登记与
内部详情出参处做结构约束（对象根类型、大小、深度、节点数与引用关键字），
并调用 Draft 2020-12 元 Schema 校验，避免把不兼容的 Schema 包装成可执行能力；
执行器仍会按自身强类型规则复核输入边界。
"""

import json
from typing import Any

from jsonschema import Draft202012Validator, SchemaError

SCHEMA_MAX_BYTES = 32_768
SCHEMA_MAX_DEPTH = 20
SCHEMA_MAX_NODES = 2_000
FORBIDDEN_REFERENCE_KEYS = frozenset({"$ref", "$dynamicRef", "$recursiveRef", "$id"})


def _measure(value: Any, depth: int = 0) -> int:
    """统计节点数并检查深度与引用关键字。"""

    if depth > SCHEMA_MAX_DEPTH:
        raise ValueError("param_schema 嵌套层级超过 20")
    nodes = 1
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_REFERENCE_KEYS:
                raise ValueError("param_schema 不允许使用 $ref/$dynamicRef/$recursiveRef/$id")
            nodes += _measure(child, depth + 1)
    elif isinstance(value, list):
        nodes += sum(_measure(child, depth + 1) for child in value)
    if nodes > SCHEMA_MAX_NODES:
        raise ValueError("param_schema 节点数超过 2000")
    return nodes


def validate_param_schema(schema: dict[str, Any] | None) -> dict[str, Any] | None:
    """校验内联 Schema；不合法时抛出 ValueError，由调用方转换为业务错误码。"""

    if schema is None:
        return None
    if not isinstance(schema, dict):
        raise ValueError("param_schema 必须是 JSON 对象")
    try:
        encoded = json.dumps(schema, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("param_schema 必须是可序列化的 JSON 对象") from exc
    if len(encoded.encode("utf-8")) > SCHEMA_MAX_BYTES:
        raise ValueError("param_schema 序列化后不能超过 32768 字节")
    _measure(schema)
    if schema.get("type") != "object":
        raise ValueError("param_schema 根类型必须是 object")
    try:
        Draft202012Validator.check_schema(schema)
    except (SchemaError, RecursionError) as exc:
        raise ValueError("param_schema 不是合法的 Draft 2020-12 对象 Schema") from exc
    return schema
