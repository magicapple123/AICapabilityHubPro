from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: 单条消息 `content` 的**字符**上限。
#:
#: 这是唯一的代码内事实来源：`openai_compat` 的入参预校验、`responses` 的
#: `instructions` 截断阈值、`SummaryInput.text` 的上限都从这里取值，避免同一个
#: 数字散落多处。要改它必须**同时**改下面三处，否则会在另一层被拒：
#:
#: 1. capability-service 目录 Schema 的 `maxLength`（`sql/02_seed.sql`、
#:    `sql/03_align_executor_schema.sql`、`sql/09_allow_tools_in_chat_schema.sql`，
#:    以及已有库的增量脚本 `sql/11_raise_message_max_length.sql`）；
#: 2. `t_chat_message.content` 的列宽（`ai-chat-service/sql/04_widen_message_content.sql`，
#:    MEDIUMTEXT 才装得下 48000 个中文：48000 × 3 字节 ≈ 144 KB > TEXT 的 65535 字节）；
#: 3. `input_validation.validate_capability_input` 的整包上限（65536 字符，见该模块）。
MAX_MESSAGE_CONTENT_LENGTH = 48000


class ChatMessage(BaseModel):
    """一条消息。

    E2：新增 `tool` 角色与两个工具字段。工具调用是多轮的：
    模型回 `tool_calls` → 客户端执行 → 以 `role="tool"` 回灌结果 →
    再发一次请求。平台**不在服务端跑工具**，所以每轮天然是一条独立账单。
    """

    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant", "tool"]
    # 纯工具调用的 assistant 消息 content 为空（OpenAI 允许 null），由校验器放行。
    # 上限见模块常量 MAX_MESSAGE_CONTENT_LENGTH（与目录 Schema / DB 列宽联动）。
    content: str = Field(default="", max_length=MAX_MESSAGE_CONTENT_LENGTH)
    # 仅 `role="tool"` 使用：对应上一轮 assistant 的 tool_call id。
    tool_call_id: str | None = Field(default=None, max_length=64)
    # 可选的名字（OpenAI 的 name 字段），工具结果回灌时常用。
    name: str | None = Field(default=None, max_length=64)
    # E2：assistant 回灌时必须带上一轮模型返回的 tool_calls，否则上游无法把
    # `role="tool"` 的结果和调用对上（实测会返回 400）。
    tool_calls: list[dict[str, Any]] | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def tool_fields_consistent(self):
        if self.role == "tool" and not self.tool_call_id:
            raise ValueError("tool 角色的消息必须带 tool_call_id")
        if self.role != "tool" and self.tool_call_id:
            raise ValueError("只有 tool 角色可以带 tool_call_id")
        if self.tool_calls is not None and self.role != "assistant":
            raise ValueError("只有 assistant 消息可以带 tool_calls")
        if not self.content.strip() and not (self.role == "assistant" and self.tool_calls):
            raise ValueError("消息内容不能为空")
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
