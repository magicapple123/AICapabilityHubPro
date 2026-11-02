"""运营操作审计（B1 同构表，落 user_db）。

与 capability 的实现保持同一套字段与语义：
- 一库一张同构表，四库物理隔离、不跨库查询；
- 只追加：本模块没有 update/delete，接口只暴露 GET；
- **同事务**：调用方先 `stage()` 把审计行挂进 session，业务操作的 commit 会一并提交，
  业务失败则一起回滚，不会出现"改了没留痕"或"留痕了没改成"。
"""

from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import UserContext
from app.models import OperationLog

SENSITIVE_KEYWORDS = ("password", "passwd", "secret", "api_key", "apikey", "token", "cipher")
MASK = "***"

ACTION_UPDATE = "update"
ACTION_STATUS = "status"
ACTION_ADJUST_POINTS = "adjust_points"
ACTION_EXPORT = "export"

RESOURCE_USER = "user"
RESOURCE_POINTS = "points"


def sanitize(payload: dict | None) -> dict | None:
    if payload is None or not isinstance(payload, dict):
        return payload
    cleaned: dict = {}
    for key, value in payload.items():
        if any(word in str(key).lower() for word in SENSITIVE_KEYWORDS):
            cleaned[key] = MASK
        elif isinstance(value, dict):
            cleaned[key] = sanitize(value)
        else:
            cleaned[key] = value
    return cleaned


def stage(
    db: Session,
    *,
    actor: UserContext,
    resource_type: str,
    resource_id: int | str,
    action: str,
    before: dict | None,
    after: dict | None,
) -> None:
    """把审计行挂进当前事务；由业务操作的 commit 一起提交。"""

    db.add(
        OperationLog(
            operator_id=str(actor.user_id),
            operator_name=actor.user_name or "",
            resource_type=resource_type,
            resource_id=str(resource_id),
            action=action,
            before_json=sanitize(before),
            after_json=sanitize(after),
            request_id=actor.request_id or "",
        )
    )


class AuditService:
    def list_logs(
        self,
        db: Session,
        *,
        resource_type: str | None = None,
        resource_id: str | None = None,
        action: str | None = None,
        operator_id: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[OperationLog], int]:
        conditions: list[object] = []
        if resource_type:
            conditions.append(OperationLog.resource_type == resource_type)
        if resource_id:
            conditions.append(OperationLog.resource_id == str(resource_id))
        if action:
            conditions.append(OperationLog.action == action)
        if operator_id:
            conditions.append(OperationLog.operator_id == operator_id)
        if start_date:
            conditions.append(OperationLog.create_time >= datetime.combine(start_date, time.min))
        if end_date:
            conditions.append(
                OperationLog.create_time
                < datetime.combine(end_date + timedelta(days=1), time.min)
            )
        total = db.scalar(select(func.count(OperationLog.id)).where(*conditions)) or 0
        rows = db.scalars(
            select(OperationLog)
            .where(*conditions)
            .order_by(OperationLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return list(rows), total


audit_service = AuditService()
