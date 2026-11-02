"""供应商数据访问；只访问 ai_chat_db。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.provider import ModelProvider


class ProviderRepository:
    def find_by_alias(self, db: Session, alias: str) -> ModelProvider | None:
        return db.scalar(
            select(ModelProvider).where(
                ModelProvider.alias == alias, ModelProvider.is_deleted == 0
            )
        )

    def find_by_id(self, db: Session, provider_id: int) -> ModelProvider | None:
        return db.scalar(
            select(ModelProvider).where(
                ModelProvider.id == provider_id, ModelProvider.is_deleted == 0
            )
        )

    def list_all(self, db: Session) -> list[ModelProvider]:
        return list(
            db.scalars(
                select(ModelProvider)
                .where(ModelProvider.is_deleted == 0)
                .order_by(ModelProvider.id)
            ).all()
        )

    def create(self, db: Session, provider: ModelProvider) -> ModelProvider:
        db.add(provider)
        db.commit()
        db.refresh(provider)
        return provider

    def update_fields(
        self, db: Session, provider: ModelProvider, values: dict[str, object]
    ) -> ModelProvider:
        for field, value in values.items():
            setattr(provider, field, value)
        db.commit()
        db.refresh(provider)
        return provider


provider_repository = ProviderRepository()
