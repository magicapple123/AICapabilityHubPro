"""Conversation persistence extracted without behavior changes; transaction owned by caller."""
from datetime import datetime
from loguru import logger
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.constants import DEFAULT_SESSION_TITLE, SESSION_TITLE_MAX_LENGTH, MessageRole
from app.core.exceptions import BizException
from app.models.chat import ChatMessage, ChatSession
from app.repository.chat_repository import chat_repository
from app.schemas.chat import ChatCompletionRequest
from app.service.model_client import ModelReply

SESSION_NOT_FOUND_CODE = 4004
SESSION_NOT_FOUND_MESSAGE = "会话不存在或不属于当前用户"

class ConversationStore:
    def _prepare_session(
        self, db: Session, user_id: str, request: ChatCompletionRequest
    ) -> tuple[ChatSession, bool]:
        """取会话或新建会话；返回 (会话, 是否新建)。"""

        now = datetime.now()
        if request.session_id is None:
            session = chat_repository.create_session(
                db, user_id=user_id, title=self._build_title(request), now=now
            )
            return session, True

        session = chat_repository.find_session(db, user_id, request.session_id)
        if session is None:
            raise BizException(SESSION_NOT_FOUND_CODE, SESSION_NOT_FOUND_MESSAGE)
        return session, False

    @staticmethod
    def _build_title(request: ChatCompletionRequest) -> str:
        """用最后一条用户消息生成标题，超长截断。"""

        for message in reversed(request.messages):
            if message.role == MessageRole.USER.value:
                text = " ".join(message.content.split())
                if text:
                    return text[:SESSION_TITLE_MAX_LENGTH]
        return DEFAULT_SESSION_TITLE

    @staticmethod
    def _build_messages(request: ChatCompletionRequest) -> list[dict[str, str]]:
        """组装模型入参；未显式提供 system 消息时注入配置的默认提示词。"""

        messages = [
            {"role": message.role, "content": message.content}
            for message in request.messages
        ]
        has_system = any(item["role"] == MessageRole.SYSTEM.value for item in messages)
        if settings.default_system_prompt and not has_system:
            messages.insert(
                0,
                {
                    "role": MessageRole.SYSTEM.value,
                    "content": settings.default_system_prompt,
                },
            )
        return messages

    def _persist_user_message(
        self,
        db: Session,
        session: ChatSession,
        request: ChatCompletionRequest,
        user_id: str,
    ) -> ChatMessage:
        last_user_content = ""
        for message in reversed(request.messages):
            if message.role == MessageRole.USER.value:
                last_user_content = message.content
                break
        return chat_repository.add_message(
            db,
            session_id=session.id,
            user_id=user_id,
            role=MessageRole.USER.value,
            content=last_user_content,
            token_count=len(last_user_content),
        )

    def _persist_assistant_message(
        self,
        db: Session,
        session: ChatSession,
        reply: ModelReply,
        user_id: str,
        *,
        is_new_session: bool,
    ) -> ChatMessage:
        message = chat_repository.add_message(
            db,
            session_id=session.id,
            user_id=user_id,
            role=MessageRole.ASSISTANT.value,
            content=reply.content,
            call_status=reply.call_status,
            token_count=reply.token_count,
        )
        # 刷新会话活跃时间；新建会话时标题已在 _prepare_session 中确定。
        chat_repository.touch_session(db, session, now=datetime.now())
        if is_new_session:
            logger.info("新建会话 session_id={} user_id={}", session.id, user_id)
        return message
