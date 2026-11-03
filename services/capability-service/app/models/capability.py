from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Computed,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import BillingMode, CapabilityStatus, CategoryStatus
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
    openai_alias: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, default=None
    )
    service_name: Mapped[str] = mapped_column(String(64), nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    param_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    price_per_call: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # C2 双轨计费：旧能力全部是 per_call，price_per_call 语义与金额不变。
    billing_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default=BillingMode.PER_CALL.value,
        server_default=BillingMode.PER_CALL.value,
    )
    price_per_1k_input: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    price_per_1k_output: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    price_per_unit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    unit: Mapped[str] = mapped_column(
        String(16), nullable=False, default="", server_default=""
    )
    # D2：执行器与供应商别名。code 不再兼任"执行器选择"。
    executor: Mapped[str] = mapped_column(
        String(32), nullable=False, default="", server_default=""
    )
    provider_alias: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", server_default=""
    )
    # D4：单次输出 token 上限，实际请求取 min(请求值, 本值)。
    max_output_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1024, server_default="1024"
    )
    # E4：是否在市场展示。默认 1，保证历史能力行为不变；
    # 与 status 是两个维度：status=online 表示可执行，exposed=1 表示愿意被看见。
    exposed_to_market: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
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
    # D5：数据库生成列（STORED），未删除时等于 code，已删除时为 NULL。
    # 唯一约束建在它上面，于是"同一 code 可以软删任意多次再重建"，而未删除范围内
    # code 仍唯一（MySQL 唯一索引允许多行 NULL）。值由数据库计算，应用永不写它。
    active_code: Mapped[str | None] = mapped_column(
        String(64),
        Computed("IF(is_deleted = 0, code, NULL)", persisted=True),
        nullable=True,
        comment="生成列：未删除时等于 code，已删除时为 NULL（D5）",
    )
