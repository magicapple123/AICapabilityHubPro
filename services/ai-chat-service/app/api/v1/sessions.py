from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.exceptions import BizException
from app.core.logging import get_request_id
from app.core.result import Result
from app.core.security import UserContext, current_user
from app.core.config import settings
from app.core.service_call import call_internal
from app.db.session import get_db
from app.repository.chat_repository import chat_repository
from app.schemas.session import ChatMessageResponse, ChatSessionResponse


router = APIRouter()


async def _required_user(user: UserContext) -> str:
    if not user.user_id or not user.user_id.isdigit() or int(user.user_id) <= 0:
        raise BizException(1001, "未认证或登录已过期")
    # JWT 只证明签名与有效期；只读接口也必须查账号当前状态，不能靠扣费预检。
    # 此检查独立于 enable_internal_chain，关闭计费链不应绕过账号禁用。
    status = await call_internal(
        settings.user_service_name, "GET", "/internal/user/check",
        params={"user_id": user.user_id, "points_cost": 0},
        headers={"X-User-Id": user.user_id, "X-User-Name": user.user_name,
                 "X-Request-Id": user.request_id or get_request_id()},
    )
    if not isinstance(status, dict) or status.get("user_id") != int(user.user_id):
        raise BizException(4002, "用户状态响应格式错误")
    if status.get("status") != "normal":
        raise BizException(1005, "用户不存在或已被禁用")
    return user.user_id


@router.get("/sessions", response_model=Result)
async def list_sessions(
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=20, ge=1, le=100),
    user: UserContext = Depends(current_user),
    db: Session = Depends(get_db),
) -> Result:
    """当前用户的会话列表，按最后消息时间倒序。"""

    user_id = await _required_user(user)
    sessions, total = chat_repository.list_sessions(
        db, user_id, page=page, page_size=page_size
    )
    data = {
        "list": [
            ChatSessionResponse.model_validate(item).model_dump(mode="json")
            for item in sessions
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
    return Result.ok(data, request_id=get_request_id())


@router.get("/sessions/{session_id}/messages", response_model=Result)
async def list_messages(
    session_id: int,
    user: UserContext = Depends(current_user),
    db: Session = Depends(get_db),
) -> Result:
    """会话内的消息列表；会话不存在或不属于当前用户返回 4004。"""

    user_id = await _required_user(user)
    session = chat_repository.find_session(db, user_id, session_id)
    if session is None:
        raise BizException(4004, "会话不存在或不属于当前用户")
    messages = chat_repository.list_messages(db, session)
    data = {
        "list": [
            ChatMessageResponse.model_validate(item).model_dump(mode="json")
            for item in messages
        ],
        "total": len(messages),
    }
    return Result.ok(data, request_id=get_request_id())
