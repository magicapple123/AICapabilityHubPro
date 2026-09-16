"""积分账户与积分流水数据访问；只访问 user_db。

并发安全的关键在 `try_deduct`：
不使用“先查余额、再判断、最后更新”的读改写流程，而是执行条件更新
`UPDATE t_points_account SET balance = balance - :cost WHERE user_id = :uid AND balance >= :cost`，
由数据库保证“余额永远不为负”，再以影响行数判断是否扣减成功（指南 5.5）。
"""

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import PointsAccount, PointsLog


class PointsRepository:
    """`t_points_account` 与 `t_points_log` 的读写。"""

    # ------------------------------------------------------------ 账户

    def find_account(self, db: Session, user_id: int) -> PointsAccount | None:
        statement = select(PointsAccount).where(
            PointsAccount.user_id == user_id, PointsAccount.is_deleted == 0
        )
        return db.scalar(statement)

    def add_account(self, db: Session, account: PointsAccount) -> PointsAccount:
        db.add(account)
        db.flush()
        return account

    def try_deduct(self, db: Session, user_id: int, amount: int) -> int:
        """条件更新式扣分；返回影响行数（0 表示余额不足或账户不存在）。"""

        statement = (
            update(PointsAccount)
            .where(
                PointsAccount.user_id == user_id,
                PointsAccount.is_deleted == 0,
                PointsAccount.balance >= amount,
            )
            .values(
                balance=PointsAccount.balance - amount,
                version=PointsAccount.version + 1,
            )
            .execution_options(synchronize_session=False)
        )
        return db.execute(statement).rowcount

    def read_balance(self, db: Session, user_id: int) -> int | None:
        """读取最新余额；账户不存在返回 None。"""

        statement = select(PointsAccount.balance).where(
            PointsAccount.user_id == user_id, PointsAccount.is_deleted == 0
        )
        return db.scalar(statement)

    def add_income(self, db: Session, user_id: int, amount: int) -> int:
        """增加积分（注册赠送）；返回影响行数。"""

        statement = (
            update(PointsAccount)
            .where(PointsAccount.user_id == user_id, PointsAccount.is_deleted == 0)
            .values(
                balance=PointsAccount.balance + amount,
                version=PointsAccount.version + 1,
            )
            .execution_options(synchronize_session=False)
        )
        return db.execute(statement).rowcount

    # ------------------------------------------------------------ 流水

    def find_log_by_request_id(self, db: Session, request_id: str) -> PointsLog | None:
        """按幂等键取流水；(request_id, is_deleted) 唯一索引保证最多一条。"""

        statement = select(PointsLog).where(
            PointsLog.request_id == request_id, PointsLog.is_deleted == 0
        )
        return db.scalar(statement)

    def add_log(self, db: Session, log: PointsLog) -> PointsLog:
        """插入流水并 flush；重复 requestId 会抛 IntegrityError，由 service 兜底。"""

        db.add(log)
        db.flush()
        return log

    def list_logs(
        self,
        db: Session,
        user_id: int,
        *,
        direction: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> tuple[list[PointsLog], int]:
        """分页查询当前用户流水，按时间倒序。"""

        conditions = [PointsLog.user_id == user_id, PointsLog.is_deleted == 0]
        if direction is not None:
            conditions.append(PointsLog.direction == direction)

        total = db.scalar(select(func.count(PointsLog.id)).where(*conditions)) or 0
        statement = (
            select(PointsLog)
            .where(*conditions)
            .order_by(PointsLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(db.scalars(statement).all()), total


points_repository = PointsRepository()
