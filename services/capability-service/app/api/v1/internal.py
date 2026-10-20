"""服务间内部能力详情，挂载前缀 `/internal/capability`。

AI 执行器在每次调用前读取该接口，要求 id/code/status/param_schema/price_per_call。
网关对外部 `/internal/**` 一律 403；这里仍校验链路身份，避免绕过网关直连服务时
匿名读取目录配置。响应不包含 service_name / path，避免被当做任意代理目标。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.deps import current_user_id
from app.core.logging import get_request_id
from app.core.result import Result
from app.db.session import get_db
from app.service import capability_service

router = APIRouter()


@router.get("/{capability_id}", response_model=Result)
async def get_internal_capability(
    capability_id: int,
    _: str = Depends(current_user_id),
    db: Session = Depends(get_db),
) -> Result:
    """内部详情；未知/软删除 2002，配置异常 4002，草稿/下架保留真实状态。"""

    detail = capability_service.get_internal_detail(db, capability_id)
    return Result.ok(detail.model_dump(), request_id=get_request_id())
