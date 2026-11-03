"""F1 运营后台用户管理接口，挂载前缀 `/api/user/admin`。

管理员判定在**本服务内**完成（读自己的库，不绕远端）：
账号不可用返回1005；正常账号仅 `role='admin'` 放行，其余2007。
之所以不像 capability 那样调远端授权：user-service 就是授权数据的持有方，
自调用只会多一次网络跳转和一个自依赖故障点。
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.exceptions import BizException
from app.core.logging import get_request_id
from app.core.result import Result
from app.core.security import UserContext, current_user
from app.db.session import get_db
from app.schemas import PAGE_SIZE_DEFAULT, PAGE_SIZE_MAX, build_page_data
from app.schemas.admin import AdminUserOut, AuditLogOut
from app.service.audit_service import audit_service
from app.service.admin_service import admin_service
from app.service.user_service import require_available_user

router = APIRouter()

ADMIN_ONLY_MESSAGE = "无运营权限，仅管理员可执行该操作"
AUDIT_PAGE_SIZE_DEFAULT = 20
# P5「用户与用量」合并页要一次拿到全量用户，再与 billing 的消耗聚合按 user_id join。
# 这是**仅管理端列表**的放宽（普通分页仍按契约上限 100），边界是 2000 用户；
# 超过该量级必须改成 billing 主导分页 + user-service 批量补资料（契约 A2 路径）。
ADMIN_USER_PAGE_SIZE_MAX = 2000


def _require_admin(user: UserContext, db: Session) -> UserContext:
    if not user.user_id or not str(user.user_id).isdigit():
        raise BizException(1001, "未认证或登录已过期")
    row = require_available_user(db, int(user.user_id))
    if row.role != "admin":
        raise BizException(2007, ADMIN_ONLY_MESSAGE)
    return user


class AdminStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(pattern="^(normal|disabled)$")


class AdminPointsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: int = Field(ge=-1_000_000, le=1_000_000)
    reason: str = Field(min_length=1, max_length=200)


class AdminBudgetRequest(BaseModel):
    """P10：日预算。`0` 表示不限，与列表里"不限"的展示口径一致。"""

    model_config = ConfigDict(extra="forbid")
    daily_points_limit: int = Field(ge=0, le=1_000_000)


@router.get("/users", response_model=Result)
async def list_users(
    keyword: str | None = Query(default=None, max_length=64),
    status: str | None = Query(default=None, pattern="^(normal|disabled)$"),
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(
        default=PAGE_SIZE_DEFAULT, ge=1, le=ADMIN_USER_PAGE_SIZE_MAX
    ),
    user: UserContext = Depends(current_user),
    db: Session = Depends(get_db),
) -> Result:
    """用户列表（含余额与日预算）；支持 ID/用户名/昵称搜索与状态筛选。"""

    _require_admin(user, db)
    items, total = admin_service.list_users(
        db, keyword=keyword, status=status, page=page, page_size=page_size
    )
    return Result.ok(
        build_page_data(
            [AdminUserOut(**item) for item in items],
            total=total, page=page, page_size=page_size,
        ),
        request_id=get_request_id(),
    )


@router.get("/users/export", response_class=PlainTextResponse)
async def export_users(
    keyword: str | None = Query(default=None, max_length=64),
    status: str | None = Query(default=None, pattern="^(normal|disabled)$"),
    user: UserContext = Depends(current_user),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    """导出 CSV；内容与服务端筛选条件一致，不带任何密钥字段。"""

    _require_admin(user, db)
    content = admin_service.export_csv(db, keyword=keyword, status=status)
    return PlainTextResponse(
        content="\ufeff" + content,  # BOM 让 Excel 正确识别 UTF-8 中文
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="users.csv"',
            "X-Request-Id": get_request_id(),
        },
    )


@router.get("/users/{user_id}", response_model=Result)
async def user_detail(
    user_id: int,
    user: UserContext = Depends(current_user),
    db: Session = Depends(get_db),
) -> Result:
    """用户详情；`usage` 取自 billing 的统计口径，对端不可用时为 null。"""

    _require_admin(user, db)
    return Result.ok(
        await admin_service.detail(db, user_id), request_id=get_request_id()
    )


@router.put("/users/{user_id}/status", response_model=Result)
async def set_user_status(
    user_id: int,
    payload: AdminStatusRequest,
    user: UserContext = Depends(current_user),
    db: Session = Depends(get_db),
) -> Result:
    """启用 / 禁用账号；禁用后该用户所有受保护接口返回 1005。"""

    _require_admin(user, db)
    data = admin_service.set_status(db, user, user_id, payload.status)
    return Result.ok(data, request_id=get_request_id())


@router.post("/users/{user_id}/points", response_model=Result)
async def adjust_points(
    user_id: int,
    payload: AdminPointsRequest,
    user: UserContext = Depends(current_user),
    db: Session = Depends(get_db),
) -> Result:
    """人工调分；必须填原因，写入 `admin_adjust` 流水与审计。"""

    _require_admin(user, db)
    data = admin_service.adjust_points(
        db, user, user_id, payload.amount, payload.reason
    )
    return Result.ok(data, request_id=get_request_id())


@router.put("/users/{user_id}/budget", response_model=Result)
async def set_user_budget(
    user_id: int,
    payload: AdminBudgetRequest,
    user: UserContext = Depends(current_user),
    db: Session = Depends(get_db),
) -> Result:
    """设置日预算（P10）：0 = 不限；变更写审计（`resource_type=user, action=budget`）。"""

    _require_admin(user, db)
    data = admin_service.set_budget(
        db, user, user_id, payload.daily_points_limit
    )
    return Result.ok(data, request_id=get_request_id())


@router.get("/audit", response_model=Result)
async def list_audit(
    resource_type: str | None = Query(default=None, max_length=32),
    resource_id: str | None = Query(default=None, max_length=64),
    action: str | None = Query(default=None, max_length=32),
    operator_id: str | None = Query(default=None, max_length=64),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=AUDIT_PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
    user: UserContext = Depends(current_user),
    db: Session = Depends(get_db),
) -> Result:
    """用户侧运营审计（只读）；与 capability 的审计同构、各自独立。"""

    _require_admin(user, db)
    if start_date and end_date and start_date > end_date:
        raise BizException(2001, "开始日期不能晚于结束日期")
    rows, total = audit_service.list_logs(
        db, resource_type=resource_type, resource_id=resource_id, action=action,
        operator_id=operator_id, start_date=start_date, end_date=end_date,
        page=page, page_size=page_size,
    )
    return Result.ok(
        build_page_data(
            [AuditLogOut.model_validate(row) for row in rows],
            total=total, page=page, page_size=page_size,
        ),
        request_id=get_request_id(),
    )
