from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChatMessage(BaseModel):
    """一条消息。

    E2：新增 `tool` 角色与两个工具字段。工具调用是多轮的：
    模型回 `tool_calls` → 客户端执行 → 以 `role="tool"` 回灌结果 →
    再发一次请求。平台**不在服务端跑工具**，所以每轮天然是一条独立账单。
    """

    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant", "tool"]
    content: str = Field(min_length=1, max_length=12000)
    # 仅 `role="tool"` 使用：对应上一轮 assistant 的 tool_call id。
    tool_call_id: str | None = Field(default=None, max_length=64)
    # 可选的名字（OpenAI 的 name 字段），工具结果回灌时常用。
    name: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def tool_fields_consistent(self):
        if self.role == "tool" and not self.tool_call_id:
            raise ValueError("tool 角色的消息必须带 tool_call_id")
        if self.role != "tool" and self.tool_call_id:
            raise ValueError("只有 tool 角色可以带 tool_call_id")
        return self


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
        # exclude_none：非 tool 消息不应把 tool_call_id/name 的 null 发给上游。
        return {"messages": [message.model_dump(exclude_none=True) for message in self.messages]}
