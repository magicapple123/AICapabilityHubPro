"""Capability execution: fresh catalog -> bounded input -> points -> adapter -> settlement.

C1/A1 落实后的执行链：

1. 目录读取与余额预检（不碰数据库，不占连接）；
2. **事务 1**：建/取会话 + 写用户消息 → `commit`（模型调用期间不持有事务，
   连接池不再被 3–10 秒的上游调用占住）；
3. 模型调用（无数据库连接）；
4. **事务 2**：写助手消息 → `commit`（立刻还连接）；
5. 账单上报（HTTP，无数据库连接）；
6. 需要落 receipt 时才开**事务 3**，且只写 receipt 本身。

第 4/5 步的先后是这一版的关键：旧实现把「写助手消息」和「上报账单」放在同一个
事务里，`report_execution` 的 40 ms HTTP 全程占着池里的一条连接，2 worker × 20 并发
直接把 `5+10` 的连接池打穿（`QueuePool limit ... reached` → 4002）。把 commit 提到
上报之前，连接占用从"模型耗时 + 账单耗时"缩到"一条 INSERT"。

失败语义（已冻结）：
- 模型降级：仍写助手消息并落 `degraded`，照旧不计费；
- 模型硬异常：助手消息未提交 → 回滚后补写一条 `failed` 占位消息（带 `error_code`）；
- 账单失败：助手消息**已提交**，把它原地改成 `failed`（同一条记录，不新增、不留半截），
  保证"用户消息已提交"这一事实不被静默丢失，历史里也不会出现"只有提问"；
- 计费仍以 `requestId` 为幂等键，一次调用只产生一条账单。
"""
import time
from collections.abc import AsyncGenerator
from anyio import to_thread
from loguru import logger
from sqlalchemy.orm import Session
from app.core.config import model_runtime_config, settings
from app.core.constants import FAILED_REPLY, CallStatus, Executor
from app.core.deadline import Deadline
from app.core.exceptions import BizException
from app.core.security import UserContext
from app.core.service_call import call_internal
from app.schemas.chat import ChatCompletionRequest
from app.service.capability_client import capability_client
from app.service.capability_adapters import (
    effective_max_tokens,
    execute_prepared,
    prepare_execution,
    resolve_upstream_model,
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
        # P16：入口算一次整体预算，后续所有上游调用（含重试）都在它之内。
        deadline = Deadline.start()
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
                model=execution.requested_model,
            )
            if definition.provider_alias else None
        )
        effective = execution.request
        session, is_new = await to_thread.run_sync(self._begin_turn, db, user_id, effective)
        # 事务 1 已 commit：会话主键是稳定值，先取出来，后面所有日志与出参都用它，
        # 不再通过 ORM 属性间接读取（见下方事务 2 的说明）。
        session_id = session.id
        message_id: int | None = None
        committed = False

        try:
            reply = await execute_prepared(
                execution, runtime=model_runtime_config.snapshot(), model_client=model_client,
                provider=provider, definition=definition, deadline=deadline,
            )
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            session_id, message_id = await to_thread.run_sync(
                self._commit_assistant, db, session, reply, user_id, is_new,
            )
            committed = True
            receipt = None
            if settings.enable_internal_chain:
                # 账单是 40 ms 级 HTTP，此刻本请求不持有任何数据库连接。
                receipt = await report_execution(
                    user_id, definition, reply, duration_ms, units=units,
                    call_internal=call_internal,
                    api_key_id=user.api_key_id, entrypoint=user.entrypoint,
                )
        except Exception as error:
            db.rollback()
            code = error.code if isinstance(error, BizException) else 4003
            # 用户消息已在事务 1 提交。助手消息是否已提交，决定了失败怎么落地：
            # 已提交（账单阶段失败）→ 原地把那条消息标成 failed；
            # 未提交（模型阶段失败）→ 补写一条 failed 占位。两条路径都只留一条
            # assistant 消息，既不丢"用户已提问"，也不留"半截成功"。
            if committed and message_id is not None:
                self._mark_failure(db, message_id, user_id, code)
            else:
                self._record_failure(db, session, user_id, code)
            logger.warning(
                "能力调用失败 capability_id={} session_id={} code={}",
                definition.id, session_id, code,
            )
            if isinstance(error, BizException):
                raise
            # 非业务异常统一折算成 4003，避免把堆栈原样抛给调用方。
            raise BizException(4003, "系统内部错误") from error

        logger.info(
            "能力调用完成 capability_id={} session_id={} status={} mode={} tokens={} duration_ms={}",
            definition.id, session_id, reply.call_status, definition.billing_mode,
            reply.total_tokens, duration_ms,
        )
        return completion_result(
            definition=definition, session_id=session_id, message_id=message_id,
            reply=reply, duration_ms=duration_ms, receipt=receipt,
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
        # P16：流式同样受整体预算约束（超时取 min(供应商配置, 剩余预算)）。
        deadline = Deadline.start()
        definition = await capability_client.fetch(request.capability_id)
        execution = prepare_execution(definition, request)
        if execution.executor != Executor.CHAT.value:
            raise BizException(2008, "只有 chat 执行器支持流式")
        units = units_for(definition.billing_mode, execution.units)
        if settings.enable_internal_chain:
            await check_points(user_id, definition, units=units, call_internal=call_internal)

        provider = (
            provider_service.resolve_runtime(
                db, definition.provider_alias, model=execution.requested_model
            )
            if definition.provider_alias else None
        )
        runtime = model_runtime_config.snapshot()
        effective = execution.request
        session, is_new = self._begin_turn(db, user_id, effective)

        outcome = StreamOutcome()
        payload = {
            "model": resolve_upstream_model(execution, provider),
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
                timeout=deadline.clamp(
                    provider.timeout if provider else settings.model_timeout
                ),
                outcome=outcome,
                # P15：钉扎建连；P16：按 alias 熔断。
                target=getattr(provider, "target", None) if provider else None,
                breaker_key=getattr(provider, "alias", None) if provider else None,
            ):
                yield line
        finally:
            await self._settle_stream(
                db, session, user_id, definition, outcome, units,
                int((time.perf_counter() - started_at) * 1000), is_new,
                api_key_id=user.api_key_id, entrypoint=user.entrypoint,
            )

    async def _settle_stream(
        self, db: Session, session, user_id: str, definition, outcome: StreamOutcome,
        units: int, duration_ms: int, is_new: bool, *,
        api_key_id: int | None = None, entrypoint: str = "web",
    ) -> None:
        """流结束后结算；任何异常都只记日志，不影响已经发出去的内容。"""

        from app.service.model_client import ModelReply

        session_id = session.id
        message_id: int | None = None
        committed = False
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
            message = self._persist_assistant_message(
                db, session, reply, user_id, is_new_session=is_new,
            )
            message_id = message.id
            # 与 complete 同一套事务边界：助手消息先提交还连接，账单再走 HTTP。
            db.commit()
            committed = True
            if settings.enable_internal_chain:
                await report_execution(
                    user_id, definition, reply, duration_ms, units=units,
                    call_internal=call_internal,
                    api_key_id=api_key_id, entrypoint=entrypoint,
                )
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
                if committed and message_id is not None:
                    self._mark_failure(db, message_id, user_id, 4003)
                else:
                    self._record_failure(db, session, user_id, 4003)
            except Exception:  # noqa: BLE001
                logger.error("流式失败占位写入失败 session_id={}", session_id)

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

    def _commit_assistant(
        self, db: Session, session, reply, user_id: str, is_new: bool,
    ) -> tuple[int, int]:
        """事务 2：写助手消息 → 提交 → 返回 (session_id, message_id)。

        两个关键点：

        1. **先 commit 再上报账单**。旧实现把这两件事放在同一个事务里，
           `report_execution` 的 40 ms HTTP 全程占着池里一条连接；2 worker ×
           20 并发就是这样把 `5+10` 的连接池打穿、billing 500 → chat 4002 的。
        2. **主键在 commit 之前取出来**。`SessionLocal(expire_on_commit=False)`
           （app/db/session.py:25）本来就不会让 commit 后读属性触发 SELECT，
           但那样一旦有人把配置改回默认值，就会变成"commit 之后再借一条连接
           重新加载"——拆事务的收益被静默吃掉。先把值取干净，这条约束就不再
           依赖 session 配置。

        整段同步 SQLAlchemy 由调用方丢进工作线程：一次带 fsync 的 commit 在本机
        是 5–20 ms，留在事件循环里会把同一个 worker 上其它请求全部钉住。
        """

        message = self._persist_assistant_message(
            db, session, reply, user_id, is_new_session=is_new,
        )
        session_id, message_id = session.id, message.id
        db.commit()
        return session_id, message_id

    def _record_failure(self, db: Session, session, user_id: str, code: int) -> None:
        """写失败占位消息；本身失败只记日志，不覆盖原始异常。"""

        try:
            self._persist_failed_message(db, session, user_id, code)
            db.commit()
        except Exception:
            db.rollback()
            logger.error("失败占位消息写入失败 session_id={} code={}", session.id, code)

    def _mark_failure(self, db: Session, message_id: int, user_id: str, code: int) -> None:
        """把已提交的助手消息原地改成 failed（账单阶段失败的唯一落地点）。

        不能再补写占位：那条助手消息已经提交、`message_id` 可能已经进了日志，
        再插一条会让同一轮对话在历史里出现两个 assistant。这里用一条 UPDATE
        覆盖内容/状态/token 数，语义上等价于"这次回答作废"。
        """

        try:
            self._mark_failed_message(db, message_id, user_id, code)
            db.commit()
        except Exception:
            db.rollback()
            logger.error("助手消息失败标记写入失败 message_id={} code={}", message_id, code)

    @staticmethod
    def _require_user(user: UserContext) -> str:
        raw = (user.user_id or "").strip()
        if not raw.isdigit() or int(raw) <= 0:
            raise BizException(1001, "未认证或登录已过期")
        return raw


chat_service = ChatService()
