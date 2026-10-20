"""API Key 的请求与响应模型。

最小暴露原则：
- 列表与禁用接口只返回 `secret_mask`（如 `sk_****a1b2`），永不回传完整密钥；
- 完整 `secret_key` 只在创建响应 `ApiKeyCreatedOut` 中出现一次。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from datetime import timedelta, timezone

from app.core.constants import ApiKeyStatus
from app.schemas.common import BaseOut

API_KEY_NAME_MAX_LENGTH = 32


class ApiKeyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    """创建 API Key；`expire_time` 为空表示永不过期。"""

    name: str = Field(default="", max_length=API_KEY_NAME_MAX_LENGTH)
    expire_time: datetime | None = None

    @field_validator("expire_time")
    @classmethod
    def local_expiry(cls, value):
        if value is not None and value.tzinfo is not None:
            return value.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None)
        return value


class ApiKeyOut(BaseOut):
    """API Key 列表项：只含掩码，不含 secret_hash。"""

    id: int
    name: str
    access_key: str
    secret_mask: str
    status: str
    expire_time: datetime | None
    create_time: datetime

    @classmethod
    def from_api_key(cls, api_key: object) -> "ApiKeyOut":
        return cls(
            id=api_key.id,
            name=api_key.name,
            access_key=api_key.access_key,
            secret_mask=api_key.secret_mask,
            status=api_key.status,
            expire_time=api_key.expire_time,
            create_time=api_key.create_time,
        )


class ApiKeyCreatedOut(ApiKeyOut):
    """创建结果：仅在本次响应中返回完整 `secret_key`，之后无法再次获取。"""

    secret_key: str


class ApiKeyStatusOut(BaseOut):
    """禁用结果。"""

    id: int
    status: str = ApiKeyStatus.DISABLED.value
    update_time: datetime


class ApiKeyExchangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    access_key: str = Field(min_length=1, max_length=64, repr=False)
    secret_key: SecretStr = Field(min_length=1, max_length=128)
