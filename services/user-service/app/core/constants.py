"""本服务统一的状态枚举与领域常量，避免代码中出现魔法字符串/数字。

开发指南 5.5 要求状态/枚举在代码中统一定义。指南只统一了积分变动方向
`in` / `out`；用户状态、API Key 状态和积分业务类型的取值由本服务自行约定，
已记录在 `docs/api-contract/user-service.md` 第 1 节。

错误码号段说明（指南 5.2）：用户/认证用 `10xx`；积分余额不足按指南 3.4
“积分不足 → 能力服务执行前拦截 → 3001”使用计费号段 `3001`，
因此本服务同时会出现 `3001` / `3002` 两个计费语义的错误码。
"""

from enum import Enum

# 用户名：3~32 位字母、数字、下划线或连字符，便于登录与日志脱敏。
USERNAME_PATTERN = r"^[a-zA-Z0-9_-]{3,32}$"

# API Key 展示前缀：access_key 用于标识，secret_key 只在创建时返回一次。
ACCESS_KEY_PREFIX = "ak_"
SECRET_KEY_PREFIX = "sk_"

# 注册赠送的默认积分；可通过 .env 的 INITIAL_POINTS 覆盖，不在代码里硬编码为唯一来源。
DEFAULT_INITIAL_POINTS = 100

# 积分日记账的 requestId 命名空间：注册赠送使用 `register-{user_id}`，
# 能力调用扣分直接复用全链路 requestId，两者不会互相占用。
REGISTER_BIZ_PREFIX = "register-"

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
NICKNAME_MAX_LENGTH = 32
API_KEY_NAME_MAX_LENGTH = 32


class UserStatus(str, Enum):
    """用户状态。禁用用户不允许登录，也不允许继续扣分。"""

    NORMAL = "normal"
    DISABLED = "disabled"


class ApiKeyStatus(str, Enum):
    """API Key 状态。"""

    ENABLED = "enabled"
    DISABLED = "disabled"


class PointDirection(str, Enum):
    """积分变动方向；与开发指南 5.5 的统一枚举一致。"""

    IN = "in"
    OUT = "out"


class PointBizType(str, Enum):
    """积分变动业务类型，用于流水归类。"""

    REGISTER = "register"
    CALL = "call"
