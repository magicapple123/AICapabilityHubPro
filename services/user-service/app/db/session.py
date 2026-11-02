from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


# 创建引擎不会立即连接数据库，首次执行 SQL 时才建立连接。
# 池参数全部来自环境变量（A2）：默认 5 + 10 溢出与改造前一致，
# 只是不再写死，便于按 worker 数调整。容量口径见 `docs/api-contract/pro-shared.md`。
engine = create_engine(
    settings.db_url,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
)
SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
