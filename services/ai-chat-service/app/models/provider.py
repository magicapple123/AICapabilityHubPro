"""上游供应商（D1）。

建在 `ai_chat_db`：**Key 不跨服务传**。能力表只存 `provider_alias` 字符串，
跨库不建外键（capability_db 与 ai_chat_db 独立）。

`api_key_cipher` 为 `v1:nonce:cipher`，解密只发生在 ai-chat 内存；
对外只暴露 `api_key_mask`。
"""

from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

# 状态机：draft（可存不可用）→ enabled（测通后才允许）→ disabled。
PROVIDER_DRAFT = "draft"
PROVIDER_ENABLED = "enabled"
PROVIDER_DISABLED = "disabled"


class ModelProvider(Base):
    __tablename__ = "t_model_provider"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    alias: Mapped[str] = mapped_column(String(64), nullable=False)
    protocol: Mapped[str] = mapped_column(String(32), nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    api_key_cipher: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_mask: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    default_model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=30000)
    extra_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=PROVIDER_DRAFT, server_default=PROVIDER_DRAFT
    )
    # 记录最后一次连通性测试通过的时间；"启用"前必须非空（D1 冻结规则）。
    last_test_ok_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    create_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    update_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
    is_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
