"""运营操作审计表（B1）。

只追加：应用层不提供更新与删除接口，repository 也没有 update/delete 方法。
一库一张同构表：user-service 在批 5 建同名字段结构。
"""

from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class OperationLog(Base):
    """一次运营写操作的留痕；`before_json`/`after_json` 已脱敏。"""

    __tablename__ = "t_operation_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    operator_id: Mapped[str] = mapped_column(String(64), nullable=False)
    operator_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # 用字符串承载，既兼容自增 id，也兼容 `code` 这类业务键。
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    before_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    create_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    is_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
