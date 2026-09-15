"""能力接口的请求与响应模型。

出参按"最小暴露"原则拆分：
- `CapabilityManageOut` 用于运营列表，含 service_name / path / param_schema 等内部配置；
- `CapabilityMarketOut` / `CapabilityMarketDetailOut` 用于公开市场，
  不包含任何内部配置字段，避免白名单接口泄露未上架能力与内部地址。
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.core.constants import CODE_PATTERN, CapabilityStatus
from app.models import Capability
from app.schemas.common import BaseOut, validate_partial_update

NAME_MAX_LENGTH = 64
CODE_MAX_LENGTH = 64
SERVICE_NAME_MAX_LENGTH = 64
PATH_MAX_LENGTH = 255
DESCRIPTION_MAX_LENGTH = 512
PRICE_MAX_VALUE = 1_000_000


class CapabilityCreateRequest(BaseModel):
    """登记能力请求；status 缺省为 draft，登记后需通过上下架接口上架。"""

    category_id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    code: str = Field(min_length=1, max_length=CODE_MAX_LENGTH, pattern=CODE_PATTERN)
    service_name: str = Field(min_length=1, max_length=SERVICE_NAME_MAX_LENGTH)
    path: str = Field(min_length=1, max_length=PATH_MAX_LENGTH)
    param_schema: dict[str, Any] | None = None
    price_per_call: int = Field(default=0, ge=0, le=PRICE_MAX_VALUE)
    status: CapabilityStatus = CapabilityStatus.DRAFT
    description: str = Field(default="", max_length=DESCRIPTION_MAX_LENGTH)


class CapabilityUpdateRequest(BaseModel):
    """编辑能力请求。

    状态变更必须走 `PUT /api/capability/{id}/status`，因此这里不接收 `status`。
    """

    category_id: int | None = Field(default=None, ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=NAME_MAX_LENGTH)
    code: str | None = Field(
        default=None, min_length=1, max_length=CODE_MAX_LENGTH, pattern=CODE_PATTERN
    )
    service_name: str | None = Field(
        default=None, min_length=1, max_length=SERVICE_NAME_MAX_LENGTH
    )
    path: str | None = Field(default=None, min_length=1, max_length=PATH_MAX_LENGTH)
    param_schema: dict[str, Any] | None = None
    price_per_call: int | None = Field(default=None, ge=0, le=PRICE_MAX_VALUE)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)

    @model_validator(mode="after")
    def check_partial_update(self) -> "CapabilityUpdateRequest":
        validate_partial_update(
            self,
            non_nullable=(
                "category_id",
                "name",
                "code",
                "service_name",
                "path",
                "price_per_call",
                "description",
            ),
        )
        return self


class CapabilityStatusUpdateRequest(BaseModel):
    """上下架请求；只接受指南 5.5 定义的三个能力状态。"""

    status: CapabilityStatus


class CapabilityManageOut(BaseOut):
    """运营列表出参：包含内部配置字段。"""

    id: int
    category_id: int
    category_name: str
    name: str
    code: str
    service_name: str
    path: str
    param_schema: dict[str, Any] | None
    price_per_call: int
    status: str
    description: str
    create_time: datetime
    update_time: datetime

    @classmethod
    def from_row(cls, capability: Capability, category_name: str) -> "CapabilityManageOut":
        """由能力实体与分类名组装出参，字段显式列出以避免误带内部字段。"""

        return cls(
            id=capability.id,
            category_id=capability.category_id,
            category_name=category_name,
            name=capability.name,
            code=capability.code,
            service_name=capability.service_name,
            path=capability.path,
            param_schema=capability.param_schema,
            price_per_call=capability.price_per_call,
            status=capability.status,
            description=capability.description,
            create_time=capability.create_time,
            update_time=capability.update_time,
        )


class CapabilityMarketOut(BaseOut):
    """公开市场列表出参：只含可对外字段，不含 service_name / path。"""

    id: int
    name: str
    code: str
    category_id: int
    category_name: str
    description: str
    price_per_call: int
    update_time: datetime

    @classmethod
    def from_row(cls, capability: Capability, category_name: str) -> "CapabilityMarketOut":
        """市场列表项：字段显式列举，保证不输出内部配置与状态。"""

        return cls(
            id=capability.id,
            name=capability.name,
            code=capability.code,
            category_id=capability.category_id,
            category_name=category_name,
            description=capability.description,
            price_per_call=capability.price_per_call,
            update_time=capability.update_time,
        )


class CapabilityMarketDetailOut(CapabilityMarketOut):
    """公开市场详情出参：在列表字段基础上增加 param_schema。"""

    param_schema: dict[str, Any] | None = None

    @classmethod
    def from_row(
        cls, capability: Capability, category_name: str
    ) -> "CapabilityMarketDetailOut":
        return cls(
            id=capability.id,
            name=capability.name,
            code=capability.code,
            category_id=capability.category_id,
            category_name=category_name,
            description=capability.description,
            price_per_call=capability.price_per_call,
            update_time=capability.update_time,
            param_schema=capability.param_schema,
        )


class CapabilityDeleteOut(BaseOut):
    """能力软删除出参。"""

    id: int
    is_deleted: int = 1


class CapabilityStatusOut(BaseOut):
    """上下架结果出参。"""

    id: int
    status: str
    update_time: datetime
