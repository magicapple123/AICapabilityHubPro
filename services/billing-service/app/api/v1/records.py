"""调用明细与用量统计接口，挂载前缀 `/api/billing`。均需要登录。

- `/api/billing/records`、`/api/billing/usage`：只返回当前用户自己的数据；
- `/api/billing/stat/overview`：运营全局统计，当前按“已登录即可访问”处理
  （平台暂无角色体系，契约第 6 节已登记为待确认项，与 capability-service 现状一致）。
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.deps import call_status_filter, current_user_id, date_range
from app.core.logging import get_request_id
from app.core.result import Result
from app.db.session import get_db
from app.schemas import PAGE_SIZE_DEFAULT, PAGE_SIZE_MAX, build_page_data
from app.service import billing_service, user_status_service

router = APIRouter()


@router.get("/records", response_model=Result)
async def list_records(
    range_: tuple[date, date] = Depends(date_range),
    service_name: str | None = Query(
        default=None, max_length=64, description="按承载服务名精确筛选"
    ),
    call_status: str | None = Depends(call_status_filter),
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
) -> Result:
    """当前用户调用明细分页；按时间倒序，超出默认 30 天窗口需显式传日期。"""

    # 网关不校验账号状态（见 app/service/user_status.py），放行前先确认账号仍可用。
    await user_status_service.ensure_active(user_id)
    start_date, end_date = range_
    items, total = billing_service.list_records(
        db,
        user_id,
        start_date=start_date,
        end_date=end_date,
        service_name=service_name,
        call_status=call_status,
        page=page,
        page_size=page_size,
    )
    return Result.ok(
        build_page_data(items, total, page, page_size), request_id=get_request_id()
    )


@router.get("/usage", response_model=Result)
async def get_usage(
    range_: tuple[date, date] = Depends(date_range),
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
) -> Result:
    """当前用户用量统计：汇总 + 按天 + 按服务。"""

    await user_status_service.ensure_active(user_id)
    start_date, end_date = range_
    data = billing_service.personal_usage(
        db, user_id, start_date=start_date, end_date=end_date
    )
    return Result.ok(data.model_dump(), request_id=get_request_id())


@router.get("/stat/overview", response_model=Result)
async def get_overview(
    range_: tuple[date, date] = Depends(date_range),
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
) -> Result:
    """运营全局统计：汇总（含去重用户数）+ 按天 + 按服务 + 用户排行。"""

    await user_status_service.ensure_admin(user_id)
    start_date, end_date = range_
    data = billing_service.overview(db, start_date=start_date, end_date=end_date)
    return Result.ok(data.model_dump(), request_id=get_request_id())
