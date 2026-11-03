"""Conversation persistence extracted without behavior changes; transaction owned by caller."""
from datetime import datetime
from loguru import logger
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.constants import DEFAULT_SESSION_TITLE, FAILED_REPLY, SESSION_TITLE_MAX_LENGTH, CallStatus, MessageRole
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
            # 用户消息的 token 数要等上游 usage 才知道准确值；这里不猜，避免与助手消息口径不一致。
            token_count=0,
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
            token_count=reply.total_tokens,
            error_code=reply.error_code,
        )
        # 刷新会话活跃时间；新建会话时标题已在 _prepare_session 中确定。
        chat_repository.touch_session(db, session, now=datetime.now())
        if is_new_session:
            logger.info("新建会话 session_id={} user_id={}", session.id, user_id)
        return message

    def _persist_failed_message(
        self,
        db: Session,
        session: ChatSession,
        user_id: str,
        error_code: int,
    ) -> ChatMessage:
        """A1：模型/计费失败时写一条占位消息，明确标记 `failed` 与错误码。

        用户消息已在前一个事务提交，若这里什么都不写，历史里会留下"只有提问"的
        缺口，且无法区分"用户没发"与"调用失败"。
        """

        message = chat_repository.add_message(
            db,
            session_id=session.id,
            user_id=user_id,
            role=MessageRole.ASSISTANT.value,
            content=FAILED_REPLY,
            call_status=CallStatus.FAILED.value,
            token_count=0,
            error_code=error_code,
        )
        chat_repository.touch_session(db, session, now=datetime.now())
        return message

    def _mark_failed_message(
        self, db: Session, message_id: int, user_id: str, error_code: int
    ) -> None:
        """把**已提交**的助手消息原地改成 `failed`（账单阶段失败的落地方式）。

        事务边界拆开之后，助手消息先 commit 再去上报账单：账单失败时那条消息
        已经落库且主键已返回，唯一正确的收敛方式是原地改写，而不是再插一条
        占位（会让同一轮对话出现两个 assistant）。
        """

        chat_repository.mark_message_failed(
            db,
            message_id=message_id,
            user_id=user_id,
            content=FAILED_REPLY,
            error_code=error_code,
        )
