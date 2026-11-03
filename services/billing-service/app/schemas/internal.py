"""内部记账接口（`POST /internal/billing/record`）的请求与响应模型。

入参字段与 ai-chat-service 的实际上报保持一致
（`services/ai-chat-service/app/service/execution_billing.py`）：

```json
{
  "request_id": "<全链路 requestId>",
  "user_id": 1,
  "service_name": "ai-chat-service",
  "model": "mock-model",
  "billing_mode": "per_call",
  "unit_price": 5,
  "points": 5,
  "prompt_tokens": 12,
  "completion_tokens": 34,
  "token_source": "upstream",
  "status": "success"
}
```

`capability_id` 与 `duration_ms` 为可选扩展字段。旧的"按次"上报只需
`request_id / user_id / points / unit_price`，行为完全不变。
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.core.constants import DEFAULT_CAPABILITY_ID, BillingMode, CallStatus


class BillingImage(BaseModel):
    """图片产物（D3）。

    `url` 是上游返回的可访问地址；`revised_prompt` 是部分供应商（如百炼）
    返回的改写后提示词，没有时为空串。只保留这两个字段，不存二进制。
    """

    url: str = Field(min_length=1, max_length=2048)
    revised_prompt: str = Field(default="", max_length=2000)


class BillingRecordRequest(BaseModel):
    """上报一次能力调用。`request_id` 是幂等键，重复上报只计一次费。"""

    request_id: str = Field(min_length=1, max_length=64)
    user_id: int = Field(ge=1)
    service_name: str = Field(default="", max_length=64)
    model: str = Field(default="", max_length=128)
    unit_price: int | None = Field(default=None, strict=True, ge=0, le=1_000_000)
    points: int = Field(default=0, ge=0, le=1_000_000, description="本次消耗积分")
    status: CallStatus = CallStatus.SUCCESS
    capability_id: int = Field(default=DEFAULT_CAPABILITY_ID, ge=0)
    duration_ms: int = Field(default=0, ge=0)
    remark: str = Field(default="", max_length=255)
    # ---- C1/C2 扩展：缺省值保证旧调用方零改动 ----
    billing_mode: Literal["per_call", "per_token", "per_unit"] = BillingMode.PER_CALL
    prompt_tokens: int = Field(default=0, ge=0, le=100_000_000)
    completion_tokens: int = Field(default=0, ge=0, le=100_000_000)
    token_source: str = Field(default="unknown", max_length=16)
    units: int = Field(default=1, ge=1, le=1000)
    # 单价副本：让 billing 能**独立复算**一次实扣，防止上游算错价后静默记账。
    # 旧调用方不带这三个字段，此时跳过复算（保持历史语义）。
    price_per_1k_input: int | None = Field(default=None, ge=0, le=1_000_000)
    price_per_1k_output: int | None = Field(default=None, ge=0, le=1_000_000)
    price_per_unit: int | None = Field(default=None, ge=0, le=1_000_000)
    # ---- D3 扩展：文生图产物。
    # 只接受 {url, revised_prompt} 形状，最多 4 张（与 ImageInput.n 的上限一致），
    # URL 长度上限 2048，避免被当作任意大对象写入明细表。
    images: list[BillingImage] = Field(default_factory=list, max_length=4)
    # ---- P6 扩展：Key 归因与入口。旧调用方不带这两个字段，落库为 NULL/空串。
    # `api_key_id` 只接受正整数：None 表示"没有 Key 身份"（网页调试台 / 历史数据），
    # 不能把 0 当"未知 Key"写库，否则按 Key 聚合会多出一个假 Key。
    api_key_id: int | None = Field(default=None, ge=1)
    entrypoint: str = Field(default="", max_length=16)

    @model_validator(mode="after")
    def validate_price(self):
        """按计价模式校验"实扣金额"与"单价"的一致性。

        - `per_call`：沿用旧规则 `points == unit_price`（成功）/ `0`（失败）；
          旧调用方不带 `unit_price` 时不做金额校验，保持历史语义。
        - `per_token`：实扣必须等于按 token 明细复算的结果（带单价时），
          `unit_price` 不参与比对。
        - `per_unit`：`points == price_per_unit * units`（缺单价时用 `unit_price`）。
        """

        if self.billing_mode == BillingMode.PER_TOKEN.value:
            if self.status != CallStatus.SUCCESS:
                if self.points != 0:
                    raise ValueError("非成功调用不得扣费")
                return self
            if self.price_per_1k_input is not None and self.price_per_1k_output is not None:
                weighted = (
                    self.prompt_tokens * self.price_per_1k_input
                    + self.completion_tokens * self.price_per_1k_output
                )
                expected = -(-weighted // 1000) if weighted > 0 else 0
                if self.points != expected:
                    raise ValueError("按 token 计费的实际费用与 token 明细复算结果不一致")
            if self.prompt_tokens + self.completion_tokens <= 0:
                raise ValueError("按 token 计费必须携带 token 明细")
            return self
        if self.billing_mode == BillingMode.PER_UNIT.value:
            unit_price = (
                self.price_per_unit if self.price_per_unit is not None
                else (self.unit_price or 0)
            )
            expected = unit_price * self.units
            if self.status != CallStatus.SUCCESS:
                expected = 0
            if self.points != expected:
                raise ValueError("按件计价的实际费用与单价×数量不一致")
            return self
        if self.unit_price is not None:
            expected = self.unit_price if self.status == CallStatus.SUCCESS else 0
            if self.points != expected:
                raise ValueError("实际费用与登记单价/状态不一致")
        return self


class BillingRecordOut(BaseModel):
    """记账结果。

    `duplicated=true` 表示该 `request_id` 已记过账，本次为幂等重放：
    未再次扣分，`balance_after` 为首次扣分后的余额快照；
    `call_count` / `total_cost` 为该用户当日（`stat_date`）累计值。
    token 明细回显用于调用方核对（C1）。
    """

    record_id: int
    request_id: str
    user_id: int
    capability_id: int
    service_name: str
    unit_price: int | None = None
    cost: int
    call_status: str
    duplicated: bool = False
    balance_after: int | None = None
    stat_date: date
    call_count: int = 0
    total_cost: int = 0
    billing_mode: str = BillingMode.PER_CALL.value
    prompt_tokens: int = 0
    completion_tokens: int = 0
    token_source: str = ""
    units: int = 1
    # D3：回显图片产物，调用方据此核对"记录里存的图"和"当次返回的图"一致。
    images: list[BillingImage] = Field(default_factory=list)
