"""能力业务逻辑。

关键约束：
- 登记与编辑前先校验分类是否存在（2003）与编码是否重复（2006）；
- 状态只能通过 `update_status` 变更，编辑接口不接收 status；
- 市场相关方法只返回已上架能力，未上架 / 已删除一律按 2002 处理，
  不向白名单接口暴露能力是否存在。
"""

from loguru import logger
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.constants import EXECUTOR_PROTOCOLS, CapabilityStatus
from app.core.service_call import call_internal
from app.core.config import settings
from app.core.exceptions import BizException
from app.core.schema_validation import validate_param_schema
from app.models import Capability, CapabilityCategory
from app.repository import CapabilityRepository, CategoryRepository
from app.repository import capability_repository, category_repository
from app.schemas import (
    CapabilityCreateRequest,
    CapabilityInternalOut,
    CapabilityStatusUpdateRequest,
    CapabilityUpdateRequest,
)
from app.schemas.capability import validate_billing_fields, validate_executor
from app.core.audit_context import current_audit_actor
from app.service.audit_service import (
    ACTION_CREATE,
    ACTION_ROLLBACK,
    ACTION_DELETE,
    ACTION_STATUS,
    ACTION_UPDATE,
    CAPABILITY_AUDIT_FIELDS,
    RESOURCE_CAPABILITY,
    build_entry,
    snapshot,
)
from app.service.audit_service import audit_service as audit_logs

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

    def get_internal_detail(
        self, db: Session, capability_id: int
    ) -> CapabilityInternalOut:
        """服务间内部详情。

        未知或已软删除返回 2002；草稿/下架如实返回状态，由执行器拒绝；
        数据库中的 Schema、状态或价格不合法时返回 4002 失败关闭，不投放半可用配置。
        """

        capability = self.capabilities.find_by_id(db, capability_id)
        if capability is None:
            raise BizException(2002, "能力不存在或已下线")
        try:
            return CapabilityInternalOut.from_row(capability)
        except ValidationError as exc:
            logger.error(
                "能力目录配置异常 capability_id={} error_count={}",
                capability_id,
                len(exc.errors()),
            )
            raise BizException(4002, "能力目录配置不完整或价格无效") from exc

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
        if payload.status is CapabilityStatus.ONLINE:
            self._ensure_online_schema(payload.param_schema)

        entity = Capability(
            category_id=payload.category_id,
            name=payload.name,
            code=payload.code,
            service_name=payload.service_name,
            path=payload.path,
            param_schema=payload.param_schema,
            price_per_call=payload.price_per_call,
            billing_mode=payload.billing_mode.value,
            price_per_1k_input=payload.price_per_1k_input,
            price_per_1k_output=payload.price_per_1k_output,
            price_per_unit=payload.price_per_unit,
            unit=payload.unit,
            executor=payload.executor,
            provider_alias=payload.provider_alias,
            max_output_tokens=payload.max_output_tokens,
            exposed_to_market=1 if payload.exposed_to_market else 0,
            status=payload.status.value,
            description=payload.description,
        )
        # after 用与 update 同一份白名单快照，保证创建与编辑的审计结构一致。
        audit = build_entry(
            actor=current_audit_actor(),
            resource_type=RESOURCE_CAPABILITY,
            resource_id="",
            action=ACTION_CREATE,
            before=None,
            after=snapshot(entity, CAPABILITY_AUDIT_FIELDS),
        )
        created = self.capabilities.create(db, entity, audit=audit)
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
        if (
            capability.status == CapabilityStatus.ONLINE.value
            and "param_schema" in values
            and values["param_schema"] is None
        ):
            raise BizException(2001, "线上能力不能清空参数 Schema，请先下架")

        self._validate_effective_billing(capability, values)
        self._validate_effective_executor(capability, values)
        if "billing_mode" in values and hasattr(values["billing_mode"], "value"):
            values["billing_mode"] = values["billing_mode"].value
        if "exposed_to_market" in values:
            values["exposed_to_market"] = 1 if values["exposed_to_market"] else 0
        before = snapshot(capability, CAPABILITY_AUDIT_FIELDS)
        after = {**before, **{k: v for k, v in values.items() if k in CAPABILITY_AUDIT_FIELDS}}
        audit = build_entry(
            actor=current_audit_actor(),
            resource_type=RESOURCE_CAPABILITY,
            resource_id=capability_id,
            action=ACTION_UPDATE,
            before=before,
            after=after,
        )
        return self.capabilities.update_fields(db, capability, values, audit=audit)

    @staticmethod
    def _validate_effective_executor(capability: Capability, values: dict) -> None:
        """按"改后"的执行器/别名校验格式组合；协议匹配由 ensure_provider_binding 做。"""

        if "executor" not in values and "provider_alias" not in values:
            return
        executor = values.get("executor", capability.executor)
        alias = values.get("provider_alias", capability.provider_alias)
        try:
            validate_executor(executor, alias)
        except ValueError as error:
            raise BizException(2001, str(error)) from error

    def rollback_capability(self, db: Session, capability_id: int, audit_id: int) -> Capability:
        """D5：把能力回滚到某次变更**之前**的状态。

        依据是该条审计的 `before_json`（白名单字段快照）。只允许回滚到
        同一能力的记录，且只回填白名单内字段——避免审计里缺失的字段被置空。
        """

        log = audit_logs.find_by_id(db, audit_id)
        if log is None or log.resource_type != RESOURCE_CAPABILITY:
            raise BizException(2001, "审计记录不存在或不属于能力")
        if str(log.resource_id) != str(capability_id):
            raise BizException(2001, "审计记录与目标能力不匹配")
        target = log.before_json or {}
        values = {k: v for k, v in target.items() if k in CAPABILITY_AUDIT_FIELDS}
        if not values:
            raise BizException(2001, "该记录没有可回滚的字段快照")
        capability = self.require_capability(db, capability_id)
        before = snapshot(capability, CAPABILITY_AUDIT_FIELDS)
        audit = build_entry(
            actor=current_audit_actor(),
            resource_type=RESOURCE_CAPABILITY,
            resource_id=capability_id,
            action=ACTION_ROLLBACK,
            before=before,
            after=values,
        )
        return self.capabilities.update_fields(db, capability, values, audit=audit)

    async def invalidate_catalog(self, capability_id: int | None = None) -> None:
        """A3：通知 ai-chat 失效目录缓存。**尽力而为**——失败只影响新鲜度（TTL 兜底）。

        不让写操作因为 ai-chat 不可用而回滚：改价已经落库，缓存晚 5 秒过期是可接受的。
        """

        # 关闭内部链路（本地/单测）时直接跳过：否则每次写操作都要等一次服务发现超时。
        if not settings.enable_internal_chain:
            return
        try:
            await call_internal(
                settings.ai_chat_service_name,
                "POST",
                "/internal/capability-cache/invalidate",
                json={"capability_id": capability_id},
                timeout=1.0,
            )
        except Exception as error:  # noqa: BLE001
            logger.warning(
                "目录缓存失效通知失败 capability_id={} type={}",
                capability_id, type(error).__name__,
            )

    async def ensure_provider_binding(self, executor: str, provider_alias: str) -> None:
        """保存阶段向 ai-chat 确认供应商协议与执行器匹配（D2）。

        跨库不建外键，所以"image-generate 只能绑 openai-image"这类规则
        必须问一次 provider 的真实协议；对端不可用时失败关闭（4002）。
        """

        if not provider_alias:
            return
        try:
            data = await call_internal(
                settings.ai_chat_service_name,
                "GET",
                f"/internal/provider/{provider_alias}",
            )
        except BizException as error:
            if error.code == 2002:
                raise BizException(2001, "供应商别名不存在，请先在模型服务中登记") from error
            raise BizException(4002, "供应商校验不可用，已拒绝保存") from error
        except Exception as error:  # noqa: BLE001 - 对端异常一律失败关闭
            raise BizException(4002, "供应商校验不可用，已拒绝保存") from error

        if not isinstance(data, dict) or not isinstance(data.get("protocol"), str):
            raise BizException(4002, "供应商校验响应格式错误")
        allowed = EXECUTOR_PROTOCOLS.get(executor, set())
        if data["protocol"] not in allowed:
            raise BizException(
                2001,
                f"执行器 {executor} 不能绑定协议 {data['protocol']} 的供应商",
            )

    @staticmethod
    def _validate_effective_billing(capability: Capability, values: dict) -> None:
        """按"改后"的整组计价字段校验，避免只改一半导致双重计价。"""

        billing_fields = (
            "billing_mode", "price_per_call", "price_per_1k_input",
            "price_per_1k_output", "price_per_unit", "unit",
        )
        if not any(field in values for field in billing_fields):
            return
        mode = values.get("billing_mode", capability.billing_mode)
        mode = getattr(mode, "value", mode)
        merged = {
            field: values.get(field, getattr(capability, field)) for field in billing_fields
        }
        merged["billing_mode"] = mode
        try:
            validate_billing_fields(
                mode,
                merged["price_per_call"],
                merged["price_per_1k_input"],
                merged["price_per_1k_output"],
                merged["price_per_unit"],
                merged["unit"],
            )
        except ValueError as error:
            raise BizException(2001, str(error)) from error

    def update_status(
        self, db: Session, capability_id: int, payload: CapabilityStatusUpdateRequest
    ) -> Capability:
        capability = self.require_capability(db, capability_id)
        if payload.status is CapabilityStatus.ONLINE:
            self._ensure_online_schema(capability.param_schema)
        audit = build_entry(
            actor=current_audit_actor(),
            resource_type=RESOURCE_CAPABILITY,
            resource_id=capability_id,
            action=ACTION_STATUS,
            before={"status": capability.status},
            after={"status": payload.status.value},
        )
        updated = self.capabilities.update_fields(
            db, capability, {"status": payload.status.value}, audit=audit
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
        audit = build_entry(
            actor=current_audit_actor(),
            resource_type=RESOURCE_CAPABILITY,
            resource_id=capability_id,
            action=ACTION_DELETE,
            before=snapshot(capability, CAPABILITY_AUDIT_FIELDS),
            after=values,
        )

        self.capabilities.update_fields(db, capability, values, audit=audit)
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

    @staticmethod
    def _ensure_online_schema(param_schema: dict | None) -> None:
        """上线必须有合法 Schema，避免市场展示无法执行的目录配置。"""

        if param_schema is None:
            raise BizException(2001, "上架能力必须提供合法的参数 Schema")
        try:
            validate_param_schema(param_schema)
        except ValueError as exc:
            raise BizException(2001, "上架能力必须提供合法的参数 Schema") from exc


capability_service = CapabilityService()
