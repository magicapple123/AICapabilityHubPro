"""本服务统一的状态枚举与领域常量，避免代码中出现魔法字符串/数字。

开发指南 5.5 要求状态/枚举在代码中统一定义。指南统一了调用状态
`success` / `degraded` / `failed`；积分业务类型沿用 user-service 的取值，
已记录在 `docs/api-contract/billing-service.md` 第 1 节。

错误码号段（指南 5.2）：计费/积分只用 `30xx`；下游不可用与系统错误由基座
分别返回 `4002` / `4003`，不属于本服务的业务号段。
"""

from enum import Enum

# 调用流水里 capability_id 缺省值：ai-chat 当前按服务 + 固定单价上报，
# 未携带 capability_id。用 0 而不是 NULL，保证 t_usage_daily 的联合唯一索引
# 能正常参与 ON DUPLICATE KEY UPDATE 聚合（MySQL 唯一索引不约束多个 NULL）。
DEFAULT_CAPABILITY_ID = 0

# 用量统计查询的最大跨度（天），避免一次请求扫描过多分区。
MAX_STAT_RANGE_DAYS = 366

DATE_FORMAT = "%Y-%m-%d"


class CallStatus(str, Enum):
    """调用状态；与开发指南 5.5 的统一枚举一致。"""

    SUCCESS = "success"
    DEGRADED = "degraded"
    FAILED = "failed"


class PointBizType(str, Enum):
    """积分变动业务类型；与 user-service 的 `PointBizType` 保持同名同值。"""

    CALL = "call"


class StatGroupBy(str, Enum):
    """用量统计的分组维度。"""

    DAY = "day"
    CAPABILITY = "capability"
    SERVICE = "service"
