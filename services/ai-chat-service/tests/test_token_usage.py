"""C1 token 用量归一化：只采信上游 usage，缺失时明确标记而不是拿字符数冒充。"""

from app.service.model_client import ModelClient, ModelReply, normalize_usage


def test_chat_completions_usage_is_read_as_is():
    body = {"usage": {"prompt_tokens": 12, "completion_tokens": 34, "total_tokens": 46}}
    assert normalize_usage(body) == (12, 34, "upstream")


def test_responses_usage_is_normalized_from_input_output():
    body = {"usage": {"input_tokens": 7, "output_tokens": 9, "total_tokens": 16}}
    assert normalize_usage(body) == (7, 9, "upstream")


def test_chat_completions_fields_win_over_responses_fields():
    body = {"usage": {"prompt_tokens": 3, "completion_tokens": 4,
                      "input_tokens": 100, "output_tokens": 200}}
    assert normalize_usage(body) == (3, 4, "upstream")


def test_missing_usage_is_marked_not_estimated():
    assert normalize_usage({"choices": []}) == (0, 0, "missing")
    assert normalize_usage({"usage": None}) == (0, 0, "missing")
    assert normalize_usage({"usage": {}}) == (0, 0, "missing")
    assert normalize_usage("not-a-dict") == (0, 0, "missing")


def test_zero_total_is_treated_as_missing():
    """真实调用不可能 0 token；0/0 只能是"上游没给"，不能记成"用了 0"。"""

    assert normalize_usage({"usage": {"prompt_tokens": 0, "completion_tokens": 0}}) == (
        0, 0, "missing",
    )


def test_float_and_bool_are_rejected_as_missing():
    assert normalize_usage({"usage": {"prompt_tokens": 1.5, "completion_tokens": 2}}) == (
        0, 0, "missing",
    )
    assert normalize_usage({"usage": {"prompt_tokens": True, "completion_tokens": 2}}) == (
        0, 0, "missing",
    )


def test_negative_value_is_missing():
    assert normalize_usage({"usage": {"prompt_tokens": -1, "completion_tokens": 2}}) == (
        0, 0, "missing",
    )


def test_reply_total_is_the_sum_of_the_two_components():
    reply = ModelReply(content="hi", call_status="success", model_name="m",
                       prompt_tokens=11, completion_tokens=22, usage_source="upstream")
    assert reply.total_tokens == 33
    assert reply.degraded is False


def test_parse_projects_upstream_usage_into_both_components():
    reply = ModelClient._parse(
        {"model": "upstream-model",
         "choices": [{"message": {"content": "答案"}}],
         "usage": {"prompt_tokens": 5, "completion_tokens": 6, "total_tokens": 11}},
        fallback_model="fallback",
    )
    assert (reply.prompt_tokens, reply.completion_tokens) == (5, 6)
    assert reply.usage_source == "upstream"
    assert reply.model_name == "upstream-model"


def test_parse_without_usage_keeps_content_but_marks_missing():
    reply = ModelClient._parse(
        {"choices": [{"message": {"content": "答案"}}]}, fallback_model="fallback",
    )
    assert reply.content == "答案"
    assert reply.usage_source == "missing"
    assert reply.total_tokens == 0


def test_degraded_reply_has_no_token_claim():
    reply = ModelClient._degraded("m", 5001)
    assert reply.degraded is True
    assert reply.usage_source == "missing"
    assert reply.total_tokens == 0
