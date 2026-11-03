"""Read the trusted catalog snapshot through a 5 s cache with explicit invalidation.

A3：命中缓存就直接用；未命中才向 capability-service 取快照。改价 / 上下架由
capability 的写操作主动调 `/internal/capability-cache/invalidate` 清缓存，
因此"运营改价后 5 秒内生效，管理接口改动接近立即生效"。"""
import asyncio
import re
from typing import Any

from pydantic import ValidationError
from app.core.capability_config import capability_settings
from app.core.config import settings
from app.core.exceptions import BizException
from app.core.http_client import get_http_client
from app.core.logging import get_request_id
from app.core.nacos_client import nacos_register
from app.core.observability import CATALOG_CACHE_EVENTS
from app.core.service_call import call_internal
from app.schemas.capability import CapabilityDefinition
from app.service.catalog_cache import OpenAIModelCatalog, catalog_cache


class CapabilityClient:
    def __init__(self) -> None:
        self._openai_models_lock = asyncio.Lock()

    async def openai_model_catalog(self) -> OpenAIModelCatalog:
        """Get cached aliases and their currently callable chat capability targets."""

        cached = catalog_cache.get_openai_models()
        if cached is not None:
            return cached
        async with self._openai_models_lock:
            cached = catalog_cache.get_openai_models()
            if cached is not None:
                return cached
            CATALOG_CACHE_EVENTS.labels(
                service="ai-chat-service", result="models-fetch"
            ).inc()
            try:
                payload = await call_internal(
                    capability_settings.capability_service_name,
                    "GET",
                    "/internal/capability/openai-models",
                )
            except BizException as error:
                raise BizException(4002, "OpenAI 模型目录暂不可用") from error
            except Exception as error:
                raise BizException(4002, "OpenAI 模型目录响应异常") from error
        if not isinstance(payload, list):
            raise BizException(4002, "OpenAI 模型目录响应格式错误")

        mapping: dict[str, int] = {}
        capability_ids: set[int] = set()
        for row in payload:
            if not isinstance(row, dict):
                raise BizException(4002, "OpenAI 模型目录响应格式错误")
            capability_id = row.get("id")
            alias = row.get("openai_alias")
            if type(capability_id) is not int or capability_id < 1:
                raise BizException(4002, "OpenAI 模型目录响应格式错误")
            capability_ids.add(capability_id)
            if alias is None:
                continue
            if (
                not isinstance(alias, str)
                or re.fullmatch(r"^[a-z][a-z0-9._-]{1,63}$", alias) is None
                or alias in mapping
            ):
                raise BizException(4002, "OpenAI 模型目录响应格式错误")
            mapping[alias] = capability_id
        catalog = OpenAIModelCatalog(mapping, frozenset(capability_ids))
        catalog_cache.put_openai_models(catalog)
        return catalog

    async def fetch(self, capability_id: int) -> CapabilityDefinition:
        """A3：先查 5 秒缓存；未命中再取快照。失效通知由 capability 写操作触发。"""

        cached = catalog_cache.get(capability_id)
        if cached is not None:
            return cached
        definition = await self._fetch_uncached(capability_id)
        catalog_cache.put(capability_id, definition)
        return definition

    async def _fetch_uncached(self, capability_id: int) -> CapabilityDefinition:
        mode = capability_settings.capability_catalog_mode
        try:
            if mode == "internal":
                payload = await call_internal(
                    capability_settings.capability_service_name, "GET",
                    f"/internal/capability/{capability_id}",
                )
            else:
                payload = await self._market_detail(capability_id)
        except BizException as error:
            if error.code == 2002:
                raise
            raise BizException(4002, "能力目录暂不可用，请联系目录服务负责人") from error
        except Exception as error:
            raise BizException(4002, "能力目录响应异常") from error
        if not isinstance(payload, dict):
            raise BizException(4002, "能力目录响应格式错误")
        if payload.get("is_deleted", 0) != 0:
            raise BizException(2002, "能力不存在或已下线")
        data = {**payload, "catalog_source": mode}
        if mode == "market":
            # This fixed endpoint itself filters draft/offline/deleted records.
            # A present contradictory status must still be rejected.
            if data.get("status", "online") != "online":
                raise BizException(2002, "能力不存在或已下线")
            data["status"] = "online"
        try:
            definition = CapabilityDefinition.model_validate(data)
        except ValidationError as error:
            raise BizException(4002, "能力目录配置不完整或价格无效") from error
        if definition.id != capability_id:
            raise BizException(4002, "能力目录返回了错误的能力 ID")
        if definition.status != "online":
            raise BizException(2002, "能力不存在或已下线")
        return definition

    async def _market_detail(self, capability_id: int) -> Any:
        """Opt-in compatibility with the existing published-only market API."""
        try:
            base = nacos_register.discover_one(capability_settings.capability_service_name)
            client = await get_http_client()
            response = await client.get(
                f"{base}/api/capability/market/{capability_id}",
                headers={"X-Request-Id": get_request_id()},
                timeout=settings.internal_call_timeout,
            )
            response.raise_for_status()
            if len(response.content) > 65536:
                raise ValueError("Oversized catalog response")
            body = response.json()
        except Exception as error:
            raise BizException(4002, "能力目录暂不可用") from error
        if not isinstance(body, dict) or type(body.get("code")) is not int:
            raise BizException(4002, "能力目录响应格式错误")
        if body["code"] == 2002:
            raise BizException(2002, "能力不存在或已下线")
        if body["code"] != 0:
            raise BizException(4002, "能力目录响应错误")
        return body.get("data")


capability_client = CapabilityClient()
