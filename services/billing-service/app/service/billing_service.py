"""计量业务逻辑：幂等记账与用量统计。

记账顺序是“幂等写调用记录（提交）→ 调 user 扣分 → 累计日用量（提交）”，
**跨服务调用期间不持有数据库连接**：

- **事务 1**：插入 `t_call_record` 并立即 `commit`。`(request_id, is_deleted)`
  唯一索引在数据库层保证“同一 ID 只记一次”，并发同 requestId 的后到者会撞
  `IntegrityError` 走 `_replay`，不会重复扣分；
- **无事务**：`await` user-service 的 `/internal/user/points/deduct`。这一步是
  20 ms 级 HTTP，旧实现把它夹在事务里，等于每个请求都占着池里一条连接等下游；
  2 worker × 20 并发直接打穿 `5+10` 的连接池（`QueuePool TimeoutError` → 4002）。
  拆开之后，连接占用从“插入 + 扣分 + 用量”缩到两条独立的短写；
- **事务 2**：`ON DUPLICATE KEY UPDATE` 原子累加日用量。

两条失败语义：

- **扣分失败**（3001 积分不足 / 1005 用户异常 / 4002 下游不可用）：事务 1 已提交，
  所以用**补偿删除**把刚写的明细物理撤掉，回到“没有这次记账”，再原样抛出。
  不保留成 failed 明细的原因有两个：`cost > 0` 的失败明细会被用量统计算进
  `total_cost`，破坏“成功数 = 账单数 = 流水数”的对账等式；而且它仍占着
  `request_id` 唯一键，同一 ID 重试会被判成 3002。删除是唯一同时满足
  “不产生半截账单”和“可重试”的收敛方式。
- **补偿删除自身失败**（数据库抖动）：只记 error 日志，明细会留成一条
  “有账单、无同 requestId 积分流水”的差异，由 `scripts/reconcile_billing.py`
  的 `billing_without_log` 检出。这是拆事务换吞吐的已知代价：两次提交之间的
  进程崩溃与它同属一个窗口，数量级是 20 ms/次。

错误码只用计费号段：`3001` 积分不足（由 user-service 透传）、
`3002` 同一 requestId 被不同调用占用；参数错误沿用平台统一的 `2001`，
下游不可用为基座的 `4002`。
"""

from datetime import date, datetime, time
from functools import partial

from anyio import to_thread
from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import PointBizType
from app.core.exceptions import BizException
from app.core.service_call import call_internal
from app.models import CallRecord
from app.repository import CallRecordRepository, UsageRepository
from app.repository import call_record_repository, usage_repository
from app.schemas import (
    ApiKeyUsageOut,
    BillingImage,
    BillingRecordOut,
    BillingRecordRequest,
    CallRecordOut,
    OverviewSummaryOut,
    OverviewUsageOut,
    PersonalUsageOut,
    ServiceUsageOut,
    UsageDailyOut,
    UsageSummaryOut,
    UserAggregateOut,
    UserUsageOut,
)
from app.service.user_status import user_status_service

# 同一 requestId 出现但关键字段不一致：属于客户端复用幂等键，明确拒绝而不是静默改写。
DUPLICATE_REQUEST_CODE = 3002
DUPLICATE_REQUEST_MESSAGE = "重复计费：同一 requestId 已被其它调用占用"

# 运营排行默认返回条数。
TOP_USER_LIMIT = 10


def images_for_storage(images: list[BillingImage]) -> list[dict[str, str]] | None:
    """把图片产物转成可写入 JSON 列的原生结构。

    `t_call_record.images` 是 MySQL JSON 列，驱动最终调用 `json.dumps`：
    直接塞 pydantic 模型会抛 `TypeError: Object of type BillingImage is not
    JSON serializable`（记成 4003）。这里统一转成 `[{url, revised_prompt}]`
    的纯 dict，读回时仍是 `list[dict]`，前端字段保持不变。
    """

    if not images:
        return None
    return [item.model_dump() for item in images]


class BillingService:
    """调用记账与用量统计用例。"""

    def __init__(
        self,
        records: CallRecordRepository | None = None,
        usage: UsageRepository | None = None,
    ) -> None:
        self.records = records or call_record_repository
        self.usage = usage or usage_repository

    # ------------------------------------------------------------ 记账（内部）

    @staticmethod
    async def _in_thread(func, *args, **kwargs):
        """把一段同步 SQLAlchemy 调用挪到工作线程执行（只搬家，不改语义）。

        为什么需要这一步：`/internal/billing/record` 是 `async def`，但 SQLAlchemy
        是同步的——每一条语句、每一次 `commit` 都会把整个事件循环钉住（本机实测
        单次往返 3 ms、带 fsync 的 commit 5–20 ms）。一个 billing 进程就是整条
        链路唯一的漏斗，20 并发时排队时间会盖过真实耗时（7.5 节的 42.7 ms 里
        大头是排队）。挪进线程后，同步 IO 只占线程，不再占事件循环。

        只保证「同一个 Session 一次只在一个线程里用」：所有调用都是 `await` 串行
        发出的，没有并发复用 Session，所以不需要额外的锁，也没有改成异步 ORM。
        """

        return await to_thread.run_sync(partial(func, *args, **kwargs))

    async def record(
        self, db: Session, payload: BillingRecordRequest, caller_user_id: str
    ) -> BillingRecordOut:
        """幂等记账；重复 requestId 只计一次费。"""

        # 内部接口不重复解析 JWT，但必须校验链路身份，防止替他用户记账。
        if str(payload.user_id) != caller_user_id:
            raise BizException(1001, "缺少或伪造的链路身份")

        existing = await self._in_thread(
            self.records.find_by_request_id, db, payload.request_id
        )
        if existing is not None:
            return await self._in_thread(self._replay, db, existing, payload)

        record = CallRecord(
            request_id=payload.request_id,
            user_id=payload.user_id,
            capability_id=payload.capability_id,
            service_name=payload.service_name,
            cost=payload.points,
            unit_price=payload.unit_price,
            call_status=payload.status.value,
            duration_ms=payload.duration_ms,
            model_name=payload.model,
            billing_mode=payload.billing_mode,
            prompt_tokens=payload.prompt_tokens,
            completion_tokens=payload.completion_tokens,
            token_source=payload.token_source,
            units=payload.units,
            # D3：只有文生图会带图片产物；其它执行器为 None（库里存 NULL）。
            images=images_for_storage(payload.images),
            # P6：Key 身份与入口；旧调用方不传时保持 NULL / 空串。
            api_key_id=payload.api_key_id,
            entrypoint=payload.entrypoint,
        )
        try:
            # 先占住幂等键：并发同 requestId 时，后到者会在此处阻塞并最终冲突。
            await self._in_thread(self.records.add, db, record)
        except IntegrityError:
            await self._in_thread(db.rollback)
            existing = await self._in_thread(
                self.records.find_by_request_id, db, payload.request_id
            )
            if existing is None:
                logger.error("记账幂等冲突但未找到明细 request_id={}", payload.request_id)
                raise BizException(4003, "系统内部错误") from None
            return await self._in_thread(self._replay, db, existing, payload)

        record_id = record.id
        # 事务 1：明细先落库并提交。提交这一步同时做两件事——
        # 让 `request_id` 唯一索引立刻对并发可见，以及**把连接还给池子**，
        # 使下面的扣分 HTTP 不再占用任何数据库连接。
        await self._in_thread(db.commit)

        try:
            balance_after = await self._settle_charge(payload)
        except Exception:
            # 扣分失败 → 补偿删除事务 1 写下的明细，回到“没有这次记账”。
            await self._in_thread(self._discard, db, record_id, payload.request_id)
            raise

        # 事务 2：只累加日用量（原子 UPSERT），依旧是一条短写。
        stat_date = date.today()
        await self._in_thread(self._commit_usage, db, payload, stat_date)
        logger.info(
            "调用已记账 request_id={} user_id={} cost={} balance_after={}",
            payload.request_id,
            payload.user_id,
            payload.points,
            balance_after,
        )
        return await self._in_thread(
            self._result, db, record, stat_date=stat_date, balance_after=balance_after
        )

    def _commit_usage(
        self, db: Session, payload: BillingRecordRequest, stat_date: date
    ) -> None:
        """事务 2：累加日用量并提交（独立成方法，便于整段丢进线程）。"""

        self.usage.upsert_daily(
            db,
            stat_date=stat_date,
            user_id=payload.user_id,
            capability_id=payload.capability_id,
            call_count=1,
            total_cost=payload.points,
        )
        db.commit()

    def _discard(self, db: Session, record_id: int, request_id: str) -> None:
        """补偿删除一条“已提交但未扣费成功”的调用明细。

        用主键做 Core `DELETE`：明细来自**另一个已提交的事务**，此时 ORM 对象
        可能已被 `rollback()` 过期，按主键删除既不需要重新加载，也不受会话状态影响。
        """

        try:
            db.rollback()
            self.records.discard(db, record_id)
            db.commit()
            logger.warning("扣分失败，已撤销调用明细 request_id={} record_id={}", request_id, record_id)
        except Exception:  # noqa: BLE001 - 补偿失败不能让原始错误被覆盖
            db.rollback()
            logger.error(
                "补偿删除调用明细失败 request_id={} record_id={}，请按 requestId 对账",
                request_id,
                record_id,
            )

    async def _settle_charge(self, payload: BillingRecordRequest) -> int | None:
        """结算本次调用的费用，返回扣分后的余额（免费能力返回 None）。

        - `points > 0`：调用 user-service 扣分，对方同时完成账号状态与余额校验；
        - `points = 0`：免费能力不产生扣分请求（对方要求 `amount >= 1`），
          因此这里单独调 user-service 校验账号状态，避免禁用账号经免费能力绕过状态校验。

        调用方**已经提交**明细并在本方法返回后才开下一个事务，所以这里既不
        `rollback` 也不 `commit`——回滚/补偿的责任在 `record()`，本方法只管
        “要么扣成功，要么抛出去”。
        """

        if payload.points <= 0:
            await user_status_service.ensure_active(payload.user_id)
            return None

        deduct = await call_internal(
            settings.user_service_name,
            "POST",
            "/internal/user/points/deduct",
            json={
                "user_id": payload.user_id,
                "amount": payload.points,
                "biz_type": PointBizType.CALL.value,
                "request_id": payload.request_id,
                "remark": payload.remark
                or f"{payload.service_name or 'capability'} 调用扣分",
            },
        )

        if not isinstance(deduct, dict):
            raise BizException(4002, "下游服务响应格式错误")
        balance_after = deduct.get("balance_after")
        return int(balance_after) if balance_after is not None else None

    # ------------------------------------------------------------ 对外查询

    def list_records(
        self,
        db: Session,
        user_id: int,
        *,
        start_date: date,
        end_date: date,
        service_name: str | None = None,
        call_status: str | None = None,
        api_key_id: int | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> tuple[list[CallRecordOut], int]:
        rows, total = self.records.list_by_user(
            db,
            user_id,
            start_date=start_date,
            end_date=end_date,
            service_name=service_name,
            call_status=call_status,
            api_key_id=api_key_id,
            page=page,
            page_size=page_size,
        )
        return [CallRecordOut.model_validate(row) for row in rows], total

    def key_usage(
        self, db: Session, user_id: int, *, start_date: date, end_date: date
    ) -> list[ApiKeyUsageOut]:
        """按 Key 的使用分布；供运营在用户详情里判断"哪把 Key 出了问题"。"""

        return [
            ApiKeyUsageOut(
                api_key_id=row[0],
                call_count=row[1],
                total_cost=row[2],
                last_call_at=row[3],
            )
            for row in self.records.group_by_api_key(
                db, user_id, start_date=start_date, end_date=end_date
            )
        ]

    def personal_usage(
        self, db: Session, user_id: int, *, start_date: date, end_date: date
    ) -> PersonalUsageOut:
        """当前用户的用量统计。"""

        summary = self.records.summary(
            db, start_date=start_date, end_date=end_date, user_id=user_id
        )
        by_day = self.usage.sum_by_day(
            db, start_date=start_date, end_date=end_date, user_id=user_id
        )
        by_service = self.records.group_by_service(
            db, start_date=start_date, end_date=end_date, user_id=user_id
        )

        return PersonalUsageOut(
            start_date=start_date,
            end_date=end_date,
            summary=UsageSummaryOut(
                call_count=summary["call_count"],
                total_cost=summary["total_cost"],
                success_count=summary["success_count"],
                degraded_count=summary["degraded_count"],
                failed_count=summary["failed_count"],
            ),
            by_day=[self._daily_out(row) for row in by_day],
            by_service=[self._service_out(row) for row in by_service],
        )

    def user_aggregates(
        self, db: Session, *, start_date: date, end_date: date
    ) -> list[UserAggregateOut]:
        """全量用户的用量聚合（P5）。

        只返回"花过钱/调过用"的用户；零调用用户由 user-service 的资料列表补位，
        两边在**前端**按 `user_id` join（跨库不 join，见契约）。
        """

        return [
            UserAggregateOut(
                user_id=row[0],
                call_count=row[1],
                total_cost=row[2],
                last_call_at=(
                    datetime.combine(row[3], time.min) if row[3] else None
                ),
            )
            for row in self.usage.sum_by_user(
                db, start_date=start_date, end_date=end_date
            )
        ]

    def overview(
        self, db: Session, *, start_date: date, end_date: date
    ) -> OverviewUsageOut:
        """全局运营统计。

        契约第 6 节已登记：平台暂无角色体系，当前按“已登录即可访问”处理，
        与 capability-service 的 `/api/capability/manage` 保持同一现状。
        """

        summary = self.records.summary(db, start_date=start_date, end_date=end_date)
        by_day = self.usage.sum_by_day(db, start_date=start_date, end_date=end_date)
        by_service = self.records.group_by_service(
            db, start_date=start_date, end_date=end_date
        )
        top_users = self.records.top_users(
            db, start_date=start_date, end_date=end_date, limit=TOP_USER_LIMIT
        )

        return OverviewUsageOut(
            start_date=start_date,
            end_date=end_date,
            summary=OverviewSummaryOut(
                call_count=summary["call_count"],
                total_cost=summary["total_cost"],
                success_count=summary["success_count"],
                degraded_count=summary["degraded_count"],
                failed_count=summary["failed_count"],
                user_count=summary["user_count"],
            ),
            by_day=[self._daily_out(row) for row in by_day],
            by_service=[self._service_out(row) for row in by_service],
            top_users=[
                UserUsageOut(user_id=row[0], call_count=row[1], total_cost=row[2])
                for row in top_users
            ],
        )

    # ------------------------------------------------------------ 内部工具

    def _replay(
        self, db: Session, existing: CallRecord, payload: BillingRecordRequest
    ) -> BillingRecordOut:
        """幂等重放：校验关键字段一致后返回首次结果，不再扣分。"""

        if not self._is_same_call(existing, payload):
            raise BizException(DUPLICATE_REQUEST_CODE, DUPLICATE_REQUEST_MESSAGE)

        logger.info(
            "重复记账请求已幂等命中 request_id={} user_id={}",
            payload.request_id,
            payload.user_id,
        )
        return self._result(
            db,
            existing,
            stat_date=existing.create_time.date(),
            balance_after=None,
            duplicated=True,
        )

    @staticmethod
    def _is_same_call(existing: CallRecord, payload: BillingRecordRequest) -> bool:
        """判断重复 requestId 是否来自同一次调用。"""

        return (
            existing.user_id == payload.user_id
            and existing.service_name == payload.service_name
            and existing.capability_id == payload.capability_id
            and existing.cost == payload.points
            and existing.unit_price == payload.unit_price
            and existing.model_name == payload.model
            and existing.duration_ms == payload.duration_ms
            and existing.call_status == payload.status.value
            # C1/C2：同一次调用的 token 明细与计价模式必须一致，否则视为复用幂等键。
            and existing.billing_mode == payload.billing_mode
            and existing.prompt_tokens == payload.prompt_tokens
            and existing.completion_tokens == payload.completion_tokens
            and existing.units == payload.units
        )

    def _result(
        self,
        db: Session,
        record: CallRecord,
        *,
        stat_date: date,
        balance_after: int | None,
        duplicated: bool = False,
    ) -> BillingRecordOut:
        usage = self.usage.find_daily(
            db,
            stat_date=stat_date,
            user_id=record.user_id,
            capability_id=record.capability_id,
        )
        return BillingRecordOut(
            record_id=record.id,
            request_id=record.request_id,
            user_id=record.user_id,
            capability_id=record.capability_id,
            service_name=record.service_name,
            cost=record.cost,
            unit_price=record.unit_price,
            call_status=record.call_status,
            duplicated=duplicated,
            balance_after=balance_after,
            stat_date=stat_date,
            call_count=usage.call_count if usage is not None else 0,
            total_cost=usage.total_cost if usage is not None else 0,
            billing_mode=record.billing_mode,
            prompt_tokens=record.prompt_tokens,
            completion_tokens=record.completion_tokens,
            token_source=record.token_source,
            units=record.units,
            images=list(record.images) if record.images else [],
        )

    @staticmethod
    def _daily_out(row: tuple[date, int, int]) -> UsageDailyOut:
        return UsageDailyOut(stat_date=row[0], call_count=row[1], total_cost=row[2])

    @staticmethod
    def _service_out(row: tuple[str, int, int]) -> ServiceUsageOut:
        return ServiceUsageOut(service_name=row[0], call_count=row[1], total_cost=row[2])


billing_service = BillingService()
