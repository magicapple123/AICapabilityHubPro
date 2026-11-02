"""目录缓存失效接口（A3），挂载在 `/internal/capability-cache`。

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
