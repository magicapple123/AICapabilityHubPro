"""运营后台跨用户查询接口，挂载前缀 `/api/billing/admin`（F1）。

与 `/api/billing/records`、`/api/billing/usage` 的区别只有两点：
**目标用户由路径/参数指定**，以及**调用方必须是管理员**。统计口径完全复用
`billing_service` 的个人查询逻辑，避免管理端与用户端看到两套数字。

权限：复用 `user_status_service.ensure_admin`（实时向 user-service 求授权，
失败关闭）。普通用户在这里统一映射为平台运营口径的 `2007`（与
capability-service 一致），user-service 中原生的 `1006` 语义仍在 Key 端点保留。
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.deps import call_status_filter, current_user_id, date_range
from app.core.exceptions import BizException
from app.core.logging import get_request_id
from app.core.result import Result
from app.db.session import get_db
from app.schemas import PAGE_SIZE_DEFAULT, PAGE_SIZE_MAX, build_page_data
from app.service import billing_service, user_status_service

router = APIRouter()

ADMIN_ONLY_CODE = 2007
ADMIN_ONLY_MESSAGE = "无运营权限，仅管理员可执行该操作"


async def _ensure_admin(user_id: int) -> None:
    """管理员校验；把 user 侧的 `1006 权限不足` 归一成运营口径的 `2007`。"""

    try:
        await user_status_service.ensure_admin(user_id)
    except BizException as error:
        if error.code == 1006:
            raise BizException(ADMIN_ONLY_CODE, ADMIN_ONLY_MESSAGE) from None
        raise


@router.get("/records", response_model=Result)
async def admin_records(
    user_id: int = Query(..., ge=1, description="目标用户 ID"),
    range_: tuple[date, date] = Depends(date_range),
    service_name: str | None = Query(
        default=None, max_length=64, description="按承载服务名精确筛选"
    ),
    call_status: str | None = Depends(call_status_filter),
    api_key_id: int | None = Query(
        default=None, ge=1, description="按 API Key 归因筛选（P6）"
    ),
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
    caller_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
) -> Result:
    """跨用户调用明细分页；只返回元数据，不含会话正文。"""

    await _ensure_admin(caller_id)
    start_date, end_date = range_
    items, total = billing_service.list_records(
        db,
        user_id,
        start_date=start_date,
        end_date=end_date,
        service_name=service_name,
        call_status=call_status,
        api_key_id=api_key_id,
        page=page,
        page_size=page_size,
    )
    return Result.ok(
        build_page_data(items, total, page, page_size), request_id=get_request_id()
    )


@router.get("/users/usage", response_model=Result)
async def admin_users_usage(
    range_: tuple[date, date] = Depends(date_range),
    caller_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
) -> Result:
    """全量用户用量聚合（P5）。

    为什么一次返回全量而不是分页：用户资料在 user-service、消耗在 billing_db，
    服务端排序等于跨服务 join。当前规模（≤2000 用户）由前端 join 后排序分页，
    超过该量级必须改成 billing 主导分页 + user-service 批量补资料（契约 A2 路径）。
    """

    await _ensure_admin(caller_id)
    start_date, end_date = range_
    items = billing_service.user_aggregates(
        db, start_date=start_date, end_date=end_date
    )
    return Result.ok(
        {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "list": [item.model_dump(mode="json") for item in items],
        },
        request_id=get_request_id(),
    )


@router.get("/users/{user_id}/keys-usage", response_model=Result)
async def admin_user_key_usage(
    user_id: int,
    range_: tuple[date, date] = Depends(date_range),
    caller_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
) -> Result:
    """某用户按 API Key 的调用分布（P6）；只返回 Key ID 与用量，不返回密钥材料。

    Key 名称由前端用 user-service 的 Key 列表补齐：billing 不认识 Key 名，
    也不该为展示名去跨库读 user_db。
    """

    await _ensure_admin(caller_id)
    start_date, end_date = range_
    items = billing_service.key_usage(
        db, user_id, start_date=start_date, end_date=end_date
    )
    return Result.ok(
        {
            "user_id": user_id,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "list": [item.model_dump(mode="json") for item in items],
        },
        request_id=get_request_id(),
    )


@router.get("/users/{user_id}/usage", response_model=Result)
async def admin_user_usage(
    user_id: int,
    range_: tuple[date, date] = Depends(date_range),
    caller_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
) -> Result:
    """指定用户近 30 天（可传日期覆盖）用量：汇总 + 按天 + 按服务。"""

    await _ensure_admin(caller_id)
    start_date, end_date = range_
    data = billing_service.personal_usage(
        db, user_id, start_date=start_date, end_date=end_date
    )
    return Result.ok(data.model_dump(), request_id=get_request_id())
