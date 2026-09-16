"""计量业务逻辑：幂等记账与用量统计。

记账顺序固定为“幂等写调用记录 → 调 user 扣分 → 累计日用量”，并且三步在同一
数据库事务内完成（指南 11.2 / team-tasks 4.2）：

- 明细先 `flush` 抢占 `request_id` 唯一键，但不提交；扣分失败时 `rollback`
  会一并撤销明细，**不会留下“记录了调用但没扣分”的半成功状态**；
- 扣分走 user-service 的 `/internal/user/points/deduct`，由对方做乐观锁与幂等，
  本服务不读 `user_db`；
- 日用量用 `ON DUPLICATE KEY UPDATE` 原子累加。

错误码只用计费号段：`3001` 积分不足（由 user-service 透传）、
`3002` 同一 requestId 被不同调用占用；参数错误沿用平台统一的 `2001`，
下游不可用为基座的 `4002`。
"""

from datetime import date

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
    BillingRecordOut,
    BillingRecordRequest,
    CallRecordOut,
    OverviewSummaryOut,
    OverviewUsageOut,
    PersonalUsageOut,
    ServiceUsageOut,
    UsageDailyOut,
    UsageSummaryOut,
    UserUsageOut,
)
from app.service.user_status import user_status_service

# 同一 requestId 出现但关键字段不一致：属于客户端复用幂等键，明确拒绝而不是静默改写。
DUPLICATE_REQUEST_CODE = 3002
DUPLICATE_REQUEST_MESSAGE = "重复计费：同一 requestId 已被其它调用占用"

# 运营排行默认返回条数。
TOP_USER_LIMIT = 10


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

    async def record(
        self, db: Session, payload: BillingRecordRequest, caller_user_id: str
    ) -> BillingRecordOut:
        """幂等记账；重复 requestId 只计一次费。"""

        # 内部接口不重复解析 JWT，但必须校验链路身份，防止替他用户记账。
        if str(payload.user_id) != caller_user_id:
            raise BizException(1001, "缺少或伪造的链路身份")

        existing = self.records.find_by_request_id(db, payload.request_id)
        if existing is not None:
            return self._replay(db, existing, payload)

        record = CallRecord(
            request_id=payload.request_id,
            user_id=payload.user_id,
            capability_id=payload.capability_id,
            service_name=payload.service_name,
            cost=payload.points,
            call_status=payload.status.value,
            duration_ms=payload.duration_ms,
            model_name=payload.model,
        )
        try:
            # 先占住幂等键：并发同 requestId 时，后到者会在此处阻塞并最终冲突。
            self.records.add(db, record)
        except IntegrityError:
            db.rollback()
            existing = self.records.find_by_request_id(db, payload.request_id)
            if existing is None:
                logger.error("记账幂等冲突但未找到明细 request_id={}", payload.request_id)
                raise BizException(4003, "系统内部错误") from None
            return self._replay(db, existing, payload)

        balance_after = await self._settle_charge(db, payload)

        stat_date = date.today()
        self.usage.upsert_daily(
            db,
            stat_date=stat_date,
            user_id=payload.user_id,
            capability_id=payload.capability_id,
            call_count=1,
            total_cost=payload.points,
        )
        db.commit()
        logger.info(
            "调用已记账 request_id={} user_id={} cost={} balance_after={}",
            payload.request_id,
            payload.user_id,
            payload.points,
            balance_after,
        )
        return self._result(db, record, stat_date=stat_date, balance_after=balance_after)

    async def _settle_charge(self, db: Session, payload: BillingRecordRequest) -> int | None:
        """结算本次调用的费用，返回扣分后的余额（免费能力返回 None）。

        - `points > 0`：调用 user-service 扣分，对方同时完成账号状态与余额校验；
        - `points = 0`：免费能力不产生扣分请求（对方要求 `amount >= 1`），
          因此这里单独调 user-service 校验账号状态，避免禁用账号经免费能力绕过状态校验。

        任何异常都先回滚本地事务，确保明细与日用量都不落库。
        """

        try:
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
        except Exception:
            # 含积分不足 3001、用户异常 1005、下游不可用 4002：一律不留半成功状态。
            db.rollback()
            raise

        if not isinstance(deduct, dict):
            db.rollback()
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
            page=page,
            page_size=page_size,
        )
        return [CallRecordOut.model_validate(row) for row in rows], total

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
            and existing.call_status == payload.status.value
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
            call_status=record.call_status,
            duplicated=duplicated,
            balance_after=balance_after,
            stat_date=stat_date,
            call_count=usage.call_count if usage is not None else 0,
            total_cost=usage.total_cost if usage is not None else 0,
        )

    @staticmethod
    def _daily_out(row: tuple[date, int, int]) -> UsageDailyOut:
        return UsageDailyOut(stat_date=row[0], call_count=row[1], total_cost=row[2])

    @staticmethod
    def _service_out(row: tuple[str, int, int]) -> ServiceUsageOut:
        return ServiceUsageOut(service_name=row[0], call_count=row[1], total_cost=row[2])


billing_service = BillingService()
