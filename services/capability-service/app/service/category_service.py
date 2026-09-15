"""分类业务逻辑。

业务错误码只用 2xxx 号段，且通过 BizException 抛出，由基座的全局异常处理器
转换成统一 Result（HTTP 仍为 200）。
"""

from loguru import logger
from sqlalchemy.orm import Session

from app.core.exceptions import BizException
from app.models import CapabilityCategory
from app.repository import CapabilityRepository, CategoryRepository
from app.repository import capability_repository, category_repository
from app.schemas import CategoryCreateRequest, CategoryUpdateRequest


class CategoryService:
    """分类的增删改查与删除前引用检查。"""

    def __init__(
        self,
        categories: CategoryRepository | None = None,
        capabilities: CapabilityRepository | None = None,
    ) -> None:
        self.categories = categories or category_repository
        self.capabilities = capabilities or capability_repository

    def list_categories(
        self,
        db: Session,
        *,
        status: str | None = None,
        keyword: str | None = None,
    ) -> list[CapabilityCategory]:
        return self.categories.list_all(db, status=status, keyword=keyword)

    def create_category(
        self, db: Session, payload: CategoryCreateRequest
    ) -> CapabilityCategory:
        if self.categories.exists_name(db, payload.name):
            raise BizException(2004, "分类名称已存在")
        if self.categories.exists_code(db, payload.code):
            raise BizException(2004, "分类编码已存在")

        created = self.categories.create(
            db,
            CapabilityCategory(
                name=payload.name,
                code=payload.code,
                sort=payload.sort,
                status=payload.status.value,
            ),
        )
        logger.info("分类已创建 category_id={} code={}", created.id, created.code)
        return created

    def update_category(
        self, db: Session, category_id: int, payload: CategoryUpdateRequest
    ) -> CapabilityCategory:
        category = self.require_category(db, category_id)
        # 只有显式提交的字段才参与更新，避免把未提交字段覆盖成默认值。
        values = payload.model_dump(exclude_unset=True, exclude_none=True)

        if "name" in values and self.categories.exists_name(
            db, values["name"], exclude_id=category_id
        ):
            raise BizException(2004, "分类名称已存在")
        if "code" in values and self.categories.exists_code(
            db, values["code"], exclude_id=category_id
        ):
            raise BizException(2004, "分类编码已存在")
        if "status" in values:
            values["status"] = values["status"].value

        return self.categories.update_fields(db, category, values)

    def delete_category(self, db: Session, category_id: int) -> None:
        category = self.require_category(db, category_id)
        # 契约 2005：分类下仍有未删除能力时不允许删除。
        if self.capabilities.count_by_category(db, category_id) > 0:
            raise BizException(2005, "分类下仍有能力，不可删除")

        self.categories.soft_delete(db, category)
        logger.info("分类已软删除 category_id={}", category_id)

    def require_category(self, db: Session, category_id: int) -> CapabilityCategory:
        """取未删除分类，不存在时抛 2003；供本服务其它业务复用。"""

        category = self.categories.find_by_id(db, category_id)
        if category is None:
            raise BizException(2003, "分类不存在")
        return category


category_service = CategoryService()
