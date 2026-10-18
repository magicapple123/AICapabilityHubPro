"""Read a fresh trusted catalog snapshot before every execution, without caching."""
from typing import Any
import httpx
from pydantic import ValidationError
from app.core.capability_config import capability_settings
from app.core.config import settings
from app.core.exceptions import BizException
from app.core.logging import get_request_id
from app.core.nacos_client import nacos_register
from app.core.service_call import call_internal
from app.schemas.capability import CapabilityDefinition


class CapabilityClient:
    async def fetch(self, capability_id: int) -> CapabilityDefinition:
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
            async with httpx.AsyncClient(timeout=settings.internal_call_timeout) as client:
                response = await client.get(
                    f"{base}/api/capability/market/{capability_id}",
                    headers={"X-Request-Id": get_request_id()},
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
