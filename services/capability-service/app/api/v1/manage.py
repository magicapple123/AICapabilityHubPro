"""运营管理列表接口，挂载前缀 `/api/capability`。

需要登录且通过 user-service 实时管理员授权；普通用户 2007，授权依赖
不可用 4002，不具备运营权限时不返回任何内部目录字段。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.deps import require_admin
from app.core.constants import CapabilityStatus
from app.core.logging import get_request_id
from app.core.result import Result
from app.db.session import get_db
from app.schemas import (
    PAGE_SIZE_DEFAULT,
    PAGE_SIZE_MAX,
    CapabilityManageOut,
    build_page_data,
)
from app.service import capability_service

router = APIRouter()


@router.get("/manage", response_model=Result)
async def list_manage(
    status: CapabilityStatus | None = Query(
        default=None, description="按能力状态筛选，缺省返回全部状态"
    ),
    category_id: int | None = Query(default=None, ge=1, description="按分类筛选"),
    keyword: str | None = Query(
        default=None, max_length=64, description="按能力名称或描述模糊匹配"
    ),
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Result:
    """运营列表；仅管理员可读，返回全部状态与内部配置字段。"""

    rows, total = capability_service.list_manage(
        db,
        status=status.value if status is not None else None,
        category_id=category_id,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    items = [CapabilityManageOut.from_row(capability, name) for capability, name in rows]
    return Result.ok(
        build_page_data(items, total, page, page_size), request_id=get_request_id()
    )
