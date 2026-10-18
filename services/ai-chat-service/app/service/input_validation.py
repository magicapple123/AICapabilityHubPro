"""Bounded JSON Schema validation; references cannot trigger network retrieval."""
import json
from jsonschema import Draft202012Validator, SchemaError, ValidationError
from app.core.exceptions import BizException


def _check_structure(value: object, depth: int = 0) -> int:
    if depth > 20:
        raise ValueError("Structure exceeds depth budget")
    nodes = 1
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"$ref", "$dynamicRef", "$recursiveRef", "$id"}:
                raise ValueError("Schema references are not supported")
            nodes += _check_structure(child, depth + 1)
    elif isinstance(value, list):
        nodes += sum(_check_structure(child, depth + 1) for child in value)
    if nodes > 2000:
        raise ValueError("Structure exceeds node budget")
    return nodes


def validate_capability_input(schema: dict, payload: dict) -> None:
    try:
        if len(json.dumps(schema, ensure_ascii=False)) > 32768:
            raise ValueError("Schema too large")
        _check_structure(schema)
        if schema.get("type") != "object":
            raise ValueError("Only object schemas can describe capability inputs")
        Draft202012Validator.check_schema(schema)
    except (ValueError, TypeError, SchemaError, RecursionError) as error:
        raise BizException(4002, "能力参数 Schema 配置无效") from error
    try:
        if len(json.dumps(payload, ensure_ascii=False)) > 65536:
            raise ValueError("Input too large")
        # Do not log ValidationError.message: it can contain the user's input.
        Draft202012Validator(schema).validate(payload)
    except (ValueError, TypeError, ValidationError, RecursionError) as error:
        raise BizException(2001, "参数不符合所选能力的 Schema") from error
