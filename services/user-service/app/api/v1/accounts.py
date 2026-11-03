"""注册、登录与资料接口，挂载前缀 `/api/user`。

`/api/user/register` 与 `/api/user/login` 属网关白名单（精确匹配，不带尾斜杠），
其余接口需要网关 JWT；身份一律取网关注入的 `X-User-Id`，不在服务内解析 Token。
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.v1.deps import current_user_id
from app.core.logging import get_request_id
from app.core.result import Result
from app.db.session import get_db
from app.schemas import (
    LoginOut,
    LoginRequest,
    ProfileOut,
    ProfileUpdateRequest,
    RegisterOut,
    RegisterRequest,
)
from app.service import user_service

router = APIRouter()


@router.post("/register", response_model=Result)
async def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> Result:
    """注册并创建积分账户、赠送初始积分；用户名重复返回 1004。"""

    user, account = user_service.register(db, payload)
    return Result.ok(
        RegisterOut(
            user_id=user.id,
            username=user.username,
            role=user.role,
            nickname=user.nickname,
            balance=account.balance,
            initial_points=account.balance,
        ).model_dump(),
        request_id=get_request_id(),
    )


@router.post("/login", response_model=Result)
async def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> Result:
    """签发 JWT；凭据错1003，账号禁用1005，失败窗口锁定4001。"""

    # 只信直接连接地址；外部可伪造的 Forwarded/X-Forwarded-For 不参与绕过限流。
    peer_ip = request.client.host if request.client else "unknown"
    user, token, expire_at = user_service.login(db, payload, peer_ip=peer_ip)
    return Result.ok(
        LoginOut(
            token=token,
            expire_at=expire_at,
            user_id=user.id,
            username=user.username,
            role=user.role,
        ).model_dump(),
        request_id=get_request_id(),
    )


@router.get("/profile", response_model=Result)
async def get_profile(
    user_id: int = Depends(current_user_id), db: Session = Depends(get_db)
) -> Result:
    """读取当前用户资料；不返回密码哈希等敏感字段。"""

    user = user_service.get_profile(db, user_id)
    return Result.ok(
        ProfileOut.from_user(user).model_dump(), request_id=get_request_id()
    )


@router.put("/profile", response_model=Result)
async def update_profile(
    payload: ProfileUpdateRequest,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
) -> Result:
    """更新当前用户昵称；幂等。"""

    user = user_service.update_profile(db, user_id, payload)
    return Result.ok(
        ProfileOut.from_user(user).model_dump(), request_id=get_request_id()
    )
