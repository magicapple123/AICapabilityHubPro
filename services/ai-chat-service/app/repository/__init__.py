"""数据访问层：只访问本服务的 ai_chat_db，禁止跨库查询。"""

from app.repository.chat_repository import ChatRepository, chat_repository

__all__ = ["ChatRepository", "chat_repository"]
