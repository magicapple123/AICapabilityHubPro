"""能力接口的请求与响应模型。

出参按"最小暴露"原则拆分：
- `CapabilityManageOut` 用于运营列表，含 service_name / path / param_schema 等内部配置；
- `CapabilityMarketOut` / `CapabilityMarketDetailOut` 用于公开市场，
  不包含任何内部配置字段，避免白名单接口泄露未上架能力与内部地址；
- `CapabilityInternalOut` 用于服务间内部详情，只含 AI 执行所需的六个字段。
"""

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.constants import (
    CODE_PATTERN,
    EXECUTOR_PROTOCOLS,
    BillingMode,
    CapabilityStatus,
    Executor,
)
from app.core.schema_validation import validate_param_schema
from app.models import Capability
from app.schemas.common import BaseOut, validate_partial_update

NAME_MAX_LENGTH = 64
CODE_MAX_LENGTH = 64
SERVICE_NAME_MAX_LENGTH = 64
PATH_MAX_LENGTH = 255
DESCRIPTION_MAX_LENGTH = 512
PRICE_MAX_VALUE = 1_000_000
UNIT_MAX_LENGTH = 16


ALIAS_PATTERN = r"^[a-z0-9][a-z0-9-]*$"
OPENAI_ALIAS_PATTERN = r"^[a-z][a-z0-9._-]{1,63}$"
MAX_OUTPUT_TOKENS_LIMIT = 32768


def normalize_openai_alias(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("对外模型名必须是字符串")
    alias = value.strip()
    if not alias:
        return None
    if not re.fullmatch(OPENAI_ALIAS_PATTERN, alias):
        raise ValueError("对外模型名需以小写字母开头，且只允许小写字母、数字、点、下划线、连字符")
    return alias


def validate_executor(executor: str, provider_alias: str) -> None:
    """执行器与供应商别名的组合校验（D2）；协议是否匹配由 service 跨服务确认。"""

    allowed = {item.value for item in Executor}
    if executor not in allowed:
        raise ValueError("执行器只能是 " + "/".join(sorted(allowed)))
    if provider_alias:
        if not re.match(ALIAS_PATTERN, provider_alias):
            raise ValueError("供应商别名只能是小写字母/数字/连字符")
    elif executor in (Executor.IMAGE_GENERATE.value, Executor.EMBEDDING.value):
        raise ValueError("文生图/向量化执行器必须绑定供应商别名")


def _billing_mode_of(capability: Capability) -> str:
    """取计价模式；未落库的临时对象/迁移前的行回落 per_call（与 DB 默认值一致）。"""

    return getattr(capability, "billing_mode", None) or BillingMode.PER_CALL.value


def validate_billing_fields(
    billing_mode: str,
    price_per_call: int,
    price_per_1k_input: int,
    price_per_1k_output: int,
    price_per_unit: int,
    unit: str,
) -> None:
    """计价字段的组合约束（C2）；不满足直接 2001，不让"半套价格"上线。

    - `per_call`  ：必须有 `price_per_call` 或允许为 0（免费能力），其余计价字段忽略；
    - `per_token` ：输入/输出单价至少一项 > 0；
    - `per_unit`  ：`price_per_unit > 0` 且 `unit` 不能为空（如"张"）。
    """

    if billing_mode == BillingMode.PER_TOKEN.value:
        if price_per_1k_input <= 0 and price_per_1k_output <= 0:
            raise ValueError("按 token 计费需要至少一项 token 单价大于 0")
        if price_per_call != 0:
            raise ValueError("按 token 计费时 price_per_call 必须为 0，避免双重计价")
        return
    if billing_mode == BillingMode.PER_UNIT.value:
        if price_per_unit <= 0:
            raise ValueError("按件计费需要 price_per_unit 大于 0")
        if not unit.strip():
            raise ValueError("按件计费必须声明计价单位，如 张")
        if price_per_call != 0:
            raise ValueError("按件计费时 price_per_call 必须为 0，避免双重计价")
        return
    if price_per_1k_input or price_per_1k_output or price_per_unit:
        raise ValueError("按次计费不应同时设置按 token / 按件单价")


class CapabilityCreateRequest(BaseModel):
    """登记能力请求；status 缺省为 draft，登记后需通过上下架接口上架。"""

    category_id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    code: str = Field(min_length=1, max_length=CODE_MAX_LENGTH, pattern=CODE_PATTERN)
    openai_alias: str | None = Field(default=None, max_length=64)
    service_name: str = Field(min_length=1, max_length=SERVICE_NAME_MAX_LENGTH)
    path: str = Field(min_length=1, max_length=PATH_MAX_LENGTH)
    param_schema: dict[str, Any] | None = None
    price_per_call: int = Field(default=0, ge=0, le=PRICE_MAX_VALUE)
    billing_mode: BillingMode = BillingMode.PER_CALL
    price_per_1k_input: int = Field(default=0, ge=0, le=PRICE_MAX_VALUE)
    price_per_1k_output: int = Field(default=0, ge=0, le=PRICE_MAX_VALUE)
    price_per_unit: int = Field(default=0, ge=0, le=PRICE_MAX_VALUE)
    unit: str = Field(default="", max_length=UNIT_MAX_LENGTH)
    # D2/D4：执行器与供应商绑定、输出 token 上限
    executor: str = Field(default=Executor.CHAT.value, max_length=32)
    provider_alias: str = Field(default="", max_length=64)
    max_output_tokens: int = Field(default=1024, ge=1, le=MAX_OUTPUT_TOKENS_LIMIT)
    # E4：市场展示开关（与 status 独立）
    exposed_to_market: bool = True
    status: CapabilityStatus = CapabilityStatus.DRAFT
    description: str = Field(default="", max_length=DESCRIPTION_MAX_LENGTH)

    @field_validator("param_schema")
    @classmethod
    def check_param_schema(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return validate_param_schema(value)

    @field_validator("openai_alias", mode="before")
    @classmethod
    def check_openai_alias(cls, value: Any) -> str | None:
        return normalize_openai_alias(value)

    @model_validator(mode="after")
    def check_billing(self) -> "CapabilityCreateRequest":
        validate_billing_fields(
            self.billing_mode.value, self.price_per_call, self.price_per_1k_input,
            self.price_per_1k_output, self.price_per_unit, self.unit,
        )
        validate_executor(self.executor, self.provider_alias)
        return self


class CapabilityUpdateRequest(BaseModel):
    """编辑能力请求。

    状态变更必须走 `PUT /api/capability/{id}/status`，因此这里不接收 `status`。
    """

    category_id: int | None = Field(default=None, ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=NAME_MAX_LENGTH)
    code: str | None = Field(
        default=None, min_length=1, max_length=CODE_MAX_LENGTH, pattern=CODE_PATTERN
    )
    openai_alias: str | None = Field(default=None, max_length=64)
    service_name: str | None = Field(
        default=None, min_length=1, max_length=SERVICE_NAME_MAX_LENGTH
    )
    path: str | None = Field(default=None, min_length=1, max_length=PATH_MAX_LENGTH)
    param_schema: dict[str, Any] | None = None
    price_per_call: int | None = Field(default=None, ge=0, le=PRICE_MAX_VALUE)
    # C2：计价模式的组合约束需要与既有值合并后校验，因此在 service 层做（见 update_capability）。
    billing_mode: BillingMode | None = None
    price_per_1k_input: int | None = Field(default=None, ge=0, le=PRICE_MAX_VALUE)
    price_per_1k_output: int | None = Field(default=None, ge=0, le=PRICE_MAX_VALUE)
    price_per_unit: int | None = Field(default=None, ge=0, le=PRICE_MAX_VALUE)
    unit: str | None = Field(default=None, max_length=UNIT_MAX_LENGTH)
    executor: str | None = Field(default=None, max_length=32)
    provider_alias: str | None = Field(default=None, max_length=64)
    max_output_tokens: int | None = Field(default=None, ge=1, le=MAX_OUTPUT_TOKENS_LIMIT)
    exposed_to_market: bool | None = None
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

    @field_validator("param_schema")
    @classmethod
    def check_param_schema(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return validate_param_schema(value)

    @field_validator("openai_alias", mode="before")
    @classmethod
    def check_openai_alias(cls, value: Any) -> str | None:
        return normalize_openai_alias(value)


class CapabilityStatusUpdateRequest(BaseModel):
    """上下架请求；只接受指南 5.5 定义的三个能力状态。"""

    status: CapabilityStatus


class CapabilityManageOut(BaseOut):
    """运营列表出参：包含内部配置字段与全部计价字段。"""

    id: int
    category_id: int
    category_name: str
    name: str
    code: str
    openai_alias: str | None = None
    service_name: str
    path: str
    param_schema: dict[str, Any] | None
    price_per_call: int
    billing_mode: str = BillingMode.PER_CALL.value
    price_per_1k_input: int = 0
    price_per_1k_output: int = 0
    price_per_unit: int = 0
    unit: str = ""
    executor: str = ""
    provider_alias: str = ""
    max_output_tokens: int = 1024
    exposed_to_market: bool = True
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
            openai_alias=capability.openai_alias,
            service_name=capability.service_name,
            path=capability.path,
            param_schema=capability.param_schema,
            price_per_call=capability.price_per_call,
            billing_mode=_billing_mode_of(capability),
            price_per_1k_input=capability.price_per_1k_input or 0,
            price_per_1k_output=capability.price_per_1k_output or 0,
            price_per_unit=capability.price_per_unit or 0,
            unit=capability.unit or "",
            executor=capability.executor or "",
            provider_alias=capability.provider_alias or "",
            max_output_tokens=capability.max_output_tokens or 1024,
            exposed_to_market=bool(capability.exposed_to_market),
            status=capability.status,
            description=capability.description,
            create_time=capability.create_time,
            update_time=capability.update_time,
        )


class CapabilityMarketOut(BaseOut):
    """公开市场列表出参：只含可对外字段，不含 service_name / path。

    `billing_mode` 与 `unit` 让前端知道"按次 / 按 token / 按张"，
    旧的 `price_per_call` 字段保留不动（契约兼容）。
    """

    id: int
    name: str
    code: str
    category_id: int
    category_name: str
    description: str
    price_per_call: int
    billing_mode: str = BillingMode.PER_CALL.value
    unit: str = ""
    # P8：市场卡片要判断"能不能调试"，必须以 executor 为准而不是猜 code。
    # 只暴露执行器名（chat/summary/image-generate），不含 service_name / path / 供应商密钥。
    executor: str = ""
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
            billing_mode=_billing_mode_of(capability),
            unit=capability.unit or "",
            executor=capability.executor or "",
            update_time=capability.update_time,
        )


class CapabilityMarketDetailOut(CapabilityMarketOut):
    """公开市场详情出参：在列表字段基础上增加 param_schema 与完整计价明细。"""

    param_schema: dict[str, Any] | None = None
    price_per_1k_input: int = 0
    price_per_1k_output: int = 0
    price_per_unit: int = 0
    executor: str = ""
    provider_alias: str = ""
    max_output_tokens: int = 1024

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
            billing_mode=_billing_mode_of(capability),
            unit=capability.unit or "",
            update_time=capability.update_time,
            param_schema=capability.param_schema,
            price_per_1k_input=capability.price_per_1k_input,
            price_per_1k_output=capability.price_per_1k_output,
            price_per_unit=capability.price_per_unit,
            # P8：这三个字段早就声明在出参上，但 from_row 一直没赋值，
            # 运行期恒为 ""/""/1024，前端只能靠 code 回退猜执行器。
            executor=capability.executor or "",
            provider_alias=capability.provider_alias or "",
            max_output_tokens=capability.max_output_tokens or 1024,
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


class CapabilityInternalOut(BaseModel):
    """服务间内部详情出参，与 AI 客户端读取的字段一一对应。

    不包含 service_name / path 等可被任意代理的目标配置；状态如实返回，
    draft / offline 由执行器在调用模型前拒绝。
    """

    id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    code: str = Field(min_length=1, max_length=CODE_MAX_LENGTH, pattern=CODE_PATTERN)
    openai_alias: str | None = Field(
        default=None, min_length=2, max_length=64, pattern=OPENAI_ALIAS_PATTERN
    )
    status: Literal["draft", "online", "offline"]
    param_schema: dict[str, Any]
    price_per_call: int = Field(ge=0, le=PRICE_MAX_VALUE)
    # C2：AI 执行链按这些字段决定预检门槛与结算金额。
    billing_mode: Literal["per_call", "per_token", "per_unit"] = "per_call"
    price_per_1k_input: int = Field(default=0, ge=0, le=PRICE_MAX_VALUE)
    price_per_1k_output: int = Field(default=0, ge=0, le=PRICE_MAX_VALUE)
    price_per_unit: int = Field(default=0, ge=0, le=PRICE_MAX_VALUE)
    unit: str = Field(default="", max_length=UNIT_MAX_LENGTH)
    # D2/D4：执行器选择与供应商绑定
    executor: str = Field(default="", max_length=32)
    provider_alias: str = Field(default="", max_length=64)
    max_output_tokens: int = Field(default=1024, ge=1, le=MAX_OUTPUT_TOKENS_LIMIT)

    @field_validator("param_schema")
    @classmethod
    def check_param_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        # 缺失或非法 Schema 会抛 ValueError，由 service 统一转成 4002。
        validate_param_schema(value)
        return value

    @classmethod
    def from_row(cls, capability: Capability) -> "CapabilityInternalOut":
        return cls(
            id=capability.id,
            name=capability.name,
            code=capability.code,
            openai_alias=capability.openai_alias,
            status=capability.status,
            param_schema=capability.param_schema,
            price_per_call=capability.price_per_call,
            billing_mode=_billing_mode_of(capability),
            price_per_1k_input=capability.price_per_1k_input or 0,
            price_per_1k_output=capability.price_per_1k_output or 0,
            price_per_unit=capability.price_per_unit or 0,
            unit=capability.unit or "",
            executor=capability.executor or "",
            provider_alias=capability.provider_alias or "",
            max_output_tokens=capability.max_output_tokens or 1024,
        )
