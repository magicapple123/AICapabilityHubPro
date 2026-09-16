"""分类接口的请求与响应模型。"""

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.core.constants import CODE_PATTERN, CategoryStatus
from app.schemas.common import BaseOut, validate_partial_update

NAME_MAX_LENGTH = 64
CODE_MAX_LENGTH = 64
SORT_MAX_VALUE = 99999


class CategoryCreateRequest(BaseModel):
    """新增分类请求；status 缺省为 enabled。"""

    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    code: str = Field(min_length=1, max_length=CODE_MAX_LENGTH, pattern=CODE_PATTERN)
    sort: int = Field(default=0, ge=0, le=SORT_MAX_VALUE)
    status: CategoryStatus = CategoryStatus.ENABLED


class CategoryUpdateRequest(BaseModel):
    """编辑分类请求；只提交需要变更的字段。"""

    name: str | None = Field(default=None, min_length=1, max_length=NAME_MAX_LENGTH)
    code: str | None = Field(
        default=None, min_length=1, max_length=CODE_MAX_LENGTH, pattern=CODE_PATTERN
    )
    sort: int | None = Field(default=None, ge=0, le=SORT_MAX_VALUE)
    status: CategoryStatus | None = None

    @model_validator(mode="after")
    def check_partial_update(self) -> "CategoryUpdateRequest":
        validate_partial_update(self, non_nullable=("name", "code", "sort", "status"))
        return self


class CategoryOut(BaseOut):
    """分类出参。"""

    id: int
    name: str
    code: str
    sort: int
    status: str
    create_time: datetime
    update_time: datetime


class CategoryDeleteOut(BaseOut):
    """分类软删除出参。"""

    id: int
    is_deleted: int = 1


class MarketCategoryOut(BaseOut):
    """市场筛选栏所需的分类出参，只暴露公开字段。"""

    id: int
    name: str
    code: str
