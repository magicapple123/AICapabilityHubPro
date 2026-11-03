"""能力表数据访问；只访问 capability_db，禁止跨库查询。

市场查询按接口契约第 4 节执行"最小暴露 + 严格过滤"：
只返回 `status='online'`、`is_deleted=0`，且所属分类也未软删除的条目。
分类名通过显式 join 取得，而不是 ORM 关系映射，以便一起过滤分类的 is_deleted。
"""

from sqlalchemy import desc, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.constants import CapabilityStatus, CategoryStatus
from app.models import Capability, CapabilityCategory, OperationLog

CapabilityRow = tuple[Capability, str]

#: MySQL 唯一键冲突的错误码。
MYSQL_DUPLICATE_ENTRY = 1062


class DuplicateCapabilityCodeError(RuntimeError):
    """未删除范围内 code 重复（撞上 `uk_capability_active_code`）。

    仓储层不认识业务错误码，只把数据库异常翻译成这个领域异常；
    由 service 层映射成对外业务码 2006，保持"编码重复 → 2006"的口径不变。
    """

    def __init__(self, code: str) -> None:
        super().__init__(f"capability code already exists: {code}")
        self.code = code


class DuplicateCapabilityOpenAIAliasError(RuntimeError):
    """An active capability already owns the OpenAI model alias."""


def _is_duplicate_entry(exc: IntegrityError) -> bool:
    """判断异常是否是 MySQL 1062（唯一键冲突）。"""

    original = getattr(exc, "orig", None)
    args = getattr(original, "args", ())
    return bool(args) and args[0] == MYSQL_DUPLICATE_ENTRY


def _duplicate_constraint(exc: IntegrityError) -> str:
    original = getattr(exc, "orig", None)
    args = getattr(original, "args", ())
    detail = str(args[1]) if len(args) > 1 else ""
    if "uk_capability_openai_alias" in detail:
        return "openai_alias"
    if "uk_capability_active_code" in detail:
        return "code"
    return ""


class CapabilityRepository:
    """能力表的读写。所有查询默认过滤 is_deleted=0。"""

    @staticmethod
    def _market_conditions(
        *, category_id: int | None = None, keyword: str | None = None
    ) -> list[object]:
        conditions: list[object] = [
            Capability.is_deleted == 0,
            Capability.status == CapabilityStatus.ONLINE.value,
            # E4：运营可把能力从市场隐藏，但保留 online 以继续被已授权调用方使用。
            Capability.exposed_to_market == 1,
            CapabilityCategory.is_deleted == 0,
            # D5：分类停用（status='disabled'）后，其下能力一并不再出现在市场。
            # 停用只影响"市场可见性"，不动能力的 status，也不影响已授权调用方的执行；
            # 运营列表（_manage_conditions）不看分类状态，仍能查到并恢复。
            CapabilityCategory.status == CategoryStatus.ENABLED.value,
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

    def list_openai_models(self, db: Session) -> list[tuple[int, str | None]]:
        """List online chat targets for dynamic aliases and legacy configured aliases."""

        statement = (
            select(Capability.id, Capability.openai_alias)
            .where(
                Capability.is_deleted == 0,
                Capability.status == CapabilityStatus.ONLINE.value,
                Capability.executor == "chat",
            )
            .order_by(Capability.openai_alias, Capability.id)
        )
        return [
            (int(capability_id), str(alias) if alias else None)
            for capability_id, alias in db.execute(statement)
        ]

    def list_published_models(self, db: Session) -> list[tuple[str, int, str]]:
        """P3：登录用户可见的对外模型名清单：(alias, capability_id, name)。

        只取 `status=online`、`executor=chat` 且填了对外模型名的能力——摘要/文生图
        放进去只会让用户"选了再报参数错"。这与 `/v1/models` 的过滤口径一致。
        """

        statement = (
            select(Capability.openai_alias, Capability.id, Capability.name)
            .where(
                Capability.is_deleted == 0,
                Capability.status == CapabilityStatus.ONLINE.value,
                Capability.executor == "chat",
                Capability.openai_alias.is_not(None),
            )
            .order_by(Capability.openai_alias, Capability.id)
        )
        return [
            (str(alias), int(capability_id), str(name))
            for alias, capability_id, name in db.execute(statement)
        ]

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

    def exists_openai_alias(
        self, db: Session, alias: str, *, exclude_id: int | None = None
    ) -> bool:
        conditions = [Capability.openai_alias == alias, Capability.is_deleted == 0]
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
        """存在"市场里真能看到的能力"的分类 ID，供市场分类筛选栏使用。

        条件与 `_market_conditions` 保持完全一致：否则会出现"筛选栏有分类、
        点进去却是空列表"的割裂（例如能力被 E4 隐藏、或分类被 D5 停用）。
        """

        statement = (
            select(Capability.category_id)
            .join(CapabilityCategory, CapabilityCategory.id == Capability.category_id)
            .where(
                Capability.is_deleted == 0,
                Capability.status == CapabilityStatus.ONLINE.value,
                Capability.exposed_to_market == 1,
                CapabilityCategory.is_deleted == 0,
                CapabilityCategory.status == CategoryStatus.ENABLED.value,
            )
            .distinct()
        )
        return list(db.scalars(statement).all())

    def create(
        self, db: Session, capability: Capability, *, audit: OperationLog | None = None
    ) -> Capability:
        db.add(capability)
        # 先 flush 拿到自增 id，审计行才能记录真实 resource_id；
        # 审计与业务写在同一个 commit 内，不会出现"改了没留痕"。
        # 并发下 service 的 exists_code 预检可能双双通过，最终仍由数据库唯一键兜底：
        # 1062 → DuplicateCapabilityCodeError，由 service 映射为 2006（不是 500）。
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            if _is_duplicate_entry(exc):
                if _duplicate_constraint(exc) == "openai_alias":
                    raise DuplicateCapabilityOpenAIAliasError() from exc
                raise DuplicateCapabilityCodeError(capability.code) from exc
            raise
        self._attach_audit(db, audit, capability.id)
        db.commit()
        db.refresh(capability)
        return capability

    def update_fields(
        self,
        db: Session,
        capability: Capability,
        values: dict[str, object],
        *,
        audit: OperationLog | None = None,
    ) -> Capability:
        """按字段名更新；values 应为 model_dump(exclude_unset=True) 的结果。"""

        for field, value in values.items():
            setattr(capability, field, value)
        self._attach_audit(db, audit, capability.id)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            if _is_duplicate_entry(exc):
                if _duplicate_constraint(exc) == "openai_alias":
                    raise DuplicateCapabilityOpenAIAliasError() from exc
                raise DuplicateCapabilityCodeError(str(values.get("code", capability.code))) from exc
            raise
        db.refresh(capability)
        return capability

    def soft_delete(
        self, db: Session, capability: Capability, *, audit: OperationLog | None = None
    ) -> None:
        capability.is_deleted = 1
        capability.openai_alias = None
        self._attach_audit(db, audit, capability.id)
        db.commit()

    @staticmethod
    def _attach_audit(
        db: Session, audit: OperationLog | None, resource_id: int
    ) -> None:
        """把审计行挂到当前事务；调用方未提供操作者时跳过（内部调用不留痕）。"""

        if audit is None:
            return
        audit.resource_id = str(resource_id)
        db.add(audit)


capability_repository = CapabilityRepository()
