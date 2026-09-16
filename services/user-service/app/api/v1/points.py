"""积分余额与流水接口，挂载前缀 `/api/user/points`。均需要登录，只能查自己。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.deps import current_user_id
from app.core.constants import PointDirection
from app.core.logging import get_request_id
from app.core.result import Result
from app.db.session import get_db
from app.schemas import (
    PAGE_SIZE_DEFAULT,
    PAGE_SIZE_MAX,
    PointsAccountOut,
    build_page_data,
)
from app.service import points_service

router = APIRouter()


@router.get("", response_model=Result)
async def get_points(
    user_id: int = Depends(current_user_id), db: Session = Depends(get_db)
) -> Result:
    """当前用户积分余额。"""

    account = points_service.get_account(db, user_id)
    return Result.ok(
        PointsAccountOut.from_account(account).model_dump(), request_id=get_request_id()
    )


@router.get("/logs", response_model=Result)
async def list_point_logs(
    direction: PointDirection | None = Query(
        default=None, description="按变动方向筛选 in 收入 out 支出"
    ),
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
) -> Result:
    """当前用户积分流水分页；按时间倒序。"""

    items, total = points_service.list_logs(
        db,
        user_id,
        direction=direction.value if direction is not None else None,
        page=page,
        page_size=page_size,
    )
    return Result.ok(
        build_page_data(items, total, page, page_size), request_id=get_request_id()
    )
