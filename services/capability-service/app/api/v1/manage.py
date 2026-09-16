"""运营管理列表接口，挂载前缀 `/api/capability`。需要登录。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.deps import current_user_id
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
    _: str = Depends(current_user_id),
    db: Session = Depends(get_db),
) -> Result:
    """运营列表；返回全部状态，含 service_name / path / param_schema 等内部字段。"""

    # TODO(契约第 6 节待确认): 运营权限方案未定，当前按“已登录即可访问”处理，
    # 2007 判定位置保留在此处。
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
