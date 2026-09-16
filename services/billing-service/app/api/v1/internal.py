"""服务间内部接口，挂载前缀 `/internal/billing`。

调用方链路（指南 11.2）：

    ai-chat → POST /internal/billing/record   上报一次调用，幂等

网关对外部访问 `/internal/**` 一律 403，因此这里不做 JWT 解析，但必须校验
`X-User-Id`（身份）与 `X-Request-Id`（幂等键，与 body 中的 request_id 一致）。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.deps import internal_caller
from app.core.logging import get_request_id
from app.core.result import Result
from app.core.security import UserContext
from app.db.session import get_db
from app.schemas import BillingRecordRequest
from app.service import billing_service

router = APIRouter()


@router.post("/record", response_model=Result)
async def record_call(
    payload: BillingRecordRequest,
    caller: UserContext = Depends(internal_caller),
    db: Session = Depends(get_db),
) -> Result:
    """上报调用并完成扣分与用量累计。

    错误码：`1001` 链路身份与目标用户不一致；`3001` 积分不足；
    `3002` 同一 requestId 被不同调用占用；`4002` user-service 不可用。
    """

    data = await billing_service.record(db, payload, caller.user_id)
    return Result.ok(data.model_dump(), request_id=caller.request_id or get_request_id())
