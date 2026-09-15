"""能力业务逻辑。

关键约束：
- 登记与编辑前先校验分类是否存在（2003）与编码是否重复（2006）；
- 状态只能通过 `update_status` 变更，编辑接口不接收 status；
- 市场相关方法只返回已上架能力，未上架 / 已删除一律按 2002 处理，
  不向白名单接口暴露能力是否存在。
"""

from loguru import logger
from sqlalchemy.orm import Session

from app.core.constants import CapabilityStatus
from app.core.exceptions import BizException
from app.models import Capability, CapabilityCategory
from app.repository import CapabilityRepository, CategoryRepository
from app.repository import capability_repository, category_repository
from app.schemas import (
    CapabilityCreateRequest,
    CapabilityStatusUpdateRequest,
    CapabilityUpdateRequest,
)

CapabilityRow = tuple[Capability, str]


class CapabilityService:
    """能力的登记、编辑、上下架、软删除与市场查询。"""

    def __init__(
        self,
        capabilities: CapabilityRepository | None = None,
        categories: CategoryRepository | None = None,
    ) -> None:
        self.capabilities = capabilities or capability_repository
        self.categories = categories or category_repository

    def list_market(
        self,
        db: Session,
        *,
        category_id: int | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> tuple[list[CapabilityRow], int]:
        return self.capabilities.list_market(
            db, category_id=category_id, keyword=keyword, page=page, page_size=page_size
        )

    def get_market_detail(self, db: Session, capability_id: int) -> CapabilityRow:
        row = self.capabilities.find_market_by_id(db, capability_id)
        if row is None:
            raise BizException(2002, "能力不存在或已下线")
        return row

    def list_market_categories(self, db: Session) -> list[CapabilityCategory]:
        """只返回确实存在已上架能力的分类，供市场筛选栏使用。"""

        category_ids = self.capabilities.list_online_category_ids(db)
        return self.categories.list_by_ids(db, category_ids)

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
        return self.capabilities.list_manage(
            db,
            status=status,
            category_id=category_id,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )

    def create_capability(
        self, db: Session, payload: CapabilityCreateRequest
    ) -> Capability:
        self._require_category(db, payload.category_id)
        if self.capabilities.exists_code(db, payload.code):
            raise BizException(2006, "能力编码已存在")

        created = self.capabilities.create(
            db,
            Capability(
                category_id=payload.category_id,
                name=payload.name,
                code=payload.code,
                service_name=payload.service_name,
                path=payload.path,
                param_schema=payload.param_schema,
                price_per_call=payload.price_per_call,
                status=payload.status.value,
                description=payload.description,
            ),
        )
        logger.info("能力已登记 capability_id={} code={}", created.id, created.code)
        return created

    def update_capability(
        self, db: Session, capability_id: int, payload: CapabilityUpdateRequest
    ) -> Capability:
        capability = self.require_capability(db, capability_id)
        values = payload.model_dump(exclude_unset=True)

        if "category_id" in values:
            self._require_category(db, values["category_id"])
        if "code" in values and self.capabilities.exists_code(
            db, values["code"], exclude_id=capability_id
        ):
            raise BizException(2006, "能力编码已存在")

        return self.capabilities.update_fields(db, capability, values)

    def update_status(
        self, db: Session, capability_id: int, payload: CapabilityStatusUpdateRequest
    ) -> Capability:
        capability = self.require_capability(db, capability_id)
        updated = self.capabilities.update_fields(
            db, capability, {"status": payload.status.value}
        )
        logger.info(
            "能力状态已变更 capability_id={} status={}", capability_id, payload.status.value
        )
        return updated

    def delete_capability(self, db: Session, capability_id: int) -> None:
        capability = self.require_capability(db, capability_id)
        # 契约第 3 节：online 能力先下架再软删除，避免市场侧残留不可用的已删除条目。
        values: dict[str, object] = {"is_deleted": 1}
        if capability.status == CapabilityStatus.ONLINE.value:
            values["status"] = CapabilityStatus.OFFLINE.value

        self.capabilities.update_fields(db, capability, values)
        logger.info("能力已软删除 capability_id={}", capability_id)

    def require_capability(self, db: Session, capability_id: int) -> Capability:
        """取未删除能力（不限状态），不存在时抛 2002。"""

        capability = self.capabilities.find_by_id(db, capability_id)
        if capability is None:
            raise BizException(2002, "能力不存在")
        return capability

    def get_category_name(self, db: Session, category_id: int) -> str:
        """取分类名用于出参组装；分类已不存在时返回空串。"""

        category = self.categories.find_by_id(db, category_id)
        return category.name if category is not None else ""

    def _require_category(self, db: Session, category_id: int) -> CapabilityCategory:
        category = self.categories.find_by_id(db, category_id)
        if category is None:
            raise BizException(2003, "分类不存在")
        return category


capability_service = CapabilityService()
