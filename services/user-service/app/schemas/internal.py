"""服务间内部接口（`/internal/**`）的请求与响应模型。

这些接口只允许其它后端服务通过基座 `call_internal` 调用：
网关对外部访问 `/internal/**` 一律返回 403，因此内部接口不再重复解析 JWT，
但必须校验链路身份（`X-User-Id`）与幂等键（`X-Request-Id`），见
`docs/api-contract/user-service.md` 第 4 节。
"""

from pydantic import BaseModel, Field

from app.core.constants import PointBizType, PointDirection


class UserCheckOut(BaseModel):
    """`GET /internal/user/check` 出参：用户状态 + 可用积分。"""

    user_id: int
    username: str
    status: str
    balance: int
    points_cost: int
    available: bool


class PointsDeductRequest(BaseModel):
    """`POST /internal/user/points/deduct` 入参。

    `request_id` 由上游（billing-service）透传全链路 requestId，作为扣分幂等键。
    """

    user_id: int = Field(ge=1)
    amount: int = Field(ge=1, description="扣减积分数量，必须为正整数")
    biz_type: PointBizType = PointBizType.CALL
    request_id: str = Field(min_length=1, max_length=64)
    remark: str = Field(default="", max_length=255)


class PointsDeductOut(BaseModel):
    """扣分结果。

    `duplicated=true` 表示该 requestId 已经扣过分，本次为幂等重放：
    余额未再减少，`balance_after` 为首次扣分后的余额快照。
    """

    user_id: int
    amount: int
    balance_after: int
    direction: str = PointDirection.OUT.value
    duplicated: bool = False
