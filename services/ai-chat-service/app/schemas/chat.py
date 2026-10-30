from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=12000)


class ChatCompletionRequest(BaseModel):
    """对话请求体。

    `session_id` 为空时新建会话；传入时必须是当前用户自己的会话，
    否则返回 `4004`。`stream` 本期不支持，只做参数兼容（指南非目标：SSE）。
    """

    model_config = ConfigDict(extra="forbid")
    capability_id: int = Field(default=1, ge=1, strict=True)
    input: dict[str, Any] | None = None
    session_id: int | None = Field(default=None, ge=1, strict=True)
    model: str | None = Field(default=None, max_length=128)
    messages: list[ChatMessage] = Field(default_factory=list, max_length=40)
    temperature: float = Field(default=0.7, ge=0, le=2)
    stream: bool = False

    @model_validator(mode="after")
    def validate_input_shape(self):
        if self.stream:
            raise ValueError("Streaming is not implemented")
        if self.input is None and not self.messages:
            raise ValueError("Provide input or nonempty messages")
        if self.input is not None and self.messages:
            raise ValueError("input and messages cannot be combined")
        return self

    def capability_input(self) -> dict[str, Any]:
        if self.input is not None:
            return self.input
        return {"messages": [message.model_dump() for message in self.messages]}
