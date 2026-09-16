from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=12000)


class ChatCompletionRequest(BaseModel):
    """对话请求体。

    `session_id` 为空时新建会话；传入时必须是当前用户自己的会话，
    否则返回 `4004`。`stream` 本期不支持，只做参数兼容（指南非目标：SSE）。
    """

    session_id: int | None = Field(default=None, ge=1)
    model: str = Field(default="mock-model", min_length=1, max_length=128)
    messages: list[ChatMessage] = Field(min_length=1)
    temperature: float = Field(default=0.7, ge=0, le=2)
    stream: bool = False
