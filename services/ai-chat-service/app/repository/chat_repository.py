"""ai_chat_db 的数据访问层：只做查询与持久化，不提交事务。

事务边界统一由 service 层控制：本层 `flush` 让主键与唯一约束立即生效，
失败时由 service 回滚，保证“消息与计费”不存在半成功状态。
"""

from datetime import datetime

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.constants import DEFAULT_SESSION_TITLE, CallStatus
from app.models.chat import ChatMessage, ChatSession


class ChatRepository:
    """只负责 ai_chat_db 的查询和持久化，不跨库访问其它服务。"""

    # ------------------------------------------------------------ 查询

    def list_sessions(
        self, db: Session, user_id: str, *, page: int = 1, page_size: int = 20
    ) -> tuple[list[ChatSession], int]:
        predicate = ChatSession.user_id == user_id, ChatSession.is_deleted == 0
        # 历史数据可能没有 last_message_time，用 create_time 兜底再排序。
        activity = func.coalesce(ChatSession.last_message_time, ChatSession.create_time)
        statement = (
            select(ChatSession)
            .where(*predicate)
            .order_by(desc(activity), desc(ChatSession.id))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        count_statement = select(func.count(ChatSession.id)).where(*predicate)
        total = db.scalar(count_statement) or 0
        return list(db.scalars(statement).all()), total

    def find_session(self, db: Session, user_id: str, session_id: int) -> ChatSession | None:
        statement = select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user_id,
            ChatSession.is_deleted == 0,
        )
        return db.scalar(statement)

    def list_messages(self, db: Session, session: ChatSession) -> list[ChatMessage]:
        statement = (
            select(ChatMessage)
            .where(
                ChatMessage.session_id == session.id,
                ChatMessage.user_id == session.user_id,
                ChatMessage.is_deleted == 0,
            )
            .order_by(ChatMessage.id)
        )
        return list(db.scalars(statement).all())

    # ------------------------------------------------------------ 写入

    def create_session(
        self, db: Session, *, user_id: str, title: str, now: datetime
    ) -> ChatSession:
        session = ChatSession(user_id=user_id, title=title, last_message_time=now)
        db.add(session)
        db.flush()
        return session

    def add_message(
        self,
        db: Session,
        *,
        session_id: int,
        user_id: str,
        role: str,
        content: str,
        call_status: str = CallStatus.SUCCESS.value,
        token_count: int = 0,
    ) -> ChatMessage:
        message = ChatMessage(
            session_id=session_id,
            user_id=user_id,
            role=role,
            content=content,
            call_status=call_status,
            token_count=token_count,
        )
        db.add(message)
        db.flush()
        return message

    def touch_session(
        self,
        db: Session,
        session: ChatSession,
        *,
        now: datetime,
        title: str | None = None,
    ) -> None:
        """刷新会话活跃时间；传 title 时一并更新标题（仅首条消息使用）。"""

        session.last_message_time = now
        session.update_time = now
        if title is not None and title:
            session.title = title or DEFAULT_SESSION_TITLE
        db.flush()


chat_repository = ChatRepository()
