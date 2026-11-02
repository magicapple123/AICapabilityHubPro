"""供应商内部详情（D1/D2），供 capability-service 在**保存阶段**做绑定校验。

只返回协议与状态，**绝不返回密钥**（连密文都不返回）。
路径挂在 `/internal/provider/{alias}`，网关对外一律 403。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import UserContext, current_user
from app.core.logging import get_request_id
from app.core.result import Result
from app.db.session import get_db
from app.repository.provider_repository import provider_repository
from app.core.exceptions import BizException

router = APIRouter()



@router.get("/{alias}", response_model=Result)
async def get_provider(
    alias: str,
    user: UserContext = Depends(current_user),
    db: Session = Depends(get_db),
) -> Result:
    """按别名返回 `{alias, protocol, status, supports_models}`；不存在 2002。"""

    if not user.user_id:
        raise BizException(1001, "缺少可信链路身份")
    provider = provider_repository.find_by_alias(db, alias)
    if provider is None:
        raise BizException(2002, "供应商不存在")
    return Result.ok(
        {
            "alias": provider.alias,
            "protocol": provider.protocol,
            "status": provider.status,
            "default_model": provider.default_model,
        },
        request_id=get_request_id(),
    )
