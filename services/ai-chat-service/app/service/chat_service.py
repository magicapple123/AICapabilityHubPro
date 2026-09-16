"""对话能力的业务编排（本服务的核心闭环）。

一次对话的固定处理顺序（指南 11.2 / team-tasks 3.2）：

    读取透传身份与 requestId → 准备会话 → 用户消息落库 → 校验用户/积分
    → 执行 Mock 或真实模型 → 助手消息落库 → 上报计费 → 提交事务 → 返回

事务与失败语义：

- 全流程复用 `get_db` 提供的同一个数据库会话，全部成功才 `commit`；
- 积分不足（`3001`）、下游不可用（`4002`）等异常一律 `rollback`，
  不留“有消息但没有计费”或“计费了但没有消息”的半成功状态；
- 真实模型超时/异常不抛错：按指南 3.4 返回兜底话术并标记 `degraded`，
  闭环不中断；降级调用不计费（`DEGRADED_POINTS_COST = 0`），
  但仍写调用流水，便于运营观察失败率。
"""

import time
from datetime import datetime
from uuid import uuid4

from loguru import logger
from sqlalchemy.orm import Session

from app.core.config import model_runtime_config, settings
from app.core.constants import (
    DEFAULT_SESSION_TITLE,
    DEGRADED_POINTS_COST,
    MOCK_REPLY,
    SESSION_TITLE_MAX_LENGTH,
    CallStatus,
    MessageRole,
)
from app.core.exceptions import BizException
from app.core.logging import get_request_id
from app.core.security import UserContext
from app.core.service_call import call_internal
from app.models.chat import ChatMessage, ChatSession
from app.repository.chat_repository import chat_repository
from app.schemas.chat import ChatCompletionRequest
from app.service.model_client import ModelReply, model_client

# 会话不存在、已软删除或不属于当前用户，统一按同一错误返回，不暴露资源归属。
SESSION_NOT_FOUND_CODE = 4004
SESSION_NOT_FOUND_MESSAGE = "会话不存在或不属于当前用户"


class ChatService:
    """对话能力编排；Mock 分支不访问任何外部模型。"""

    async def complete(
        self, db: Session, request: ChatCompletionRequest, user: UserContext
    ) -> dict:
        user_id = self._require_user(user)
        started_at = time.perf_counter()

        try:
            session, is_new_session = self._prepare_session(db, user_id, request)
            messages = self._build_messages(request)
            self._persist_user_message(db, session, request, user_id)

            if settings.enable_internal_chain:
                # 执行能力之前先校验账号状态与积分余额（不足时抛 3001）。
                await self._check_points(user_id)

            reply = await self._execute(request, messages)
            assistant_message = self._persist_assistant_message(
                db, session, reply, user_id, is_new_session=is_new_session
            )

            duration_ms = int((time.perf_counter() - started_at) * 1000)
            if settings.enable_internal_chain:
                await self._report_billing(user_id, request, reply, duration_ms)
        except Exception:
            # 含业务异常与数据库异常：统一回滚，避免半成功状态。
            db.rollback()
            raise

        db.commit()
        logger.info(
            "对话完成 session_id={} message_id={} status={} duration_ms={}",
            session.id,
            assistant_message.id,
            reply.call_status,
            duration_ms,
        )
        return self._response(
            session=session,
            message=assistant_message,
            reply=reply,
            prompt_tokens=sum(len(item.content) for item in request.messages),
            duration_ms=duration_ms,
        )

    # ------------------------------------------------------------ 身份与会话

    @staticmethod
    def _require_user(user: UserContext) -> str:
        """校验网关注入的用户 ID；必须是正整数（JWT 的 sub 是用户 ID）。"""

        raw = (user.user_id or "").strip()
        if not raw.isdigit() or int(raw) <= 0:
            raise BizException(1001, "未认证或登录已过期")
        return raw

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

    # ------------------------------------------------------------ 落库

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

    # ------------------------------------------------------------ 能力执行

    async def _check_points(self, user_id: str) -> None:
        """校验账号状态与积分余额；不足时下游直接返回 3001。"""

        await call_internal(
            settings.user_service_name,
            "GET",
            "/internal/user/check",
            params={"user_id": user_id, "points_cost": settings.points_cost},
        )

    async def _execute(
        self, request: ChatCompletionRequest, messages: list[dict[str, str]]
    ) -> ModelReply:
        runtime = model_runtime_config.snapshot()
        if runtime.use_mock:
            # Mock 模式绝不访问外部模型（team-tasks 3.2）。
            return ModelReply(
                content=MOCK_REPLY,
                call_status=CallStatus.SUCCESS.value,
                token_count=len(MOCK_REPLY),
                model_name=request.model,
                mock=True,
            )
        return await model_client.complete(
            messages,
            model=request.model,
            temperature=request.temperature,
            runtime=runtime,
        )

    async def _report_billing(
        self,
        user_id: str,
        request: ChatCompletionRequest,
        reply: ModelReply,
        duration_ms: int,
    ) -> None:
        """向 billing 上报本次调用；降级不计费但仍留流水。"""

        points = DEGRADED_POINTS_COST if reply.degraded else settings.points_cost
        await call_internal(
            settings.billing_service_name,
            "POST",
            "/internal/billing/record",
            json={
                "request_id": get_request_id(),
                "user_id": int(user_id),
                "service_name": settings.service_name,
                "model": reply.model_name,
                "points": points,
                "status": reply.call_status,
                "duration_ms": duration_ms,
                "remark": (
                    f"模型降级 error_code={reply.error_code}"
                    if reply.degraded
                    else f"模型 {request.model} 调用"
                ),
            },
        )

    # ------------------------------------------------------------ 响应

    @staticmethod
    def _response(
        *,
        session: ChatSession,
        message: ChatMessage,
        reply: ModelReply,
        prompt_tokens: int,
        duration_ms: int,
    ) -> dict:
        """OpenAI 风格的 chat.completion，附加会话与调用状态扩展字段。"""

        return {
            "id": f"chatcmpl-{uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": reply.model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": MessageRole.ASSISTANT.value,
                        "content": reply.content,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": reply.token_count,
                "total_tokens": prompt_tokens + reply.token_count,
            },
            "session_id": session.id,
            "message_id": message.id,
            "mock": reply.mock,
            "call_status": reply.call_status,
            "degraded": reply.degraded,
            "error_code": reply.error_code,
            "duration_ms": duration_ms,
        }


chat_service = ChatService()
