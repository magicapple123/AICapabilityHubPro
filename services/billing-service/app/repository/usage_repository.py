"""按天用量聚合表的数据访问；只访问 billing_db。

累加必须由数据库原子完成：使用 MySQL 的
`INSERT ... ON DUPLICATE KEY UPDATE call_count = call_count + n`
而不是“先查到旧值、内存相加、再写回”，后者在并发下会丢失更新。
`uk_usage_daily (stat_date, user_id, capability_id)` 是这一写法的前提。
"""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session

from app.models import UsageDaily


class UsageRepository:
    """`t_usage_daily` 的读写；本表只累加、不软删除。"""

    def upsert_daily(
        self,
        db: Session,
        *,
        stat_date: date,
        user_id: int,
        capability_id: int,
        call_count: int,
        total_cost: int,
    ) -> None:
        """原子累加当日用量；同日同用户同能力重复调用只更新一行。"""

        statement = mysql_insert(UsageDaily).values(
            stat_date=stat_date,
            user_id=user_id,
            capability_id=capability_id,
            call_count=call_count,
            total_cost=total_cost,
            is_deleted=0,
        )
        statement = statement.on_duplicate_key_update(
            call_count=UsageDaily.call_count + call_count,
            total_cost=UsageDaily.total_cost + total_cost,
        )
        db.execute(statement)

    def find_daily(
        self, db: Session, *, stat_date: date, user_id: int, capability_id: int
    ) -> UsageDaily | None:
        statement = select(UsageDaily).where(
            UsageDaily.stat_date == stat_date,
            UsageDaily.user_id == user_id,
            UsageDaily.capability_id == capability_id,
        )
        return db.scalar(statement)

    def sum_by_day(
        self,
        db: Session,
        *,
        start_date: date,
        end_date: date,
        user_id: int | None = None,
    ) -> list[tuple[date, int, int]]:
        """按天聚合：返回 (stat_date, call_count, total_cost)，按日期升序。"""

        conditions: list[object] = [
            UsageDaily.is_deleted == 0,
            UsageDaily.stat_date >= start_date,
            UsageDaily.stat_date <= end_date,
        ]
        if user_id is not None:
            conditions.append(UsageDaily.user_id == user_id)

        statement = (
            select(
                UsageDaily.stat_date,
                func.coalesce(func.sum(UsageDaily.call_count), 0),
                func.coalesce(func.sum(UsageDaily.total_cost), 0),
            )
            .where(*conditions)
            .group_by(UsageDaily.stat_date)
            .order_by(UsageDaily.stat_date)
        )
        return [
            (row[0], int(row[1] or 0), int(row[2] or 0))
            for row in db.execute(statement).all()
        ]

    def sum_by_user(
        self, db: Session, *, start_date: date, end_date: date
    ) -> list[tuple[int, int, int, date | None]]:
        """全量用户聚合（P5）：(user_id, call_count, total_cost, 最近用量日期)。

        数据源是 `t_usage_daily`：它按 `(stat_date, user_id, capability_id)` 累加，
        一张表就能给出"这个人近 N 天调了多少次、花了多少"，不需要扫明细表。
        `last_stat_date` 只能到天粒度——聚合表本来就只有天，不伪造分钟精度。
        """

        statement = (
            select(
                UsageDaily.user_id,
                func.coalesce(func.sum(UsageDaily.call_count), 0),
                func.coalesce(func.sum(UsageDaily.total_cost), 0),
                func.max(UsageDaily.stat_date),
            )
            .where(
                UsageDaily.is_deleted == 0,
                UsageDaily.stat_date >= start_date,
                UsageDaily.stat_date <= end_date,
            )
            .group_by(UsageDaily.user_id)
            .order_by(func.coalesce(func.sum(UsageDaily.total_cost), 0).desc(),
                      UsageDaily.user_id)
        )
        return [
            (int(row[0]), int(row[1] or 0), int(row[2] or 0), row[3])
            for row in db.execute(statement).all()
        ]


usage_repository = UsageRepository()
