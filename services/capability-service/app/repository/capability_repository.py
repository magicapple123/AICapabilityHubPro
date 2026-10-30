"""能力表数据访问；只访问 capability_db，禁止跨库查询。

市场查询按接口契约第 4 节执行"最小暴露 + 严格过滤"：
只返回 `status='online'`、`is_deleted=0`，且所属分类也未软删除的条目。
分类名通过显式 join 取得，而不是 ORM 关系映射，以便一起过滤分类的 is_deleted。
"""

from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app.core.constants import CapabilityStatus
from app.models import Capability, CapabilityCategory

CapabilityRow = tuple[Capability, str]


class CapabilityRepository:
    """能力表的读写。所有查询默认过滤 is_deleted=0。"""

    @staticmethod
    def _market_conditions(
        *, category_id: int | None = None, keyword: str | None = None
    ) -> list[object]:
        conditions: list[object] = [
            Capability.is_deleted == 0,
            Capability.status == CapabilityStatus.ONLINE.value,
            CapabilityCategory.is_deleted == 0,
        ]
        if category_id is not None:
            conditions.append(Capability.category_id == category_id)
        if keyword:
            like = f"%{keyword}%"
            conditions.append(
                or_(Capability.name.like(like), Capability.description.like(like))
            )
        return conditions

    @staticmethod
    def _manage_conditions(
        *,
        status: str | None = None,
        category_id: int | None = None,
        keyword: str | None = None,
    ) -> list[object]:
        conditions: list[object] = [
            Capability.is_deleted == 0,
            CapabilityCategory.is_deleted == 0,
        ]
        if status is not None:
            conditions.append(Capability.status == status)
        if category_id is not None:
            conditions.append(Capability.category_id == category_id)
        if keyword:
            like = f"%{keyword}%"
            conditions.append(
                or_(
                    Capability.name.like(like),
                    Capability.code.like(like),
                    Capability.description.like(like),
                )
            )
        return conditions

    def _paginate(
        self, db: Session, conditions: list[object], *, page: int, page_size: int
    ) -> tuple[list[CapabilityRow], int]:
        joined = select(Capability, CapabilityCategory.name).join(
            CapabilityCategory, CapabilityCategory.id == Capability.category_id
        )
        counted = (
            select(func.count(Capability.id))
            .select_from(Capability)
            .join(CapabilityCategory, CapabilityCategory.id == Capability.category_id)
        )

        total = db.scalar(counted.where(*conditions)) or 0
        rows = db.execute(
            joined.where(*conditions)
            .order_by(desc(Capability.update_time), desc(Capability.id))
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return [(row[0], row[1]) for row in rows], total

    def list_market(
        self,
        db: Session,
        *,
        category_id: int | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> tuple[list[CapabilityRow], int]:
        """公开市场列表：只返回已上架且分类未被软删除的能力。"""

        conditions = self._market_conditions(category_id=category_id, keyword=keyword)
        return self._paginate(db, conditions, page=page, page_size=page_size)

    def list_manage(
        self,
        db: Session,
        *,
        status: str | None = None,
        category_id: int | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> tuple[list[CapabilityRow], int]:
        """运营列表：返回全部状态（draft / online / offline）。"""

        conditions = self._manage_conditions(
            status=status, category_id=category_id, keyword=keyword
        )
        return self._paginate(db, conditions, page=page, page_size=page_size)

    def find_market_by_id(self, db: Session, capability_id: int) -> CapabilityRow | None:
        """市场详情：未上架或已软删除的能力一律返回 None，不暴露存在性。"""

        conditions = [
            Capability.id == capability_id,
            *self._market_conditions(),
        ]
        statement = (
            select(Capability, CapabilityCategory.name)
            .join(CapabilityCategory, CapabilityCategory.id == Capability.category_id)
            .where(*conditions)
        )
        row = db.execute(statement).first()
        return (row[0], row[1]) if row is not None else None

    def find_by_id(self, db: Session, capability_id: int) -> Capability | None:
        """按 ID 取未删除能力（不限制状态），用于编辑与上下架。"""

        statement = select(Capability).where(
            Capability.id == capability_id,
            Capability.is_deleted == 0,
        )
        return db.scalar(statement)

    def exists_code(
        self, db: Session, code: str, *, exclude_id: int | None = None
    ) -> bool:
        """未删除范围内能力编码是否已存在；exclude_id 用于编辑时排除自身。"""

        conditions = [Capability.code == code, Capability.is_deleted == 0]
        if exclude_id is not None:
            conditions.append(Capability.id != exclude_id)
        return bool(db.scalar(select(func.count(Capability.id)).where(*conditions)))

    def count_by_category(self, db: Session, category_id: int) -> int:
        """统计分类下未删除的能力数，供删除分类前的引用检查使用。"""

        return (
            db.scalar(
                select(func.count(Capability.id)).where(
                    Capability.category_id == category_id,
                    Capability.is_deleted == 0,
                )
            )
            or 0
        )

    def list_online_category_ids(self, db: Session) -> list[int]:
        """存在已上架能力的分类 ID，供市场分类筛选栏使用。"""

        statement = (
            select(Capability.category_id)
            .join(CapabilityCategory, CapabilityCategory.id == Capability.category_id)
            .where(
                Capability.is_deleted == 0,
                Capability.status == CapabilityStatus.ONLINE.value,
                CapabilityCategory.is_deleted == 0,
            )
            .distinct()
        )
        return list(db.scalars(statement).all())

    def create(self, db: Session, capability: Capability) -> Capability:
        db.add(capability)
        db.commit()
        db.refresh(capability)
        return capability

    def update_fields(
        self, db: Session, capability: Capability, values: dict[str, object]
    ) -> Capability:
        """按字段名更新；values 应为 model_dump(exclude_unset=True) 的结果。"""

        for field, value in values.items():
            setattr(capability, field, value)
        db.commit()
        db.refresh(capability)
        return capability

    def soft_delete(self, db: Session, capability: Capability) -> None:
        capability.is_deleted = 1
        db.commit()


capability_repository = CapabilityRepository()
