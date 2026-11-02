"""供应商管理接口（D1），挂载前缀 `/api/chat/providers`。

权限复用 user-service 的实时管理员校验（与 capability 的运营接口同源），
普通用户 2007、依赖不可用 4002，失败关闭。

安全：响应永不含密钥明文或密文，只回 `api_key_mask`。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.exceptions import BizException
from app.core.logging import get_request_id
from app.core.result import Result
from app.core.security import UserContext, current_user
from app.db.session import get_db
from app.schemas.provider import (
    ProviderCreateRequest,
    ProviderOut,
    ProviderUpdateRequest,
)
from app.core.constants import ProviderStatus
from app.service import authorization_service
from app.service.provider_service import provider_service

router = APIRouter()


async def require_admin(user: UserContext = Depends(current_user)) -> str:
    if not user.user_id:
        raise BizException(1001, "未认证或登录已过期")
    await authorization_service.require_admin(user.user_id)
    return user.user_id


def _out(provider) -> dict:
    return ProviderOut.model_validate(provider).model_dump(mode="json")


@router.get("", response_model=Result)
async def list_providers(
    _: str = Depends(require_admin), db: Session = Depends(get_db)
) -> Result:
    """供应商列表；只返回掩码后的密钥。"""

    rows = provider_service.list_providers(db)
    return Result.ok({"list": [_out(row) for row in rows], "total": len(rows)},
                     request_id=get_request_id())


@router.post("", response_model=Result)
async def create_provider(
    payload: ProviderCreateRequest,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Result:
    """登记供应商；地址不安全或不白名单 2001，别名重复 2006，永远是草稿态。"""

    created = provider_service.create_provider(db, payload)
    return Result.ok(_out(created), request_id=get_request_id())


@router.put("/{provider_id}", response_model=Result)
async def update_provider(
    provider_id: int,
    payload: ProviderUpdateRequest,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Result:
    """编辑供应商；换密钥会把启用态退回草稿，强制重新测通。"""

    updated = provider_service.update_provider(db, provider_id, payload)
    return Result.ok(_out(updated), request_id=get_request_id())


@router.post("/{provider_id}/test", response_model=Result)
async def test_provider(
    provider_id: int,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Result:
    """连通性测试；通过后记录 `last_test_ok_at`，才允许启用。"""

    result = await provider_service.test_provider(db, provider_id)
    return Result.ok(result.model_dump(), request_id=get_request_id())


@router.put("/{provider_id}/status", response_model=Result)
async def set_provider_status(
    provider_id: int,
    payload: dict,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Result:
    """启用/停用/退回草稿；未测通直接启用返回 2001。"""

    status = str(payload.get("status") or "").strip()
    if status not in {item.value for item in ProviderStatus}:
        raise BizException(2001, "供应商状态只能是 draft/enabled/disabled")
    updated = provider_service.set_status(db, provider_id, status)
    return Result.ok(_out(updated), request_id=get_request_id())
