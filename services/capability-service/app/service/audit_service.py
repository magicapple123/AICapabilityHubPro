"""运营操作审计；只追加、不修改、不删除（B1）。

设计要点：
- **一库一张同构表**：capability 的运营写操作落 `capability_db`，user-service 的
  用户管理写操作落 `user_db`（批 5 建同构表）。四库物理隔离，不跨库查询。
- **只追加**：本模块与 repository 都不提供 update / delete；接口只暴露 `GET`。
- **同事务**：审计行与业务写在同一个 `db.commit()` 内提交，
  避免"改价成功但没留痕"或"留痕了但改价失败"两种半成功状态。
"""

from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import UserContext
from app.models import OperationLog

# 敏感字段一律脱敏后落库，审计日志本身不能成为泄漏源。
SENSITIVE_KEYWORDS = ("password", "passwd", "secret", "api_key", "apikey", "token", "cipher")
MASK = "***"

# 允许的动作；新增动作必须同步更新契约文档。
ACTION_CREATE = "create"
ACTION_UPDATE = "update"
ACTION_STATUS = "status"
ACTION_DELETE = "delete"
ACTION_ROLLBACK = "rollback"

RESOURCE_CAPABILITY = "capability"
RESOURCE_CATEGORY = "category"
RESOURCE_USER = "user"
RESOURCE_POINTS = "points"
RESOURCE_APIKEY = "apikey"


def sanitize(payload: dict | None) -> dict | None:
    """递归脱敏；键名命中敏感词的值替换为 `***`，其余原样保留。"""

    if payload is None:
        return None
    if not isinstance(payload, dict):
        return payload
    cleaned: dict = {}
    for key, value in payload.items():
        if any(word in str(key).lower() for word in SENSITIVE_KEYWORDS):
            cleaned[key] = MASK
        elif isinstance(value, dict):
            cleaned[key] = sanitize(value)
        elif isinstance(value, list):
            cleaned[key] = [sanitize(item) if isinstance(item, dict) else item for item in value]
        else:
            cleaned[key] = value
    return cleaned


def snapshot(obj: object, fields: tuple[str, ...]) -> dict:
    """按白名单字段取快照，避免把 ORM 全量属性（含内部配置）写进审计。"""

    return {field: getattr(obj, field, None) for field in fields}


CAPABILITY_AUDIT_FIELDS = (
    "category_id", "name", "code", "service_name", "path", "param_schema",
    "price_per_call", "billing_mode", "price_per_1k_input", "price_per_1k_output",
    "price_per_unit", "unit", "status", "description",
)
CATEGORY_AUDIT_FIELDS = ("name", "code", "sort", "status")


def build_entry(
    *,
    actor: UserContext | None,
    resource_type: str,
    resource_id: int | str,
    action: str,
    before: dict | None,
    after: dict | None,
) -> OperationLog | None:
    """构造待落库的审计行；没有操作者身份时返回 None（内部调用不留痕）。"""

    if actor is None or not actor.user_id:
        return None
    return OperationLog(
        operator_id=str(actor.user_id),
        operator_name=actor.user_name or "",
        resource_type=resource_type,
        resource_id=str(resource_id),
        action=action,
        before_json=sanitize(before),
        after_json=sanitize(after),
        request_id=actor.request_id or "",
    )


class AuditService:
    def find_by_id(self, db, audit_id: int):
        """取单条审计（回滚按 id 定位）。"""

        from sqlalchemy import select

        return db.scalar(select(OperationLog).where(OperationLog.id == audit_id))

    """审计查询；没有写入方法，写入由各 repository 在同一事务内完成。"""

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
            conditions.append(
                OperationLog.create_time >= datetime.combine(start_date, time.min)
            )
        if end_date:
            conditions.append(
                OperationLog.create_time
                < datetime.combine(end_date + timedelta(days=1), time.min)
            )

        total = db.scalar(select(func.count(OperationLog.id)).where(*conditions)) or 0
        statement = (
            select(OperationLog)
            .where(*conditions)
            .order_by(OperationLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(db.scalars(statement).all()), total


audit_service = AuditService()
