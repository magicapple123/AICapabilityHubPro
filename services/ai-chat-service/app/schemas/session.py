from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ChatSessionResponse(BaseModel):
    """会话列表项；`last_message_time` 可能为空（历史数据）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    last_message_time: datetime | None = None
    create_time: datetime
    update_time: datetime


class ChatMessageResponse(BaseModel):
    """会话消息项；`call_status` / `token_count` 只对助手消息有意义。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    role: str
    content: str
    call_status: str
    token_count: int
    create_time: datetime
