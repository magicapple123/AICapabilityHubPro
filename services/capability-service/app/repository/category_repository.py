"""分类表数据访问；只访问 capability_db，禁止跨库查询。

写入方法内部提交事务：本服务的写操作都是单表原子操作，把事务边界放在
repository 可以让 service 层不直接接触 SQLAlchemy 的会话细节。
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CapabilityCategory


class CategoryRepository:
    """分类表的读写。所有查询默认过滤 is_deleted=0。"""

    def list_all(
        self,
        db: Session,
        *,
        status: str | None = None,
        keyword: str | None = None,
    ) -> list[CapabilityCategory]:
        """列出全部未删除分类，按 sort、id 升序；分类数量少，不分页。"""

        conditions = [CapabilityCategory.is_deleted == 0]
        if status is not None:
            conditions.append(CapabilityCategory.status == status)
        if keyword:
            conditions.append(CapabilityCategory.name.like(f"%{keyword}%"))

        statement = (
            select(CapabilityCategory)
            .where(*conditions)
            .order_by(CapabilityCategory.sort, CapabilityCategory.id)
        )
        return list(db.scalars(statement).all())

    def list_by_ids(self, db: Session, category_ids: list[int]) -> list[CapabilityCategory]:
        """按 ID 批量取未删除分类，用于市场分类筛选栏。"""

        if not category_ids:
            return []
        statement = (
            select(CapabilityCategory)
            .where(
                CapabilityCategory.id.in_(category_ids),
                CapabilityCategory.is_deleted == 0,
            )
            .order_by(CapabilityCategory.sort, CapabilityCategory.id)
        )
        return list(db.scalars(statement).all())

    def find_by_id(self, db: Session, category_id: int) -> CapabilityCategory | None:
        """按 ID 取未删除分类；不存在或已软删除返回 None。"""

        statement = select(CapabilityCategory).where(
            CapabilityCategory.id == category_id,
            CapabilityCategory.is_deleted == 0,
        )
        return db.scalar(statement)

    def exists_name(
        self, db: Session, name: str, *, exclude_id: int | None = None
    ) -> bool:
        """未删除范围内名称是否已存在；exclude_id 用于编辑时排除自身。"""

        conditions = [
            CapabilityCategory.name == name,
            CapabilityCategory.is_deleted == 0,
        ]
        if exclude_id is not None:
            conditions.append(CapabilityCategory.id != exclude_id)
        return bool(db.scalar(select(func.count(CapabilityCategory.id)).where(*conditions)))

    def exists_code(
        self, db: Session, code: str, *, exclude_id: int | None = None
    ) -> bool:
        """未删除范围内编码是否已存在；exclude_id 用于编辑时排除自身。"""

        conditions = [
            CapabilityCategory.code == code,
            CapabilityCategory.is_deleted == 0,
        ]
        if exclude_id is not None:
            conditions.append(CapabilityCategory.id != exclude_id)
        return bool(db.scalar(select(func.count(CapabilityCategory.id)).where(*conditions)))

    def create(self, db: Session, category: CapabilityCategory) -> CapabilityCategory:
        db.add(category)
        db.commit()
        db.refresh(category)
        return category

    def update_fields(
        self, db: Session, category: CapabilityCategory, values: dict[str, object]
    ) -> CapabilityCategory:
        """按字段名更新；values 应为 model_dump(exclude_unset=True) 的结果。"""

        for field, value in values.items():
            setattr(category, field, value)
        db.commit()
        db.refresh(category)
        return category

    def soft_delete(self, db: Session, category: CapabilityCategory) -> None:
        """软删除；唯一索引按 (列, is_deleted) 组合，因此这里只置标记位。"""

        category.is_deleted = 1
        db.commit()


category_repository = CategoryRepository()
