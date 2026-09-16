"""内部记账接口（`POST /internal/billing/record`）的请求与响应模型。

入参字段与 ai-chat-service 的实际上报保持一致
（`services/ai-chat-service/app/service/chat_service.py`）：

```json
{
  "request_id": "<全链路 requestId>",
  "user_id": "1",
  "service_name": "ai-chat-service",
  "model": "mock-model",
  "points": 1,
  "status": "success"
}
```

`capability_id` 与 `duration_ms` 为可选扩展字段：当前 ai-chat 按“服务 + 固定单价”
上报，未携带能力 ID，因此 `capability_id` 缺省为 0（见 `app/core/constants.py`）。
"""

from datetime import date

from pydantic import BaseModel, Field

from app.core.constants import DEFAULT_CAPABILITY_ID, CallStatus


class BillingRecordRequest(BaseModel):
    """上报一次能力调用。`request_id` 是幂等键，重复上报只计一次费。"""

    request_id: str = Field(min_length=1, max_length=64)
    user_id: int = Field(ge=1)
    service_name: str = Field(default="", max_length=64)
    model: str = Field(default="", max_length=128)
    points: int = Field(default=0, ge=0, le=1_000_000, description="本次消耗积分")
    status: CallStatus = CallStatus.SUCCESS
    capability_id: int = Field(default=DEFAULT_CAPABILITY_ID, ge=0)
    duration_ms: int = Field(default=0, ge=0)
    remark: str = Field(default="", max_length=255)


class BillingRecordOut(BaseModel):
    """记账结果。

    `duplicated=true` 表示该 `request_id` 已记过账，本次为幂等重放：
    未再次扣分，`balance_after` 为首次扣分后的余额快照；
    `call_count` / `total_cost` 为该用户当日（`stat_date`）累计值。
    """

    record_id: int
    request_id: str
    user_id: int
    capability_id: int
    service_name: str
    cost: int
    call_status: str
    duplicated: bool = False
    balance_after: int | None = None
    stat_date: date
    call_count: int = 0
    total_cost: int = 0
