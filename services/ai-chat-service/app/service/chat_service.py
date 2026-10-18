"""Capability execution: fresh catalog -> bounded input -> points -> adapter -> settlement.

The local message transaction does not make remote billing atomic. Reconcile
a billing-success/local-commit failure by requestId; do not retry the model blindly.
"""
import time
from loguru import logger
from sqlalchemy.orm import Session
from app.core.config import model_runtime_config, settings
from app.core.exceptions import BizException
from app.core.security import UserContext
from app.core.service_call import call_internal
from app.schemas.chat import ChatCompletionRequest
from app.service.capability_client import capability_client
from app.service.capability_adapters import prepare_execution, execute_prepared
from app.service.completion_result import completion_result
from app.service.conversation_store import ConversationStore
from app.service.execution_billing import check_points, report_execution
from app.service.model_client import model_client


class ChatService(ConversationStore):
    async def complete(self, db: Session, request: ChatCompletionRequest, user: UserContext) -> dict:
        user_id = self._require_user(user)
        started_at = time.perf_counter()
        try:
            # Every request, including the legacy capability_id=1 path, is revalidated.
            definition = await capability_client.fetch(request.capability_id)
            execution = prepare_execution(definition, request)
            if settings.enable_internal_chain:
                await check_points(user_id, definition.price_per_call, call_internal=call_internal)
            effective = execution.request
            session, is_new = self._prepare_session(db, user_id, effective)
            self._persist_user_message(db, session, effective, user_id)
            reply = await execute_prepared(
                execution, runtime=model_runtime_config.snapshot(), model_client=model_client,
            )
            message = self._persist_assistant_message(
                db, session, reply, user_id, is_new_session=is_new,
            )
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            receipt = None
            if settings.enable_internal_chain:
                receipt = await report_execution(
                    user_id, definition, reply, duration_ms, call_internal=call_internal,
                )
            db.commit()
        except Exception:
            db.rollback()
            raise
        logger.info(
            "能力调用完成 capability_id={} session_id={} status={} duration_ms={}",
            definition.id, session.id, reply.call_status, duration_ms,
        )
        return completion_result(
            definition=definition, session=session, message=message, reply=reply,
            prompt_tokens=sum(len(item.content) for item in effective.messages),
            duration_ms=duration_ms, receipt=receipt,
        )

    @staticmethod
    def _require_user(user: UserContext) -> str:
        raw = (user.user_id or "").strip()
        if not raw.isdigit() or int(raw) <= 0:
            raise BizException(1001, "未认证或登录已过期")
        return raw


chat_service = ChatService()
