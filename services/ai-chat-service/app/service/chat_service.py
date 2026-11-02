"""Capability execution: fresh catalog -> bounded input -> points -> adapter -> settlement.

C1/A1 落实后的执行链：

1. 目录读取与余额预检（不碰数据库，不占连接）；
2. **事务 1**：建/取会话 + 写用户消息 → `commit`（模型调用期间不持有事务，
   连接池不再被 3–10 秒的上游调用占住）；
3. 模型调用（无数据库连接）；
4. **事务 2**：写助手消息 + 上报账单 → `commit`。

失败语义（已冻结）：
- 模型降级：仍写助手消息并落 `degraded`，照旧不计费；
- 模型硬异常 / 账单失败：助手消息回滚，另写一条 `failed` 占位消息（带 `error_code`），
  保证"用户消息已提交"这一事实不被静默丢失；
- 计费仍以 `requestId` 为幂等键，一次调用只产生一条账单。
"""
import time
from collections.abc import AsyncGenerator
from loguru import logger
from sqlalchemy.orm import Session
from app.core.config import model_runtime_config, settings
from app.core.constants import FAILED_REPLY, CallStatus, Executor
from app.core.exceptions import BizException
from app.core.security import UserContext
from app.core.service_call import call_internal
from app.schemas.chat import ChatCompletionRequest
from app.service.capability_client import capability_client
from app.service.capability_adapters import (
    effective_max_tokens,
    execute_prepared,
    prepare_execution,
)
from app.service.completion_result import completion_result
from app.service.conversation_store import ConversationStore
from app.service.execution_billing import check_points, report_execution
from app.service.model_client import model_client
from app.core.rate_limit import rate_limiter
from app.service.pricing import units_for
from app.service.stream_service import StreamOutcome, stream_upstream
from app.service.provider_service import provider_service


class ChatService(ConversationStore):
    async def complete(self, db: Session, request: ChatCompletionRequest, user: UserContext) -> dict:
        user_id = self._require_user(user)
        # A4：流式同样在入口限流，避免"流式绕过限流"的漏洞。
        rate_limiter.acquire(str(user_id))
        started_at = time.perf_counter()
        # 目录与预检凡是失败的，都不应留下任何会话或消息（旧行为保持不变）。
        definition = await capability_client.fetch(request.capability_id)
        execution = prepare_execution(definition, request)
        units = units_for(definition.billing_mode, execution.units)
        if settings.enable_internal_chain:
            await check_points(user_id, definition, units=units, call_internal=call_internal)

        # D1/D2：绑定供应商时用供应商的地址/密钥/超时；读库发生在事务外，不占连接。
        provider = (
            provider_service.resolve_runtime(
                db, definition.provider_alias,
                model=execution.request.model or None,
            )
            if definition.provider_alias else None
        )
        effective = execution.request
        session, is_new = self._begin_turn(db, user_id, effective)

        try:
            reply = await execute_prepared(
                execution, runtime=model_runtime_config.snapshot(), model_client=model_client,
                provider=provider, definition=definition,
            )
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            message = self._persist_assistant_message(
                db, session, reply, user_id, is_new_session=is_new,
            )
            receipt = None
            if settings.enable_internal_chain:
                receipt = await report_execution(
                    user_id, definition, reply, duration_ms, units=units, call_internal=call_internal,
                )
            db.commit()
        except Exception as error:
            db.rollback()
            code = error.code if isinstance(error, BizException) else 4003
            # 用户消息已在事务 1 提交，这里补一条失败的助手占位消息，避免"只有提问没有结果"。
            self._record_failure(db, session, user_id, code)
            logger.warning(
                "能力调用失败 capability_id={} session_id={} code={}",
                definition.id, session.id, code,
            )
            if isinstance(error, BizException):
                raise
            # 非业务异常统一折算成 4003，避免把堆栈原样抛给调用方。
            raise BizException(4003, "系统内部错误") from error

        logger.info(
            "能力调用完成 capability_id={} session_id={} status={} mode={} tokens={} duration_ms={}",
            definition.id, session.id, reply.call_status, definition.billing_mode,
            reply.total_tokens, duration_ms,
        )
        return completion_result(
            definition=definition, session=session, message=message, reply=reply,
            duration_ms=duration_ms, receipt=receipt,
        )


    async def stream(
        self, db: Session, request: ChatCompletionRequest, user: UserContext
    ) -> AsyncGenerator[str, None]:
        """E1 真流式：逐块转发上游，流期间不持有数据库事务。

        事务切分与 A1 一致：用户消息先提交 → 上游流（无连接）→ 流结束后新事务
        写助手消息与账单。客户端断开时上游流被取消，只写失败占位、不计费。
        """

        user_id = self._require_user(user)
        # A4：流式同样在入口限流，避免"流式绕过限流"的漏洞。
        rate_limiter.acquire(str(user_id))
        started_at = time.perf_counter()
        definition = await capability_client.fetch(request.capability_id)
        execution = prepare_execution(definition, request)
        if execution.executor != Executor.CHAT.value:
            raise BizException(2008, "只有 chat 执行器支持流式")
        units = units_for(definition.billing_mode, execution.units)
        if settings.enable_internal_chain:
            await check_points(user_id, definition, units=units, call_internal=call_internal)

        provider = (
            provider_service.resolve_runtime(
                db, definition.provider_alias, model=execution.request.model or None
            )
            if definition.provider_alias else None
        )
        runtime = model_runtime_config.snapshot()
        effective = execution.request
        session, is_new = self._begin_turn(db, user_id, effective)

        outcome = StreamOutcome()
        payload = {
            "model": provider.model if provider and provider.model else effective.model,
            "messages": [
                message.model_dump() for message in effective.messages
            ],
            "temperature": effective.temperature,
            "max_tokens": effective_max_tokens(definition, None),
        }
        for key, value in (execution.model_params or {}).items():
            payload[key] = value

        try:
            async for line in stream_upstream(
                base_url=provider.base_url if provider else runtime.model_base_url,
                api_key=provider.api_key if provider else runtime.model_api_key,
                payload=payload,
                timeout=provider.timeout if provider else settings.model_timeout,
                outcome=outcome,
            ):
                yield line
        finally:
            await self._settle_stream(
                db, session, user_id, definition, outcome, units,
                int((time.perf_counter() - started_at) * 1000), is_new,
            )

    async def _settle_stream(
        self, db: Session, session, user_id: str, definition, outcome: StreamOutcome,
        units: int, duration_ms: int, is_new: bool,
    ) -> None:
        """流结束后结算；任何异常都只记日志，不影响已经发出去的内容。"""

        from app.service.model_client import ModelReply

        try:
            if outcome.aborted or outcome.error_code is not None:
                reply = ModelReply(
                    content=FAILED_REPLY,
                    call_status=CallStatus.FAILED.value,
                    model_name=outcome.model_name or "",
                    error_code=outcome.error_code or 4003,
                )
            else:
                reply = ModelReply(
                    content=outcome.content,
                    call_status=CallStatus.SUCCESS.value,
                    model_name=outcome.model_name,
                    prompt_tokens=outcome.prompt_tokens,
                    completion_tokens=outcome.completion_tokens,
                    usage_source=outcome.usage_source,
                )
            self._persist_assistant_message(
                db, session, reply, user_id, is_new_session=is_new,
            )
            if settings.enable_internal_chain:
                await report_execution(
                    user_id, definition, reply, duration_ms, units=units,
                    call_internal=call_internal,
                )
            db.commit()
            logger.info(
                "流式调用完成 capability_id={} frames={} tokens={} aborted={}",
                definition.id, outcome.frames, outcome.total_tokens, outcome.aborted,
            )
        except Exception as error:  # noqa: BLE001 - 结算失败不能影响已发送内容
            db.rollback()
            logger.warning(
                "流式结算失败 capability_id={} type={}", definition.id, type(error).__name__
            )
            try:
                self._record_failure(db, session, user_id, 4003)
            except Exception:  # noqa: BLE001
                logger.error("流式失败占位写入失败 session_id={}", session.id)

    def _begin_turn(
        self, db: Session, user_id: str, request: ChatCompletionRequest,
    ):
        """事务 1：会话与用户消息先落库，随后释放连接。"""

        try:
            session, is_new = self._prepare_session(db, user_id, request)
            self._persist_user_message(db, session, request, user_id)
            db.commit()
            return session, is_new
        except Exception:
            db.rollback()
            raise

    def _record_failure(self, db: Session, session, user_id: str, code: int) -> None:
        """写失败占位消息；本身失败只记日志，不覆盖原始异常。"""

        try:
            self._persist_failed_message(db, session, user_id, code)
            db.commit()
        except Exception:
            db.rollback()
            logger.error("失败占位消息写入失败 session_id={} code={}", session.id, code)

    @staticmethod
    def _require_user(user: UserContext) -> str:
        raw = (user.user_id or "").strip()
        if not raw.isdigit() or int(raw) <= 0:
            raise BizException(1001, "未认证或登录已过期")
        return raw


chat_service = ChatService()
