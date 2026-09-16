"""SQLAlchemy 模型：只映射 ai_chat_db 中的表。"""

from app.models.chat import ChatMessage, ChatSession

__all__ = ["ChatMessage", "ChatSession"]
