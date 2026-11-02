"""供应商业务逻辑（D1）。

安全策略（已冻结）：
1. 保存阶段就校验 `base_url`：https + 域名白名单 + 禁内网（解析后逐 IP 判断）；
2. 草稿可存，**"启用"前必须测通**（`last_test_ok_at` 非空）；
3. 每次真实调用前**重新校验**一次地址，缩小 DNS 重绑定的时间窗
   （已知限制：校验与建连之间仍有极短 TOCTOU 窗口，需要 IP 钉住才能完全消除，
   已记入契约文档"已知限制"）；
4. 不跟随重定向；密钥只在内存解密，不写日志、不进任何响应。
"""

from dataclasses import dataclass
from datetime import datetime

import httpx
from loguru import logger
from sqlalchemy.orm import Session

from app.core.exceptions import BizException
from app.core.provider_crypto import ProviderKeyError, decrypt, encrypt, mask
from app.core.provider_guard import ProviderUrlError, validate_url
from app.models.provider import (
    PROVIDER_DISABLED,
    PROVIDER_DRAFT,
    PROVIDER_ENABLED,
    ModelProvider,
)
from app.repository.provider_repository import provider_repository
from app.schemas.provider import (
    ProviderCreateRequest,
    ProviderTestOut,
    ProviderUpdateRequest,
)

ALIAS_CONFLICT_CODE = 2006
VALIDATION_CODE = 2001
DEPENDENCY_CODE = 4002

# 各协议探测路径；探测只验证"能连通且鉴权通过"，不消耗生成额度。
PROBE_PATHS = {
    "openai-chat": "/models",
    "openai-image": "/models",
    "openai-embedding": "/models",
    # 百炼原生协议没有 /models，但兼容模式有（实测 200），用它做连通性探测。
    "dashscope-image": "/compatible-mode/v1/models",
    "custom-http": "",
}


@dataclass(frozen=True)
class ProviderRuntime:
    """一次调用需要的供应商运行参数；`api_key` 只在内存存在。"""

    alias: str
    protocol: str
    base_url: str
    api_key: str
    model: str
    timeout: float


def _check_url(url: str) -> None:
    try:
        validate_url(url)
    except ProviderUrlError as error:
        raise BizException(VALIDATION_CODE, f"供应商地址不可用：{error}") from error


class ProviderService:
    def list_providers(self, db: Session) -> list[ModelProvider]:
        return provider_repository.list_all(db)

    def create_provider(
        self, db: Session, payload: ProviderCreateRequest
    ) -> ModelProvider:
        if provider_repository.find_by_alias(db, payload.alias) is not None:
            raise BizException(ALIAS_CONFLICT_CODE, "供应商别名已存在")
        _check_url(payload.base_url)
        try:
            cipher = encrypt(payload.api_key)
        except ProviderKeyError as error:
            raise BizException(DEPENDENCY_CODE, "主密钥未配置或不可用，无法保存密钥") from error
        provider = ModelProvider(
            name=payload.name,
            alias=payload.alias,
            protocol=payload.protocol,
            base_url=payload.base_url,
            api_key_cipher=cipher,
            api_key_mask=mask(payload.api_key),
            default_model=payload.default_model,
            timeout_ms=payload.timeout_ms,
            extra_json=payload.extra_json,
            # 创建只能是草稿：启用必须经过连通性测试。
            status=PROVIDER_DRAFT,
        )
        created = provider_repository.create(db, provider)
        logger.info("供应商已登记 provider_id={} alias={}", created.id, created.alias)
        return created

    def update_provider(
        self, db: Session, provider_id: int, payload: ProviderUpdateRequest
    ) -> ModelProvider:
        provider = self.require(db, provider_id)
        values = payload.model_dump(exclude_unset=True, exclude_none=True)
        if "base_url" in values:
            _check_url(values["base_url"])
        if "api_key" in values:
            try:
                values["api_key_cipher"] = encrypt(values.pop("api_key"))
            except ProviderKeyError as error:
                raise BizException(DEPENDENCY_CODE, "主密钥未配置或不可用") from error
            values["api_key_mask"] = mask(payload.api_key or "")
            # 换密钥后必须重新测通才能保持启用态。
            if provider.status == PROVIDER_ENABLED:
                values["status"] = PROVIDER_DRAFT
                values["last_test_ok_at"] = None
        return provider_repository.update_fields(db, provider, values)

    def set_status(self, db: Session, provider_id: int, status: str) -> ModelProvider:
        provider = self.require(db, provider_id)
        if status == PROVIDER_ENABLED:
            if provider.last_test_ok_at is None:
                raise BizException(VALIDATION_CODE, "启用前必须先通过连通性测试")
            _check_url(provider.base_url)
        if status not in (PROVIDER_ENABLED, PROVIDER_DISABLED, PROVIDER_DRAFT):
            raise BizException(VALIDATION_CODE, "供应商状态只能是 draft/enabled/disabled")
        return provider_repository.update_fields(db, provider, {"status": status})

    async def test_provider(self, db: Session, provider_id: int) -> ProviderTestOut:
        provider = self.require(db, provider_id)
        started = datetime.now()
        try:
            target = validate_url(provider.base_url)
        except ProviderUrlError as error:
            return ProviderTestOut(
                provider_id=provider_id, ok=False, reason=f"URL_REJECTED:{error}"
            )
        try:
            api_key = decrypt(provider.api_key_cipher)
        except ProviderKeyError:
            return ProviderTestOut(provider_id=provider_id, ok=False, reason="KEY_UNREADABLE")

        path = PROBE_PATHS.get(provider.protocol, "")
        url = f"{target.url}{path}" if path else target.url
        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            async with httpx.AsyncClient(
                timeout=min(provider.timeout_ms, 15000) / 1000, follow_redirects=False
            ) as client:
                response = await client.get(url, headers=headers)
                status = response.status_code
        except httpx.TimeoutException:
            return ProviderTestOut(
                provider_id=provider_id, ok=False, reason="TIMEOUT",
                elapsed_ms=int((datetime.now() - started).total_seconds() * 1000),
            )
        except Exception as exc:  # noqa: BLE001 - 探测失败只需要原因码
            logger.warning("供应商探测失败 provider_id={} type={}", provider_id, type(exc).__name__)
            return ProviderTestOut(
                provider_id=provider_id, ok=False, reason="NETWORK_ERROR",
                elapsed_ms=int((datetime.now() - started).total_seconds() * 1000),
            )

        elapsed = int((datetime.now() - started).total_seconds() * 1000)
        if status in (401, 403):
            return ProviderTestOut(
                provider_id=provider_id, ok=False, reason="AUTH_FAILED",
                http_status=status, elapsed_ms=elapsed,
            )
        if status >= 400:
            return ProviderTestOut(
                provider_id=provider_id, ok=False, reason="UPSTREAM_ERROR",
                http_status=status, elapsed_ms=elapsed,
            )
        provider_repository.update_fields(
            db, provider, {"last_test_ok_at": datetime.now()}
        )
        return ProviderTestOut(
            provider_id=provider_id, ok=True, http_status=status, elapsed_ms=elapsed
        )

    def require(self, db: Session, provider_id: int) -> ModelProvider:
        provider = provider_repository.find_by_id(db, provider_id)
        if provider is None:
            raise BizException(2002, "供应商不存在")
        return provider

    def resolve_runtime(
        self, db: Session, alias: str, *, model: str | None = None
    ) -> ProviderRuntime:
        """按别名取运行参数；未启用/不存在/地址不安全一律失败关闭。"""

        provider = provider_repository.find_by_alias(db, alias)
        if provider is None or provider.status != PROVIDER_ENABLED:
            raise BizException(2008, f"供应商 {alias} 不存在或未启用")
        try:
            validate_url(provider.base_url)
        except ProviderUrlError as error:
            raise BizException(DEPENDENCY_CODE, f"供应商地址已失效：{error}") from error
        try:
            api_key = decrypt(provider.api_key_cipher)
        except ProviderKeyError as error:
            raise BizException(DEPENDENCY_CODE, "供应商密钥不可解密") from error
        return ProviderRuntime(
            alias=provider.alias,
            protocol=provider.protocol,
            base_url=provider.base_url,
            api_key=api_key,
            model=model or provider.default_model,
            timeout=provider.timeout_ms / 1000,
        )


provider_service = ProviderService()
