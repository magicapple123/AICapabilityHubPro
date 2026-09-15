from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import CapabilityStatus, CategoryStatus
from app.db.session import Base


class CapabilityCategory(Base):
    """能力分类。

    未删除范围内 `name` 与 `code` 唯一；唯一性由两个 `(列, is_deleted)` 唯一索引
    在数据库层兜底，业务层在 repository 中另做一次查重以返回 2004。
    """

    __tablename__ = "t_capability_category"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=CategoryStatus.ENABLED.value
    )
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


class Capability(Base):
    """能力目录条目。

    只保存登记元数据，`param_schema` 为 JSON 对象。市场接口只对外暴露 `online`
    且未软删除的条目，`service_name` / `path` / `param_schema` 属内部配置，
    不得出现在市场列表中。
    """

    __tablename__ = "t_capability"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("t_capability_category.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    service_name: Mapped[str] = mapped_column(String(64), nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    param_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    price_per_call: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=CapabilityStatus.DRAFT.value
    )
    description: Mapped[str] = mapped_column(String(512), nullable=False, default="")
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
