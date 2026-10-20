"""服务间内部接口，挂载前缀 `/internal/user`。

调用方链路（指南 11.2）：

    ai-chat → GET  /internal/user/check          校验用户状态与积分
    billing → POST /internal/user/points/deduct  乐观锁扣分并写流水

网关对外部访问 `/internal/**` 一律 403，因此这里不做 JWT 解析，但必须校验
`X-User-Id`（身份）与 `X-Request-Id`（幂等键），见 `app/api/v1/deps.py`。
"""

from typing import Literal

from app.core.exceptions import BizException
from app.service.user_service import require_available_user

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.deps import internal_caller
from app.core.logging import get_request_id
from app.core.result import Result
from app.core.security import UserContext
from app.db.session import get_db
from app.schemas import PointsDeductRequest
from app.service import points_service

router = APIRouter()


@router.get("/check", response_model=Result)
async def check_user(
    user_id: int = Query(ge=1, description="目标用户 ID"),
    points_cost: int = Query(default=0, ge=0, description="本次预计消耗积分"),
    caller: UserContext = Depends(internal_caller),
    db: Session = Depends(get_db),
) -> Result:
    """校验用户是否可调用能力并返回可用积分。

    错误码：`1005` 用户不存在或已被禁用；`3001` 积分不足（执行前拦截）。
    """

    if caller.user_id != str(user_id):
        raise BizException(1001, "缺少或伪造的链路身份")
    data = points_service.check(db, user_id, points_cost)
    return Result.ok(data, request_id=caller.request_id or get_request_id())


@router.post("/points/deduct", response_model=Result)
async def deduct_points(
    payload: PointsDeductRequest,
    caller: UserContext = Depends(internal_caller),
    db: Session = Depends(get_db),
) -> Result:
    """乐观锁扣分并写流水；同一 requestId 幂等，不会二次扣分。

    错误码：`1001` 链路身份与目标用户不一致；`1005` 用户不存在或已被禁用；
    `3001` 积分不足（此时流水一并回滚，不留半成功状态）。
    """

    data = points_service.deduct(db, payload, caller.user_id)
    return Result.ok(data.model_dump(), request_id=caller.request_id or get_request_id())


@router.get("/authorization", response_model=Result)
async def authorization(
    user_id: int = Query(ge=1),
    required_role: Literal["admin"] = Query(...),
    caller: UserContext = Depends(internal_caller),
    db: Session = Depends(get_db),
) -> Result:
    if caller.user_id != str(user_id):
        raise BizException(1001, "缺少或伪造的链路身份")
    user = require_available_user(db, user_id)
    if user.role != required_role:
        raise BizException(1006, "权限不足")
    return Result.ok({"user_id": user.id, "status": user.status, "role": user.role,
                      "authorized": True}, request_id=caller.request_id)
