import asyncio
import importlib

import pytest

from app.core.exceptions import BizException

module = importlib.import_module("app.service.capability_service")


@pytest.mark.parametrize("status", ["draft", "disabled"])
def test_binding_rejects_unavailable_provider_before_write(monkeypatch, status):
    async def lookup(*args, **kwargs):
        return {"protocol": "openai-chat", "status": status}

    monkeypatch.setattr(module, "call_internal", lookup)
    with pytest.raises(BizException) as error:
        asyncio.run(module.CapabilityService().ensure_provider_binding("chat", "vendor-alias"))
    assert error.value.code == 2001
    assert status in error.value.message and "vendor-alias" in error.value.message
    assert "测试并启用" in error.value.message


@pytest.mark.parametrize("status,protocol,code", [("enabled", "openai-chat", None), ("enabled", "openai-image", 2001), (None, "openai-chat", 4002)])
def test_binding_checks_status_shape_and_retains_protocol_validation(monkeypatch, status, protocol, code):
    async def lookup(*args, **kwargs):
        return {"protocol": protocol, "status": status}

    monkeypatch.setattr(module, "call_internal", lookup)
    if code is None:
        asyncio.run(module.CapabilityService().ensure_provider_binding("chat", "vendor-alias"))
    else:
        with pytest.raises(BizException) as error:
            asyncio.run(module.CapabilityService().ensure_provider_binding("chat", "vendor-alias"))
        assert error.value.code == code
