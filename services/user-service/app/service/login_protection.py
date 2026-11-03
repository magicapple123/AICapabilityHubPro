"""P14: bounded, process-local account/IP login failure windows.

Keys contain SHA-256 fingerprints only. A lock is checked before PBKDF2 work;
account locks stop distributed guessing, peer-IP locks stop account spraying.
Each worker has its own state; multi-instance deployments should move the
same policy to a shared store. No password or raw username is retained.
"""

from collections import deque
from dataclasses import dataclass, field
from hashlib import sha256
from threading import Lock
from time import monotonic
from typing import Callable

from app.core.exceptions import BizException


def fingerprint(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


@dataclass
class _Window:
    failures: deque[float] = field(default_factory=deque)
    locked_until: float = 0.0
    touched_at: float = 0.0


class LoginProtection:
    """Five account failures / five minutes lock for fifteen minutes.

    Peer IP has a 25-failure budget to tolerate users behind one gateway/NAT.
    Unknown accounts follow exactly the same windows as existing accounts.
    """

    def __init__(
        self, *, account_limit: int = 5, ip_limit: int = 25,
        window_seconds: float = 300, lock_seconds: float = 900,
        max_entries: int = 10000, clock: Callable[[], float] = monotonic,
    ) -> None:
        self.account_limit = account_limit
        self.ip_limit = ip_limit
        self.window_seconds = window_seconds
        self.lock_seconds = lock_seconds
        self.max_entries = max_entries
        self._clock = clock
        self._windows: dict[str, _Window] = {}
        self._mutex = Lock()

    @staticmethod
    def _keys(username: str, peer_ip: str) -> tuple[str, str]:
        return (
            "account:" + fingerprint(username.strip().casefold()),
            "ip:" + fingerprint(peer_ip or "unknown"),
        )

    def _get(self, key: str, now: float) -> _Window:
        if key not in self._windows:
            if len(self._windows) >= self.max_entries:
                self._windows = {
                    k: w for k, w in self._windows.items()
                    if w.locked_until > now
                    or now - w.touched_at < self.window_seconds
                }
            if len(self._windows) >= self.max_entries:
                raise BizException(4001, "登录请求过多，请稍后重试")
            self._windows[key] = _Window(touched_at=now)
        window = self._windows[key]
        while window.failures and window.failures[0] <= now - self.window_seconds:
            window.failures.popleft()
        window.touched_at = now
        return window

    def check(self, username: str, peer_ip: str) -> None:
        with self._mutex:
            now = self._clock()
            for key in self._keys(username, peer_ip):
                if self._get(key, now).locked_until > now:
                    raise BizException(4001, "登录失败次数过多，已暂时锁定，请15分钟后重试")

    def failed(self, username: str, peer_ip: str) -> None:
        with self._mutex:
            now = self._clock()
            for key, limit in zip(self._keys(username, peer_ip),
                                  (self.account_limit, self.ip_limit)):
                window = self._get(key, now)
                window.failures.append(now)
                if len(window.failures) >= limit:
                    window.locked_until = max(window.locked_until, now + self.lock_seconds)

    def succeeded(self, username: str, peer_ip: str) -> None:
        # A valid account cannot erase failures from other accounts on this IP.
        with self._mutex:
            self._windows.pop(self._keys(username, peer_ip)[0], None)


login_protection = LoginProtection()
