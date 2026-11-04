"""Bounded JSON Schema validation; references cannot trigger network retrieval."""
import json
from jsonschema import Draft202012Validator, SchemaError, ValidationError
from app.core.exceptions import BizException
from app.schemas.chat import MAX_MESSAGE_CONTENT_LENGTH

#: 整包上限 = 单条上限 × 4。单条 48000 只解决"一条消息超长"，但"简历全文 + 多轮
#: 历史"天然是多条长消息；沿用旧的 65536 字符整包上限会让两条长消息在 JSON Schema
#: 之前就被拒，且错误文案是"参数不符合 Schema"，看不出真实原因。
#: 4 倍（192000 字符，中文约 0.58 MB）既覆盖真实场景，又把单请求内存占用量级锁住。
MAX_PAYLOAD_CHARACTERS = MAX_MESSAGE_CONTENT_LENGTH * 4


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
        payload_size = len(json.dumps(payload, ensure_ascii=False))
    except (ValueError, TypeError) as error:
        raise BizException(2001, "参数无法序列化") from error
    if payload_size > MAX_PAYLOAD_CHARACTERS:
        # 与"单条消息超长"分开报：整包超限的修法是减少条数/拆分历史，不是改单条。
        raise BizException(
            2001,
            f"请求体共 {payload_size} 字符，超过单次上限 {MAX_PAYLOAD_CHARACTERS} 字符"
            "（单条消息上限 " + str(MAX_MESSAGE_CONTENT_LENGTH) + " 字符）；"
            "请减少消息条数或拆分后重试",
        )
    try:
        # Do not log ValidationError.message: it can contain the user's input.
        Draft202012Validator(schema).validate(payload)
    except (ValueError, TypeError, ValidationError, RecursionError) as error:
        raise BizException(2001, "参数不符合所选能力的 Schema") from error
