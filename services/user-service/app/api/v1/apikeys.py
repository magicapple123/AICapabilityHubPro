"""API Key 接口，挂载前缀 `/api/user/apikeys`。均需要登录。

完整 `secret_key` 只在 `POST` 的响应中出现一次；列表与禁用接口只返回展示掩码。
"""

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.v1.deps import current_user_id
from app.core.logging import get_request_id
from app.core.result import Result
from app.db.session import get_db
from app.schemas.apikey import ApiKeyExchangeRequest
from app.schemas import (
    ApiKeyCreateRequest,
    ApiKeyCreatedOut,
    ApiKeyOut,
    ApiKeyStatusOut,
    build_list_data,
)
from app.service import api_key_service

router = APIRouter()


@router.get("", response_model=Result)
async def list_api_keys(
    user_id: int = Depends(current_user_id), db: Session = Depends(get_db)
) -> Result:
    """当前用户的 Key 列表；按创建时间倒序，只含掩码。"""

    keys = api_key_service.list_keys(db, user_id)
    return Result.ok(
        build_list_data([ApiKeyOut.from_api_key(item) for item in keys]),
        request_id=get_request_id(),
    )


@router.post("", response_model=Result)
async def create_api_key(
    payload: ApiKeyCreateRequest,
    response: Response,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
) -> Result:
    """创建 Key；`secret_key` 仅本次返回，请提示用户立即保存。"""

    response.headers["Cache-Control"] = "no-store"
    api_key, secret_key = api_key_service.create(db, user_id, payload)
    return Result.ok(
        ApiKeyCreatedOut(
            id=api_key.id,
            name=api_key.name,
            access_key=api_key.access_key,
            secret_mask=api_key.secret_mask,
            status=api_key.status,
            expire_time=api_key.expire_time,
            create_time=api_key.create_time,
            secret_key=secret_key,
        ).model_dump(),
        request_id=get_request_id(),
    )


@router.put("/{api_key_id}/disable", response_model=Result)
async def disable_api_key(
    api_key_id: int,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
) -> Result:
    """禁用指定 Key；重复禁用幂等，他人 Key 与不存在的 Key 一律返回 1006。"""

    api_key = api_key_service.disable(db, user_id, api_key_id)
    return Result.ok(
        ApiKeyStatusOut(id=api_key.id, update_time=api_key.update_time).model_dump(),
        request_id=get_request_id(),
    )


@router.post("/exchange", response_model=Result)
async def exchange_api_key(payload: ApiKeyExchangeRequest, response: Response,
                           db: Session = Depends(get_db)) -> Result:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Pragma"] = "no-cache"
    return Result.ok(api_key_service.exchange(db, payload), request_id=get_request_id())
