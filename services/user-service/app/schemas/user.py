"""用户注册、登录与资料的请求/响应模型。

安全约定：`password` 只出现在入参，任何出参都不包含 `password` / `password_hash`。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal

from app.core.constants import (
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    USERNAME_PATTERN,
    UserStatus,
)
from app.schemas.common import BaseOut, validate_partial_update

NICKNAME_MAX_LENGTH = 32


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    """注册请求。`nickname` 缺省时使用 `username`。"""

    username: str = Field(min_length=3, max_length=32, pattern=USERNAME_PATTERN)
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    nickname: str | None = Field(default=None, max_length=NICKNAME_MAX_LENGTH)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    """登录请求。"""

    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


class ProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    """更新当前用户资料；只允许改昵称，用户名与状态不可由用户自行修改。"""

    nickname: str = Field(min_length=1, max_length=NICKNAME_MAX_LENGTH)

    @model_validator(mode="after")
    def check_partial_update(self) -> "ProfileUpdateRequest":
        validate_partial_update(self, non_nullable=("nickname",))
        return self


class RegisterOut(BaseOut):
    role: Literal["user", "admin"] = "user"
    """注册结果：注册即创建积分账户并赠送初始积分。"""

    user_id: int
    username: str
    nickname: str
    balance: int
    initial_points: int


class LoginOut(BaseOut):
    role: Literal["user", "admin"] = "user"
    """登录结果。`token` 为与网关同密钥签发的 JWT。"""

    token: str
    token_type: str = "Bearer"
    expire_at: datetime
    user_id: int
    username: str


class ProfileOut(BaseOut):
    role: Literal["user", "admin"] = "user"
    """当前用户资料；不包含密码哈希等敏感字段。"""

    user_id: int
    username: str
    nickname: str
    status: str
    create_time: datetime
    update_time: datetime

    @classmethod
    def from_user(cls, user: object) -> "ProfileOut":
        """从 User 实体组装出参，字段显式列举以避免误带敏感列。"""

        return cls(
            user_id=user.id,
            username=user.username,
            nickname=user.nickname,
            status=user.status,
            role=user.role,
            create_time=user.create_time,
            update_time=user.update_time,
        )


def is_normal_status(status: str) -> bool:
    """用户是否处于可登录、可扣分的正常状态。"""

    return status == UserStatus.NORMAL.value
