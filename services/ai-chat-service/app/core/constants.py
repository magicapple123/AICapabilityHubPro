"""ai-chat-service 的枚举与领域常量，避免魔法字符串散落在代码里。

开发指南 5.5 统一了调用状态 `success` / `degraded` / `failed` 与消息角色；
错误码号段（指南 5.2）中本服务只使用模型号段 `5xxx` 表达下游模型异常。
"""

from enum import Enum

# 会话标题取自首条用户消息，超长直接截断，避免异常长的标题撑破列表布局。
SESSION_TITLE_MAX_LENGTH = 30

DEFAULT_SESSION_TITLE = "新对话"

# 真实模型不可用时的兜底话术：返回它并标记 degraded，闭环不中断（指南 3.4）。
DEGRADED_REPLY = "模型服务暂时不可用，已返回兜底回复，请稍后重试。"

# Mock 模式的固定回复，便于本地联调时一眼确认链路。
MOCK_REPLY = "你好！这是 ai-chat-service 的 Mock 回复。"

# 降级调用不向用户计费，但仍写入调用流水与用量统计，便于运营观察失败率。
DEGRADED_POINTS_COST = 0


class CallStatus(str, Enum):
    """调用状态；与指南 5.5 / billing-service 的统一枚举一致。"""

    SUCCESS = "success"
    DEGRADED = "degraded"
    FAILED = "failed"


class MessageRole(str, Enum):
    """会话消息角色。"""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ModelErrorCode(int, Enum):
    """下游模型错误码（5xxx 号段）。"""

    TIMEOUT = 5001
    BAD_RESPONSE = 5002
