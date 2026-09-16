"""API Key 表数据访问；只访问 user_db。

按用户维度隔离：`find_owned` 同时按 `id` 与 `user_id` 过滤，
因此访问他人 API Key 与访问不存在的 ID 返回同一个结果（1006），不泄露存在性。
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ApiKey


class ApiKeyRepository:
    """`t_api_key` 的读写；所有查询默认过滤 `is_deleted=0`。"""

    def list_by_user(self, db: Session, user_id: int) -> list[ApiKey]:
        statement = (
            select(ApiKey)
            .where(ApiKey.user_id == user_id, ApiKey.is_deleted == 0)
            .order_by(ApiKey.id.desc())
        )
        return list(db.scalars(statement).all())

    def find_owned(self, db: Session, api_key_id: int, user_id: int) -> ApiKey | None:
        """取当前用户名下的 Key；他人 Key 与不存在的 Key 同样返回 None。"""

        statement = select(ApiKey).where(
            ApiKey.id == api_key_id,
            ApiKey.user_id == user_id,
            ApiKey.is_deleted == 0,
        )
        return db.scalar(statement)

    def exists_access_key(self, db: Session, access_key: str) -> bool:
        statement = select(func.count(ApiKey.id)).where(
            ApiKey.access_key == access_key, ApiKey.is_deleted == 0
        )
        return bool(db.scalar(statement))

    def add(self, db: Session, api_key: ApiKey) -> ApiKey:
        db.add(api_key)
        db.flush()
        return api_key

    def update_fields(self, db: Session, api_key: ApiKey, values: dict[str, object]) -> ApiKey:
        for field, value in values.items():
            setattr(api_key, field, value)
        db.flush()
        return api_key


api_key_repository = ApiKeyRepository()
