"""运营审计查询接口（B1）。

**只提供 GET**：应用层不提供更新与删除接口，历史记录无法被改写。
权限复用 `require_admin`（实时向 user-service 校验），失败关闭。
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.deps import require_admin
from app.core.logging import get_request_id
from app.core.result import Result
from app.db.session import get_db
from app.core.exceptions import BizException
from app.schemas import PAGE_SIZE_MAX, AuditLogOut, build_page_data
from app.service.audit_service import audit_service

router = APIRouter()

# 审计列表默认 20 条（比目录页的 10 条更贴近排查场景）。
AUDIT_PAGE_SIZE_DEFAULT = 20


@router.get("/audit", response_model=Result)
async def list_audit_logs(
    resource_type: str | None = Query(default=None, max_length=32),
    resource_id: str | None = Query(default=None, max_length=64),
    action: str | None = Query(default=None, max_length=32),
    operator_id: str | None = Query(default=None, max_length=64),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=AUDIT_PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Result:
    """按资源 / 动作 / 操作人 / 时间区间筛选，按 id 倒序分页。"""

    if start_date and end_date and start_date > end_date:
        raise BizException(2001, "开始日期不能晚于结束日期")
    rows, total = audit_service.list_logs(
        db,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        operator_id=operator_id,
        start_date=start_date,
        end_date=end_date,
        page=page,
        page_size=page_size,
    )
    return Result.ok(
        build_page_data(
            [AuditLogOut.model_validate(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        ),
        request_id=get_request_id(),
    )
