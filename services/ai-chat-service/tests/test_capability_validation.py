import pytest
from pydantic import ValidationError
from app.core.exceptions import BizException
from app.schemas.capability import CapabilityDefinition
from app.schemas.chat import ChatCompletionRequest
from app.service.capability_adapters import prepare_execution, model_messages, local_summary
from app.service.input_validation import validate_capability_input


def definition(code="chat-completions", **kwargs):
    return CapabilityDefinition(
        id=1, code=code, status="online", price_per_call=5,
        param_schema={"type": "object"}, **kwargs,
    )


@pytest.mark.parametrize("schema,payload", [
    ({"type": "object", "required": ["text"]}, {}),
    ({"type": "object", "properties": {"text": {"type": "string", "maxLength": 3}}}, {"text": "long"}),
    ({"type": "object", "additionalProperties": False}, {"url": "http://untrusted"}),
    ({"type": "object", "properties": {"count": {"type": "integer"}}}, {"count": "5"}),
])
def test_schema_input_errors_are_rejected(schema, payload):
    with pytest.raises(BizException) as error:
        validate_capability_input(schema, payload)
    assert error.value.code == 2001


@pytest.mark.parametrize("schema", [
    {"$ref": "http://127.0.0.1/private"},
    {"type": "object", "properties": {"text": {"$ref": "file:///private"}}},
    {"type": "object", "properties": {"text": {"$ref": "#/$defs/text"}}},
    {"type": "object", "required": "not-an-array"},
    {"type": "string"},
])
def test_bad_or_referenced_schema_fails_closed(schema):
    with pytest.raises(BizException) as error:
        validate_capability_input(schema, {})
    assert error.value.code == 4002


@pytest.mark.parametrize("payload", [
    {"messages": []}, {"messages": [{"role": "system", "content": "only system"}]},
    {"messages": [{"role": "user", "content": ""}]},
    {"messages": [{"role": "user", "content": "hello"}], "url": "https://untrusted"},
])
def test_adapter_strong_validation_still_applies_to_loose_catalog(payload):
    request = ChatCompletionRequest(input=payload)
    with pytest.raises(BizException) as error:
        prepare_execution(definition(), request)
    assert error.value.code == 2001


@pytest.mark.parametrize("payload", [{"text": " "}, {"text": "abc", "max_length": True},
                                     {"text": "abc", "max_length": 0}, {"messages": []}])
def test_summary_has_its_own_input_contract(payload):
    with pytest.raises(BizException) as error:
        prepare_execution(definition("long-summary"), ChatCompletionRequest(input=payload))
    assert error.value.code == 2001


def test_summary_mapping_is_distinct_and_user_input_is_not_system_instruction():
    request = ChatCompletionRequest(capability_id=2, input={"text": "材料正文", "max_length": 50})
    prepared = prepare_execution(definition("long-summary"), request)
    messages = model_messages(prepared)
    assert messages[0]["role"] == "system" and "50" in messages[0]["content"]
    assert messages[1] == {"role": "user", "content": "材料正文"}
    assert local_summary("first material", 100) != local_summary("second material", 100)
    assert len(local_summary("x" * 200, 50)) <= 50


@pytest.mark.parametrize("payload", [{"messages": []}, {"input": {}, "messages": [{"role": "user", "content": "a"}]},
    {"input": {}, "stream": True}, {"input": {}, "capability_id": True},
    {"input": {}, "price_per_call": 0}, {"input": {}, "target_url": "https://arbitrary"}])
def test_transport_rejects_ambiguous_or_spoofed_fields(payload):
    with pytest.raises(ValidationError):
        ChatCompletionRequest.model_validate(payload)


def test_unsupported_executor_is_never_treated_as_chat():
    with pytest.raises(BizException) as error:
        prepare_execution(definition("vision-parse"), ChatCompletionRequest(input={"image_url": "x"}))
    assert error.value.code == 2008
