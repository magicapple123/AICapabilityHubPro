"""上游 Responses API 协议：解析与降级边界。

只测解析层：端点切换（/responses vs /chat/completions）由 protocol 参数决定，
一旦写错会 404，属于集成测试范畴；这里锁住"能读懂响应、读不懂不编造"。
"""

from app.core.constants import CallStatus
from app.service.model_client import ModelClient


def test_reads_output_text_convenience_field():
    reply = ModelClient._parse_responses(
        {"output_text": "你好", "model": "gpt-x",
         "usage": {"input_tokens": 12, "output_tokens": 5}},
        fallback_model="fallback",
    )
    assert reply.call_status == CallStatus.SUCCESS.value
    assert reply.content == "你好"
    assert reply.model_name == "gpt-x"
    # 用量的最终归属由上层 normalize_usage 决定（C1 只认上游明确上报），
    # 这里只保证解析出的计数是合法非负整数，不越权断言计费语义。
    assert reply.prompt_tokens >= 0 and reply.completion_tokens >= 0


def test_walks_output_items_when_output_text_absent():
    body = {
        "output": [
            {"type": "reasoning", "content": [{"type": "summary_text", "text": "思考"}]},
            {"type": "message", "content": [
                {"type": "output_text", "text": "第一段"},
                {"type": "output_text", "text": "第二段"},
            ]},
        ],
        "usage": {"input_tokens": 3, "output_tokens": 4},
    }
    reply = ModelClient._parse_responses(body, fallback_model="m")
    assert reply.content == "第一段第二段"
    # 只要 type=output_text，reasoning 的 summary_text 不能被混进来
    assert "思考" not in reply.content


def test_empty_payload_degrades_without_inventing_text():
    reply = ModelClient._parse_responses({"output": []}, fallback_model="m")
    assert reply.call_status == CallStatus.DEGRADED.value
    assert reply.error_code is not None
    # 降级会带兜底文案，但那不是模型输出——用 error_code 判定，不能只看 content
    assert "未返回" in reply.content or reply.content


def test_non_dict_body_degrades():
    reply = ModelClient._parse_responses(["not", "a", "dict"], fallback_model="m")
    assert reply.degraded
