"""F1 运营后台的响应模型。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.common import BaseOut


class AdminUserOut(BaseOut):
    """用户列表项；`balance` 与 `daily_points_limit` 来自积分账户与用户设置。"""

    id: int
    username: str
    nickname: str
    role: str
    status: str
    balance: int
    daily_points_limit: int
    create_time: datetime


class AuditLogOut(BaseOut):
    """一条运营审计；`before_json`/`after_json` 已脱敏。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    operator_id: str
    operator_name: str
    resource_type: str
    resource_id: str
    action: str
    before_json: dict | None = None
    after_json: dict | None = None
    request_id: str
    create_time: datetime
