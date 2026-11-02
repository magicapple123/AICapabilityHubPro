"""供应商请求/响应模型（D1）。

关键约束：
- `api_key` **只在创建/轮换时出现**，响应永不含明文或密文，只有 `api_key_mask`；
- `status` 创建时只允许 `draft`（必须先测通才能启用），启用走独立接口。
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PROTOCOLS = ("openai-chat", "openai-image", "openai-embedding", "dashscope-image", "custom-http")
ALIAS_PATTERN = r"^[a-z0-9][a-z0-9-]*$"


class ProviderCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    alias: str = Field(min_length=1, max_length=64, pattern=ALIAS_PATTERN)
    protocol: Literal["openai-chat", "openai-image", "openai-embedding", "dashscope-image", "custom-http"]
    base_url: str = Field(min_length=1, max_length=512)
    api_key: str = Field(min_length=1, max_length=512)
    default_model: str = Field(default="", max_length=128)
    timeout_ms: int = Field(default=30000, ge=1000, le=120000)
    extra_json: dict[str, Any] | None = None

    @field_validator("base_url")
    @classmethod
    def no_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")


class ProviderUpdateRequest(BaseModel):
    """`api_key` 为空表示"不轮换"，避免编辑其他字段时被迫重填密钥。"""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=64)
    base_url: str | None = Field(default=None, min_length=1, max_length=512)
    api_key: str | None = Field(default=None, max_length=512)
    default_model: str | None = Field(default=None, max_length=128)
    timeout_ms: int | None = Field(default=None, ge=1000, le=120000)
    extra_json: dict[str, Any] | None = None

    @field_validator("base_url")
    @classmethod
    def no_trailing_slash(cls, value: str | None) -> str | None:
        return value.rstrip("/") if value else value


class ProviderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    alias: str
    protocol: str
    base_url: str
    api_key_mask: str
    default_model: str
    timeout_ms: int
    status: str
    last_test_ok_at: datetime | None = None
    create_time: datetime
    update_time: datetime


class ProviderTestOut(BaseModel):
    """连通性测试结果；失败时 `reason` 是稳定的原因码，便于前端提示。"""

    provider_id: int
    ok: bool
    reason: str = ""
    http_status: int | None = None
    elapsed_ms: int = 0
