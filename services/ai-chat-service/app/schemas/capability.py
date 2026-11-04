"""Trusted catalog snapshots and bounded inputs for the two implemented adapters."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.schemas.chat import MAX_MESSAGE_CONTENT_LENGTH, ChatMessage


class CapabilityDefinition(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    id: int = Field(ge=1, strict=True)
    code: str = Field(min_length=1, max_length=64, strict=True)
    name: str = Field(default="", max_length=64)
    openai_alias: str | None = Field(default=None, max_length=64)
    status: Literal["online", "offline", "draft"]
    param_schema: dict[str, Any]
    price_per_call: int = Field(ge=0, le=1_000_000, strict=True)
    # C2 双轨计费：旧能力缺省 per_call，行为与金额完全不变。
    billing_mode: Literal["per_call", "per_token", "per_unit"] = "per_call"
    price_per_1k_input: int = Field(default=0, ge=0, le=1_000_000)
    price_per_1k_output: int = Field(default=0, ge=0, le=1_000_000)
    price_per_unit: int = Field(default=0, ge=0, le=1_000_000)
    unit: str = Field(default="", max_length=16)
    # D2：执行器与供应商别名（历史数据为空时按 code 兜底）
    executor: str = Field(default="", max_length=32)
    provider_alias: str = Field(default="", max_length=64)
    # D4：单次输出 token 上限
    max_output_tokens: int = Field(default=1024, ge=1, le=32768)
    catalog_source: Literal["internal", "market"] = "internal"


# D4 白名单：只有这些字段允许透传给上游；config 保持 extra="forbid"，其余一律 2001。
UPSTREAM_PARAM_FIELDS = (
    "top_p", "stop", "seed", "response_format",
    "presence_penalty", "frequency_penalty", "logprobs", "max_tokens",
    # E2：工具调用透传（平台不执行工具，只把 tool_calls 交给客户端）
    "tools", "tool_choice", "parallel_tool_calls",
)


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)
    temperature: float | None = Field(default=None, ge=0, le=2)
    # ---- D4 透传参数（全部可选，未给则不下发） ----
    top_p: float | None = Field(default=None, ge=0, le=1)
    stop: str | list[str] | None = Field(default=None, max_length=4)
    seed: int | None = Field(default=None, ge=-2147483648, le=2147483647)
    response_format: dict[str, Any] | None = None
    presence_penalty: float | None = Field(default=None, ge=-2, le=2)
    frequency_penalty: float | None = Field(default=None, ge=-2, le=2)
    logprobs: bool | None = None
    max_tokens: int | None = Field(default=None, ge=1, le=32768)
    # ---- E2 工具调用（结构原样透传，平台不做 schema 二次解释） ----
    tools: list[dict[str, Any]] | None = Field(default=None, max_length=64)
    tool_choice: str | dict[str, Any] | None = None
    parallel_tool_calls: bool | None = None

    @model_validator(mode="after")
    def ends_with_user(self):
        # E2：工具回灌后最后一条是 `tool`，同样合法。
        if self.messages[-1].role not in ("user", "tool"):
            raise ValueError("The final message must be from the user or a tool result")
        return self

    def upstream_params(self) -> dict[str, Any]:
        """只回传显式提供的白名单字段，避免把 None 写进上游请求体。"""

        return {
            name: getattr(self, name)
            for name in UPSTREAM_PARAM_FIELDS
            if getattr(self, name) is not None
        }


class ImageInput(BaseModel):
    """文生图输入（D3）：提示词 + 件数 + 尺寸。"""

    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=2000)
    n: int = Field(default=1, ge=1, le=4)
    size: str = Field(default="1024x1024", max_length=32)


class SummaryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # 与目录 Schema（long-summary 的 text.maxLength）和 ChatMessage.content 同源，
    # 否则长文本会先过 JSON Schema、再在这里撞 2001。
    text: str = Field(min_length=1, max_length=MAX_MESSAGE_CONTENT_LENGTH, strict=True)
    max_length: int = Field(default=200, ge=30, le=1000, strict=True)

    @model_validator(mode="after")
    def nonblank_text(self):
        if not self.text.strip():
            raise ValueError("Text cannot be blank")
        return self
