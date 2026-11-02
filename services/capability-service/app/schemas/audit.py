"""审计响应模型（B1）。

只读：没有任何 update / delete 的请求模型，也没有写入出参。
"""

from datetime import datetime

from pydantic import ConfigDict

from app.schemas.common import BaseOut


class AuditLogOut(BaseOut):
    """一条运营操作记录；`before_json` / `after_json` 已脱敏。"""

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
