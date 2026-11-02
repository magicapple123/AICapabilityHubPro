"""D3 文生图：输入约束、按件计费、协议分发。真实上游调用只在联调脚本里做，不进 CI。"""

import asyncio
from types import SimpleNamespace

import pytest

from app.core.constants import CallStatus
from app.core.exceptions import BizException
from app.schemas.capability import CapabilityDefinition, ImageInput
from app.schemas.chat import ChatCompletionRequest
from app.service import capability_adapters as adapters
from app.service.image_client import ImageResult
from app.service.model_client import ModelReply


def definition(**changes):
    data = {
        "id": 9, "code": "text-to-image", "status": "online",
        "param_schema": {"type": "object"}, "price_per_call": 0,
        "executor": "image-generate", "provider_alias": "dashscope",
        "billing_mode": "per_unit", "price_per_unit": 3, "unit": "张",
    }
    return CapabilityDefinition(**{**data, **changes})


def request(payload):
    return ChatCompletionRequest(capability_id=9, input=payload)


def test_image_input_defaults_and_bounds():
    parsed = ImageInput(prompt="一只猫")
    assert parsed.n == 1 and parsed.size == "1024x1024"
    with pytest.raises(Exception):
        ImageInput(prompt="x", n=9)


def test_image_executor_is_registered():
    assert "image-generate" in adapters.EXECUTORS
    assert adapters.EXECUTORS["image-generate"].protocols == ("openai-image", "dashscope-image")


def test_prepare_uses_n_as_units():
    prepared = adapters.prepare_execution(
        definition(), request({"prompt": "一只猫", "n": 2, "size": "512x512"})
    )
    assert prepared.units == 2
    assert prepared.model_params == {"size": "512x512", "n": 2}


def test_image_rejects_session():
    with pytest.raises(BizException) as error:
        adapters.prepare_execution(
            definition(),
            ChatCompletionRequest(capability_id=9, input={"prompt": "x", "n": 1}, session_id=5),
        )
    assert error.value.code == 2001


def test_execute_requires_provider():
    prepared = adapters.prepare_execution(definition(), request({"prompt": "猫"}))
    with pytest.raises(BizException) as error:
        asyncio.run(adapters.execute_prepared(
            prepared, runtime=SimpleNamespace(use_mock=False), model_client=None,
            provider=None, definition=definition(),
        ))
    assert error.value.code == 2008


def test_dashscope_protocol_is_dispatched(monkeypatch):
    async def fake(**kwargs):
        assert kwargs["model"] == "wanx2.1-t2i-turbo"
        assert kwargs["n"] == 2
        return ImageResult(images=[{"url": "https://example.com/a.png"}], model_name="wanx")

    monkeypatch.setattr(adapters, "generate_dashscope", fake)
    prepared = adapters.prepare_execution(
        definition(), request({"prompt": "猫", "n": 2})
    )
    reply = asyncio.run(adapters.execute_prepared(
        prepared, runtime=SimpleNamespace(use_mock=False), model_client=None,
        provider=SimpleNamespace(
            base_url="https://dashscope.aliyuncs.com", api_key="k",
            model="wanx2.1-t2i-turbo", protocol="dashscope-image", timeout=60.0,
        ),
        definition=definition(),
    ))
    assert reply.call_status == CallStatus.SUCCESS.value
    assert reply.images[0]["url"].endswith("a.png")


def test_openai_protocol_is_dispatched(monkeypatch):
    async def fake(**kwargs):
        return ImageResult(images=[{"url": "https://example.com/b.png"}], model_name="m")

    monkeypatch.setattr(adapters, "generate_openai", fake)
    prepared = adapters.prepare_execution(definition(), request({"prompt": "猫"}))
    reply = asyncio.run(adapters.execute_prepared(
        prepared, runtime=SimpleNamespace(use_mock=False), model_client=None,
        provider=SimpleNamespace(
            base_url="https://api.example.com/v1", api_key="k",
            model="gpt-image-1", protocol="openai-image", timeout=60.0,
        ),
        definition=definition(),
    ))
    assert reply.images[0]["url"].endswith("b.png")


def test_failed_image_generation_is_degraded_without_images(monkeypatch):
    async def fake(**kwargs):
        return ImageResult(images=[], model_name="m", error_code=5005)

    monkeypatch.setattr(adapters, "generate_dashscope", fake)
    prepared = adapters.prepare_execution(definition(), request({"prompt": "猫"}))
    reply = asyncio.run(adapters.execute_prepared(
        prepared, runtime=SimpleNamespace(use_mock=False), model_client=None,
        provider=SimpleNamespace(
            base_url="https://dashscope.aliyuncs.com", api_key="k",
            model="wanx", protocol="dashscope-image", timeout=60.0,
        ),
        definition=definition(),
    ))
    assert reply.degraded and reply.images is None and reply.error_code == 5005


def test_completion_result_exposes_images():
    from app.service.completion_result import completion_result

    reply = ModelReply(
        content="", call_status=CallStatus.SUCCESS.value, model_name="wanx",
        images=[{"url": "https://example.com/a.png"}],
    )
    data = completion_result(
        definition=definition(), session=SimpleNamespace(id=1),
        message=SimpleNamespace(id=2), reply=reply, duration_ms=10,
        receipt={"cost": 3, "record_id": 1},
    )
    assert data["choices"][0]["images"][0]["url"].endswith("a.png")
