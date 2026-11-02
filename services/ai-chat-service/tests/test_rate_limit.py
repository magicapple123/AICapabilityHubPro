"""A4 按用户令牌桶：突发上限、按时间回补、可关闭、互不影响。"""

import time

import pytest

from app.core import rate_limit as module
from app.core.config import settings
from app.core.exceptions import BizException
from app.core.rate_limit import UserRateLimiter


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)


def test_burst_then_reject():
    limiter = UserRateLimiter(qps=0.1, burst=3)
    for _ in range(3):
        limiter.acquire("u1")
    with pytest.raises(BizException) as error:
        limiter.acquire("u1")
    assert error.value.code == 2009


def test_tokens_refill_over_time(monkeypatch):
    limiter = UserRateLimiter(qps=1.0, burst=1)
    real = time.monotonic
    limiter.acquire("u1")
    monkeypatch.setattr(module.time, "monotonic", lambda: real() + 1.1)
    limiter.acquire("u1")  # 回补 1 个令牌后应放行


def test_users_are_isolated():
    limiter = UserRateLimiter(qps=0.1, burst=1)
    limiter.acquire("u1")
    limiter.acquire("u2")  # 不影响 u2


def test_disabled_never_rejects(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    limiter = UserRateLimiter(qps=0.1, burst=1)
    for _ in range(100):
        limiter.acquire("u1")


def test_reset_clears_buckets():
    limiter = UserRateLimiter(qps=0.1, burst=1)
    limiter.acquire("u1")
    limiter.reset()
    limiter.acquire("u1")
