"""调用明细与用量统计的响应模型。

数据来源（接口契约第 3、4 节已写明，避免统计口径歧义）：

- `summary` / `by_service` / `top_users`：取自 `t_call_record` 明细，
  可以按调用状态与承载服务维度拆分；
- `by_day`：取自 `t_usage_daily` 聚合表，展示按天累加结果。

金额一律整型（积分数），不使用浮点（指南 5.5）。
"""

from datetime import date, datetime

from pydantic import BaseModel

from app.schemas.common import BaseOut


class CallRecordOut(BaseOut):
    """调用明细项。当前用户只能看到自己的记录。"""

    id: int
    request_id: str
    user_id: int
    capability_id: int
    service_name: str
    unit_price: int | None = None
    cost: int
    call_status: str
    duration_ms: int
    model_name: str
    create_time: datetime


class UsageDailyOut(BaseOut):
    """按天用量项。`stat_date` 序列化为 `YYYY-MM-DD`。"""

    stat_date: date
    call_count: int
    total_cost: int


class ServiceUsageOut(BaseModel):
    """按承载服务维度聚合的用量。"""

    service_name: str
    call_count: int
    total_cost: int


class UserUsageOut(BaseModel):
    """按用户维度聚合的用量，仅运营统计返回。"""

    user_id: int
    call_count: int
    total_cost: int


class UsageSummaryOut(BaseModel):
    """汇总指标；`*_count` 为各调用状态的次数。"""

    call_count: int
    total_cost: int
    success_count: int
    degraded_count: int
    failed_count: int


class OverviewSummaryOut(UsageSummaryOut):
    """运营汇总在个人汇总基础上增加去重用户数。"""

    user_count: int


class PersonalUsageOut(BaseOut):
    """`GET /api/billing/usage` 出参。"""

    start_date: date
    end_date: date
    summary: UsageSummaryOut
    by_day: list[UsageDailyOut]
    by_service: list[ServiceUsageOut]


class OverviewUsageOut(BaseOut):
    """`GET /api/billing/stat/overview` 出参。"""

    start_date: date
    end_date: date
    summary: OverviewSummaryOut
    by_day: list[UsageDailyOut]
    by_service: list[ServiceUsageOut]
    top_users: list[UserUsageOut]
