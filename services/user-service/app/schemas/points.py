"""积分余额与流水的响应模型。金额一律整型，不使用浮点（指南 5.5）。"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import BaseOut


class PointsAccountOut(BaseOut):
    """积分余额。`frozen` 为冻结积分，当前版本不做冻结，恒为 0。"""

    user_id: int
    balance: int
    frozen: int = 0

    @classmethod
    def from_account(cls, account: object) -> "PointsAccountOut":
        return cls(
            user_id=account.user_id,
            balance=account.balance,
            frozen=account.frozen,
        )


class PointsLogOut(BaseOut):
    """积分流水项。"""

    id: int
    direction: str
    amount: int
    balance_after: int
    biz_type: str
    request_id: str
    remark: str
    create_time: datetime

    @classmethod
    def from_log(cls, log: object) -> "PointsLogOut":
        return cls(
            id=log.id,
            direction=log.direction,
            amount=log.amount,
            balance_after=log.balance_after,
            biz_type=log.biz_type,
            request_id=log.request_id,
            remark=log.remark,
            create_time=log.create_time,
        )


class PointsLogQuery(BaseModel):
    """流水查询条件；`direction` 为空表示不筛选方向。"""

    direction: str | None = Field(default=None)
