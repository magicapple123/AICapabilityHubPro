from types import SimpleNamespace

import pytest

from app.core.exceptions import BizException
from app.service.provider_service import ProviderService, provider_repository
from app.api.v1.openai_compat import _openai_error


@pytest.mark.parametrize("provider", [None, SimpleNamespace(status="draft"), SimpleNamespace(status="disabled")])
def test_unavailable_provider_has_dedicated_2009(monkeypatch, provider):
    monkeypatch.setattr(provider_repository, "find_by_alias", lambda *args: provider)
    with pytest.raises(BizException) as error:
        ProviderService().resolve_runtime(None, "provider-x")
    assert error.value.code == 2009
    assert "provider-x" in error.value.message


def test_openai_provider_error_is_retryable_service_unavailable():
    response = _openai_error(BizException(2009, "供应商 provider-x 不存在或未启用"))
    assert response.status_code == 503
    assert b'"type":"api_error"' in response.body
    assert b'"code":"platform_2009"' in response.body
    legacy = _openai_error(BizException(2008, "该能力暂未提供可用执行器"))
    assert legacy.status_code == 400
    assert b'"code":"platform_2008"' in legacy.body
