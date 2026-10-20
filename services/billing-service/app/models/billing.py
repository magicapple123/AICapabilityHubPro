"""billing_db 的 SQLAlchemy 模型；只访问本服务的库，禁止跨库查询。

对应开发指南附录 B 的两张表：

- `t_call_record`：调用明细，`request_id` 是**幂等键**，用
  `(request_id, is_deleted)` 组合唯一索引在数据库层保证“同一 ID 只记一次”；
- `t_usage_daily`：按天 + 用户 + 能力聚合的用量，用
  `(stat_date, user_id, capability_id)` 联合唯一索引支撑 UPSERT 累加。

不保存 user-service 的用户名等資料，需要时走 `/internal` 接口，避免跨库冗余。
"""

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import CallStatus, DEFAULT_CAPABILITY_ID
from app.db.session import Base


class CallRecord(Base):
    """调用明细。`request_id` 唯一，重复上报通过幂等校验后不会重复扣分。"""

    __tablename__ = "t_call_record"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    capability_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=DEFAULT_CAPABILITY_ID
    )
    service_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    unit_price: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cost: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    call_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=CallStatus.SUCCESS.value
    )
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    create_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    update_time: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
    is_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)


class UsageDaily(Base):
    """按天聚合的用量。

    只做累加、不做软删除：`(stat_date, user_id, capability_id)` 联合唯一，
    写入走 `INSERT ... ON DUPLICATE KEY UPDATE call_count = call_count + n`，
    由数据库完成原子累加，避免“先查后写”的丢失更新。
    """

    __tablename__ = "t_usage_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    capability_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=DEFAULT_CAPABILITY_ID
    )
    call_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_cost: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    create_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    update_time: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
    is_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
