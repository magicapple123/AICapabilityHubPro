"""user_db 的 SQLAlchemy 模型；只访问本服务的库，禁止跨库查询。

对应开发指南附录 B 的四张表：
`t_user`、`t_api_key`、`t_points_account`、`t_points_log`。

唯一性约定与 capability-service 保持同一风格：
用户名、access_key 用 `(列, is_deleted)` 组合唯一索引实现“未删除范围内唯一”；
积分流水用 `(request_id, is_deleted)` 组合唯一索引实现**扣分幂等**——
同一 requestId 只能写入一条流水，重复上报不会二次扣分。
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import ApiKeyStatus, PointDirection, UserStatus
from app.db.session import Base


class User(Base):
    """用户账号。`password_hash` 为 PBKDF2 自描述哈希串，任何接口都不回传。"""

    __tablename__ = "t_user"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(32), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="user", server_default="user")
    nickname: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=UserStatus.NORMAL.value
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


class ApiKey(Base):
    """开发者 API Key。

    安全约束：
    - `secret_key` 只在创建时返回一次，库里存储 `secret_hash`（SHA-256 十六进制）
      而不是明文，`secret_mask` 仅用于列表展示；
    - `access_key` 可对外展示，不包含任何密钥信息。
    """

    __tablename__ = "t_api_key"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    access_key: Mapped[str] = mapped_column(String(64), nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    secret_mask: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ApiKeyStatus.ENABLED.value
    )
    expire_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
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


class PointsAccount(Base):
    """积分账户，一个用户一条。

    扣分不使用“先查余额再更新”的做法，而是走条件更新
    `UPDATE ... SET balance = balance - :cost WHERE user_id = :uid AND balance >= :cost`，
    以影响行数判断是否扣减成功，从数据库层防止并发超扣（指南 5.5）。
    `version` 记录该账户被扣减/增加的次数，便于排查与对账。
    """

    __tablename__ = "t_points_account"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    balance: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    frozen: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
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


class PointsLog(Base):
    """积分流水。`request_id` 是幂等键，同一值只会落一条记录。"""

    __tablename__ = "t_points_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    direction: Mapped[str] = mapped_column(
        String(8), nullable=False, default=PointDirection.IN.value
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    biz_type: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    remark: Mapped[str] = mapped_column(String(255), nullable=False, default="")
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
