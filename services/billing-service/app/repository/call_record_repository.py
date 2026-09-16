"""调用明细数据访问；只访问 billing_db，禁止跨库查询。

事务边界约定：本层**不提交事务**，只做 `add + flush`，由 service 层决定
commit / rollback。原因：一次记账包含“写明细 → 调 user 扣分 → 累计日用量”
三步，必须整体成功或整体回滚，不能出现“明细写了但没扣分”的半成功状态。
"""

from datetime import date, datetime, time, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.constants import CallStatus
from app.models import CallRecord


def time_conditions(start_date: date, end_date: date) -> list[object]:
    """把日期区间转成索引友好的时间区间条件：`[start 00:00:00, end+1天 00:00:00)`。

    不使用 `DATE(create_time) = ?`，避免函数作用在列上导致索引失效。
    """

    start_dt = datetime.combine(start_date, time.min)
    end_dt = datetime.combine(end_date + timedelta(days=1), time.min)
    return [CallRecord.create_time >= start_dt, CallRecord.create_time < end_dt]


class CallRecordRepository:
    """`t_call_record` 的读写；所有查询默认过滤 `is_deleted=0`。"""

    def find_by_request_id(self, db: Session, request_id: str) -> CallRecord | None:
        """按幂等键取明细；`(request_id, is_deleted)` 唯一索引保证最多一条。"""

        statement = select(CallRecord).where(
            CallRecord.request_id == request_id, CallRecord.is_deleted == 0
        )
        return db.scalar(statement)

    def add(self, db: Session, record: CallRecord) -> CallRecord:
        """插入明细并 flush 拿到主键；重复 requestId 会抛 IntegrityError。"""

        db.add(record)
        db.flush()
        return record

    def list_by_user(
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
    ) -> tuple[list[CallRecord], int]:
        """分页查询某用户的调用明细，按时间倒序。"""

        conditions: list[object] = [
            CallRecord.user_id == user_id,
            CallRecord.is_deleted == 0,
            *time_conditions(start_date, end_date),
        ]
        if service_name:
            conditions.append(CallRecord.service_name == service_name)
        if call_status:
            conditions.append(CallRecord.call_status == call_status)

        total = db.scalar(select(func.count(CallRecord.id)).where(*conditions)) or 0
        statement = (
            select(CallRecord)
            .where(*conditions)
            .order_by(CallRecord.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(db.scalars(statement).all()), total

    def summary(
        self,
        db: Session,
        *,
        start_date: date,
        end_date: date,
        user_id: int | None = None,
    ) -> dict[str, int]:
        """汇总调用次数、消耗积分、状态分布与去重用户数（user_id 为空则统计全局）。"""

        conditions: list[object] = [
            CallRecord.is_deleted == 0,
            *time_conditions(start_date, end_date),
        ]
        if user_id is not None:
            conditions.append(CallRecord.user_id == user_id)

        row = db.execute(
            select(
                func.count(CallRecord.id),
                func.coalesce(func.sum(CallRecord.cost), 0),
                func.coalesce(
                    func.sum(case((CallRecord.call_status == CallStatus.SUCCESS.value, 1), else_=0)),
                    0,
                ),
                func.coalesce(
                    func.sum(case((CallRecord.call_status == CallStatus.DEGRADED.value, 1), else_=0)),
                    0,
                ),
                func.coalesce(
                    func.sum(case((CallRecord.call_status == CallStatus.FAILED.value, 1), else_=0)),
                    0,
                ),
                func.count(func.distinct(CallRecord.user_id)),
            ).where(*conditions)
        ).one()

        return {
            "call_count": int(row[0] or 0),
            "total_cost": int(row[1] or 0),
            "success_count": int(row[2] or 0),
            "degraded_count": int(row[3] or 0),
            "failed_count": int(row[4] or 0),
            "user_count": int(row[5] or 0),
        }

    def group_by_service(
        self,
        db: Session,
        *,
        start_date: date,
        end_date: date,
        user_id: int | None = None,
    ) -> list[tuple[str, int, int]]:
        """按承载服务聚合：返回 (service_name, call_count, total_cost)。"""

        conditions: list[object] = [
            CallRecord.is_deleted == 0,
            *time_conditions(start_date, end_date),
        ]
        if user_id is not None:
            conditions.append(CallRecord.user_id == user_id)

        statement = (
            select(
                CallRecord.service_name,
                func.count(CallRecord.id),
                func.coalesce(func.sum(CallRecord.cost), 0),
            )
            .where(*conditions)
            .group_by(CallRecord.service_name)
            .order_by(func.count(CallRecord.id).desc(), CallRecord.service_name)
        )
        return [
            (row[0] or "", int(row[1] or 0), int(row[2] or 0))
            for row in db.execute(statement).all()
        ]

    def top_users(
        self, db: Session, *, start_date: date, end_date: date, limit: int = 10
    ) -> list[tuple[int, int, int]]:
        """按消耗积分为用户排行：返回 (user_id, call_count, total_cost)。"""

        statement = (
            select(
                CallRecord.user_id,
                func.count(CallRecord.id),
                func.coalesce(func.sum(CallRecord.cost), 0),
            )
            .where(CallRecord.is_deleted == 0, *time_conditions(start_date, end_date))
            .group_by(CallRecord.user_id)
            .order_by(func.coalesce(func.sum(CallRecord.cost), 0).desc(), CallRecord.user_id)
            .limit(limit)
        )
        return [
            (int(row[0]), int(row[1] or 0), int(row[2] or 0))
            for row in db.execute(statement).all()
        ]


call_record_repository = CallRecordRepository()
