"""A3 主动失效的发送侧：管理接口改价后必须通知 ai-chat 清掉目录缓存。

分工：
- 本文件守护"钩子有没有被调用、参数对不对、下游挂了会不会拖垮写操作"；
- 接收侧（缓存真的被清、立刻读到新价）由 ai-chat 的
  `tests/test_invalidate_hook.py` 覆盖。

单测环境默认 `enable_internal_chain=False`（见 conftest），否则每次写操作都要等一次
服务发现超时；本文件显式打开该开关并把 `call_internal` 替换为记录器，
既能断言发出的请求，又不会真的发起跨服务调用。
"""

import pytest
from importlib import import_module

from app.core.config import settings
from app.core.exceptions import BizException
from app.service import capability_service
from tests.conftest import USER_HEADERS  # noqa: F401  (保持与其他用例一致的显式依赖)

INVALIDATE_PATH = "/internal/capability-cache/invalidate"

# `app.service` 把单例 `capability_service` 导出成同名对象，顶层名字指向的是**实例**；
# 这里要替换的是模块级函数 `call_internal`，所以必须拿到真正的模块对象。
_CAPABILITY_SERVICE_MODULE = import_module("app.service.capability_service")


def _capture_internal_calls(monkeypatch: pytest.MonkeyPatch, *, fail: bool = False) -> list[dict]:
    """打开内部链路并把 `call_internal` 换成记录器。

    Args:
        monkeypatch: pytest 的 monkeypatch。
        fail: 为 ``True`` 时模拟 ai-chat 不可用（抛 4002）。

    Returns:
        按调用顺序累积的参数列表，供断言使用。
    """

    calls: list[dict] = []

    async def fake_call_internal(
        service_name, method, path, *, json=None, params=None, headers=None, timeout=None
    ):
        calls.append(
            {
                "service_name": service_name,
                "method": method,
                "path": path,
                "json": json,
                "timeout": timeout,
            }
        )
        if fail:
            raise BizException(4002, "下游服务暂不可用")
        return {"removed": 1}

    monkeypatch.setattr(settings, "enable_internal_chain", True)
    monkeypatch.setattr(_CAPABILITY_SERVICE_MODULE, "call_internal", fake_call_internal)
    return calls


def _assert_invalidation_emitted(calls: list[dict], capability_id: int) -> None:
    """断言"恰好发出一次失效通知，且参数是刚被改动的能力"。

    正向用例与负向守护共用这一个断言函数，从而证明它真的能区分好坏实现。
    """

    assert [call["path"] for call in calls] == [INVALIDATE_PATH], calls
    assert calls[0]["method"] == "POST"
    assert calls[0]["json"] == {"capability_id": capability_id}
    assert calls[0]["service_name"] == settings.ai_chat_service_name
    # 写路径不能被下游拖住：超时必须显式且很短。
    assert calls[0]["timeout"] is not None and calls[0]["timeout"] <= 1.0


def test_management_price_change_notifies_ai_chat_catalog_cache(qa, monkeypatch):
    """PUT /api/capability/{id} 改价后，必须级联一次缓存失效通知。"""

    calls = _capture_internal_calls(monkeypatch)
    category = qa.category()
    capability = qa.capability(category["id"])

    calls.clear()  # 登记能力本身也会通知一次，这里只关心改价这一次
    body = qa.update_capability(capability["id"], {"price_per_call": 9})

    assert body["code"] == 0, body
    assert body["data"]["price_per_call"] == 9
    _assert_invalidation_emitted(calls, capability["id"])


def test_status_change_notifies_ai_chat_catalog_cache(qa, monkeypatch):
    """上下架同样改变目录可见性，也必须级联失效通知。"""

    calls = _capture_internal_calls(monkeypatch)
    category = qa.category()
    capability = qa.capability(category["id"])

    calls.clear()
    body = qa.set_status(capability["id"], "online")

    assert body["code"] == 0, body
    _assert_invalidation_emitted(calls, capability["id"])


def test_the_assertion_fails_when_the_hook_is_not_wired(qa, monkeypatch):
    """负向守护：钩子没接上（这里是直接短路掉）时，同一断言必须失败。"""

    calls = _capture_internal_calls(monkeypatch)

    async def skip_notification(capability_id: int | None = None) -> None:
        return None

    monkeypatch.setattr(capability_service, "invalidate_catalog", skip_notification)
    category = qa.category()
    capability = qa.capability(category["id"])
    calls.clear()
    body = qa.update_capability(capability["id"], {"price_per_call": 9})

    assert body["code"] == 0, body  # 写操作本身仍是成功的
    assert calls == []
    with pytest.raises(AssertionError):
        _assert_invalidation_emitted(calls, capability["id"])


def test_write_still_succeeds_when_ai_chat_is_unavailable(qa, monkeypatch):
    """尽力而为：失效通知失败只影响新鲜度（TTL 兜底），不能让改价回滚。"""

    calls = _capture_internal_calls(monkeypatch, fail=True)
    category = qa.category()
    capability = qa.capability(category["id"])

    calls.clear()
    body = qa.update_capability(capability["id"], {"price_per_call": 11})

    assert body["code"] == 0, body
    assert body["data"]["price_per_call"] == 11
    assert [call["path"] for call in calls] == [INVALIDATE_PATH]
