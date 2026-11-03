"""整条链路的超时预算（P16）。

为什么需要：一次 chat 调用串 4 跳（目录 → 用户校验 → 模型 → 账单），每跳各自超时。
上游卡住时最坏耗时 = 模型超时 × 重试次数 + 退避，远超用户可接受的等待，而调用方
（前端 / 外部 Agent）只能干等。这里在**入口**算一次 deadline，向下只传"还剩多少"：

- 模型调用的单次超时取 `min(供应商配置, 剩余预算)`（`Deadline.clamp`）；
- 预算耗尽时不再发起新的上游请求（`Deadline.exhausted`），直接按超时降级；
- 重试同样受预算约束，避免 `30s × 2` 的叠加。

覆盖范围（口径与代码一致）：ai-chat 自己的出站模型 / 图片 / 流式调用。内部 RPC
（目录、余额、账单）的超时仍由 `service_call` 按用途写死（3–10s），本轮不改，因此
它们挤占预算时表现为"模型超时被压小"，而不是"内部调用被中断"。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

# 允许的最小单次尝试超时；再小就只会在握手阶段必然失败，不如失败关闭。
MIN_ATTEMPT_TIMEOUT = 0.2


@dataclass(frozen=True)
class Deadline:
    """一次调用的时间预算；`expires_at` 用 `time.monotonic()`，不受系统时间调整影响。"""

    budget: float
    expires_at: float

    @classmethod
    def start(cls, budget: float | None = None) -> Deadline:
        """在入口创建预算；`budget` 为空时取 `settings.request_budget_seconds`。"""

        if budget is None:
            from app.core.config import settings

            budget = settings.request_budget_seconds
        total = max(float(budget), MIN_ATTEMPT_TIMEOUT)
        return cls(budget=total, expires_at=time.monotonic() + total)

    def remaining(self) -> float:
        """剩余秒数，已耗尽时返回 0（不返回负数，便于直接传 timeout）。"""

        return max(0.0, self.expires_at - time.monotonic())

    def exhausted(self) -> bool:
        return self.remaining() <= 0.0

    def clamp(self, timeout: float | None) -> float:
        """把配置超时压到剩余预算之内，并给一个不导致立即失败的下限。"""

        left = self.remaining()
        if timeout is None or timeout <= 0:
            return max(MIN_ATTEMPT_TIMEOUT, left)
        return max(MIN_ATTEMPT_TIMEOUT, min(float(timeout), left))
