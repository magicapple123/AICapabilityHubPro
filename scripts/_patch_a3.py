"""一次性补丁：A3 缓存接线（执行后删除）。"""
import io


def patch(path, pairs, required=True):
    s = io.open(path, encoding="utf-8").read()
    for old, new in pairs:
        if old not in s:
            if required:
                raise SystemExit(f"anchor not found in {path}: {old[:60]}")
            continue
        s = s.replace(old, new, 1)
    io.open(path, "w", encoding="utf-8").write(s)
    print("patched", path)


# 1) 指标：缓存命中/失效计数（四份模块保持一致）
for svc in ("user", "billing", "capability", "ai-chat"):
    p = f"services/{svc}-service/app/core/observability.py"
    s = io.open(p, encoding="utf-8").read()
    if "CATALOG_CACHE_EVENTS" not in s:
        s = s.replace('''CATALOG_FAILURES = Counter(''', '''CATALOG_CACHE_EVENTS = Counter(
    "catalog_cache_events_total", "目录缓存事件", ["service", "result"], registry=REGISTRY,
)
CATALOG_FAILURES = Counter(''')
        io.open(p, "w", encoding="utf-8").write(s)
print("metrics added")

# 2) 目录客户端读缓存
patch("services/ai-chat-service/app/service/capability_client.py", [
    ('''from app.schemas.capability import CapabilityDefinition''',
     '''from app.schemas.capability import CapabilityDefinition
from app.service.catalog_cache import catalog_cache'''),
    ('''class CapabilityClient:
    async def fetch(self, capability_id: int) -> CapabilityDefinition:''',
     '''class CapabilityClient:
    async def fetch(self, capability_id: int) -> CapabilityDefinition:
        """A3：先查 5 秒缓存；未命中再取快照。失效通知由 capability 写操作触发。"""

        cached = catalog_cache.get(capability_id)
        if cached is not None:
            return cached
        definition = await self._fetch_uncached(capability_id)
        catalog_cache.put(capability_id, definition)
        return definition

    async def _fetch_uncached(self, capability_id: int) -> CapabilityDefinition:'''),
])

# 3) ai-chat 失效接口
patch("services/ai-chat-service/app/api/v1/internal_provider.py", [
    ('''router = APIRouter()''',
     '''router = APIRouter()


@router.post("/../capability-cache/invalidate", include_in_schema=False)
async def _unused() -> None:  # pragma: no cover - 占位，真正实现在 catalog 路由
    return None'''),
], required=False)

io.open("services/ai-chat-service/app/api/v1/internal_catalog.py", "w", encoding="utf-8").write(
    '''"""目录缓存失效接口（A3），挂载在 `/internal/capability-cache`。

capability 的写操作（新建/编辑/上下架/删除）成功后调用这里，
把"改价 5 秒后才生效"的窗口压到接近 0。**尽力而为**：调用方吞掉异常，
失败只影响新鲜度，不影响业务成功。
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.core.exceptions import BizException
from app.core.logging import get_request_id
from app.core.result import Result
from app.core.security import UserContext, current_user
from app.service.catalog_cache import catalog_cache

router = APIRouter()


class InvalidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capability_id: int | None = Field(default=None, ge=1)


@router.post("/invalidate", response_model=Result)
async def invalidate(
    payload: InvalidateRequest,
    user: UserContext = Depends(current_user),
) -> Result:
    """带 `capability_id` 失效单条，不带则清空全部。"""

    if not user.user_id:
        raise BizException(1001, "缺少可信链路身份")
    removed = catalog_cache.invalidate(payload.capability_id)
    return Result.ok({"removed": removed}, request_id=get_request_id())
''',
)

# 4) 注册路由
p = "services/ai-chat-service/app/api/v1/__init__.py"
s = io.open(p, encoding="utf-8").read()
if "internal_catalog_router" not in s:
    s = s.replace("from app.api.v1.internal_provider import router as internal_provider_router",
                  "from app.api.v1.internal_catalog import router as internal_catalog_router\n"
                  "from app.api.v1.internal_provider import router as internal_provider_router")
    s = s.replace('    "internal_provider_router",', '    "internal_catalog_router",\n    "internal_provider_router",')
    io.open(p, "w", encoding="utf-8").write(s)

p = "services/ai-chat-service/app/main.py"
s = io.open(p, encoding="utf-8").read()
if "internal_catalog_router" not in s:
    s = s.replace("    internal_provider_router,", "    internal_catalog_router,\n    internal_provider_router,")
    s = s.replace('''app.include_router(
    internal_provider_router, prefix="/internal/provider", tags=["provider-internal"]
)''', '''app.include_router(
    internal_provider_router, prefix="/internal/provider", tags=["provider-internal"]
)
app.include_router(
    internal_catalog_router,
    prefix="/internal/capability-cache",
    tags=["catalog-cache-internal"],
)''')
    io.open(p, "w", encoding="utf-8").write(s)
print("routes wired")
