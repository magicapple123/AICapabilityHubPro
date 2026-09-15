"""本服务统一的状态枚举与领域约束，避免代码中出现魔法字符串。

开发指南 5.5 要求状态/枚举在代码中统一定义。指南只统一了能力状态
`draft` / `online` / `offline`，分类状态的取值由本服务自行约定，已记录在
`docs/api-contract/capability-service.md` 第 6 节待确认事项。
"""

from enum import Enum

# 分类 / 能力编码规则：小写字母或数字开头，只允许小写字母、数字和连字符。
CODE_PATTERN = r"^[a-z0-9][a-z0-9-]*$"


class CategoryStatus(str, Enum):
    """分类状态。"""

    ENABLED = "enabled"
    DISABLED = "disabled"


class CapabilityStatus(str, Enum):
    """能力状态；与开发指南 5.5 的统一枚举一致。"""

    DRAFT = "draft"
    ONLINE = "online"
    OFFLINE = "offline"
