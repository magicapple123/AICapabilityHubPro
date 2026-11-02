"""F1 运营后台用户管理：列表、详情（含用量）、启停、调分、导出。

安全约束：
- 全部接口要求实时管理员授权（与 capability 运营接口同源）；
- 调分必须带原因，且以 `admin_adjust` 业务类型写入流水，便于对账时与能力调用区分；
- 任何写操作都在**同一事务**内写审计（`audit_service.stage` 先挂进 session）。
"""

import csv
import io
from datetime import date, timedelta

from fastapi import HTTPException
from loguru import logger
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import PointDirection, UserStatus
from app.core.exceptions import BizException
from app.core.security import UserContext
from app.core.service_call import call_internal
from app.models import PointsLog, User
from app.repository import points_repository, user_repository
from app.service import audit_service
from app.service.audit_service import (
    ACTION_ADJUST_POINTS,
    ACTION_STATUS,
    RESOURCE_POINTS,
    RESOURCE_USER,
)

ADMIN_ADJUST_BIZ_TYPE = "admin_adjust"
MAX_ADJUST_AMOUNT = 1_000_000


class AdminService:
    # ------------------------------------------------------------ 查询

    def list_users(
        self, db: Session, *, keyword: str | None, status: str | None,
        page: int, page_size: int,
    ) -> tuple[list[dict], int]:
        rows, total = user_repository.search(
            db, keyword=keyword, status=status, page=page, page_size=page_size
        )
        items = []
        for user in rows:
            account = points_repository.find_account(db, user.id)
            items.append({
                "id": user.id,
                "username": user.username,
                "nickname": user.nickname,
                "role": user.role,
                "status": user.status,
                "balance": account.balance if account else 0,
                "daily_points_limit": user.daily_points_limit,
                "create_time": user.create_time.strftime("%Y-%m-%d %H:%M:%S"),
            })
        return items, total

    async def detail(self, db: Session, user_id: int) -> dict:
        user = user_repository.find_by_id(db, user_id)
        if user is None:
            raise BizException(1005, "用户不存在")
        account = points_repository.find_account(db, user_id)
        usage = await self._usage_of(user_id)
        return {
            "id": user.id,
            "username": user.username,
            "nickname": user.nickname,
            "role": user.role,
            "status": user.status,
            "balance": account.balance if account else 0,
            "daily_points_limit": user.daily_points_limit,
            "today_used": points_repository.sum_today_call_outflow(db, user_id),
            "create_time": user.create_time.strftime("%Y-%m-%d %H:%M:%S"),
            "usage": usage,
        }

    async def _usage_of(self, user_id: int) -> dict | None:
        """复用 billing 的统计口径；对端不可用时返回 None，不影响详情其它字段。"""

        try:
            data = await call_internal(
                settings.billing_service_name,
                "GET",
                f"/internal/billing/users/{user_id}/usage",
                params={"days": 30},
            )
        except Exception as error:  # noqa: BLE001 - 用量是附加信息，不阻断详情
            logger.warning("用户用量查询失败 user_id={} type={}", user_id, type(error).__name__)
            return None
        return data if isinstance(data, dict) else None

    # ------------------------------------------------------------ 写操作

    def set_status(
        self, db: Session, actor: UserContext, user_id: int, status: str
    ) -> dict:
        if status not in {item.value for item in UserStatus}:
            raise BizException(2001, "用户状态只能是 normal/disabled")
        user = user_repository.find_by_id(db, user_id)
        if user is None:
            raise BizException(1005, "用户不存在")
        before = {"status": user.status}
        audit_service.stage(
            db, actor=actor, resource_type=RESOURCE_USER, resource_id=user_id,
            action=ACTION_STATUS, before=before, after={"status": status},
        )
        user_repository.update_fields(db, user, {"status": status})
        # user_repository 只 flush；这里统一提交，审计行与状态变更同事务落库。
        db.commit()
        return {"id": user.id, "status": user.status}

    def adjust_points(
        self, db: Session, actor: UserContext, user_id: int, amount: int, reason: str
    ) -> dict:
        """正数加、负数减；一条调整写一条流水，requestId 由服务端生成保证可追溯。"""

        if amount == 0:
            raise BizException(2001, "调整数量不能为 0")
        if abs(amount) > MAX_ADJUST_AMOUNT:
            raise BizException(2001, "单次调整数量过大")
        reason = (reason or "").strip()
        if not reason:
            raise BizException(2001, "调整积分必须填写原因")

        user = user_repository.find_by_id(db, user_id)
        if user is None:
            raise BizException(1005, "用户不存在")
        account = points_repository.find_account(db, user_id)
        if account is None:
            raise BizException(1005, "积分账户不存在")

        # 先记住旧余额：后面的 ORM UPDATE 会把 session 里的 account 同步成新值，
        # 事后再读 account.balance 会拿到"已加过"的数字。
        balance_before = account.balance
        direction = PointDirection.IN if amount > 0 else PointDirection.OUT
        cost = abs(amount)
        if direction is PointDirection.OUT and balance_before < cost:
            raise BizException(3001, "余额不足，无法扣减")

        before = {"balance": balance_before, "daily_points_limit": user.daily_points_limit}
        audit_service.stage(
            db, actor=actor, resource_type=RESOURCE_POINTS, resource_id=user_id,
            action=ACTION_ADJUST_POINTS, before=before,
            after={"balance": balance_before + amount, "amount": amount, "reason": reason},
        )

        request_id = f"admin-{actor.request_id or 'manual'}-{user_id}-{abs(amount)}"
        points_repository.add_log(
            db,
            PointsLog(
                user_id=user_id,
                direction=direction.value,
                amount=cost,
                balance_after=balance_before + amount,
                biz_type=ADMIN_ADJUST_BIZ_TYPE,
                request_id=request_id,
                remark=f"运营调整：{reason}",
            ),
        )
        affected = (
            points_repository.try_credit(db, user_id, amount) if amount > 0
            else points_repository.try_deduct(db, user_id, cost)
        )
        if affected == 0:
            db.rollback()
            raise BizException(3001, "积分变更失败，请重试")
        db.commit()
        return {
            "id": user_id,
            "balance": balance_before + amount,
            "amount": amount,
            "reason": reason,
        }

    # ------------------------------------------------------------ 导出

    def export_csv(
        self, db: Session, *, keyword: str | None, status: str | None
    ) -> str:
        rows, _ = user_repository.search(
            db, keyword=keyword, status=status, page=1, page_size=10000
        )
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["id", "username", "nickname", "role", "status",
                         "balance", "daily_points_limit", "create_time"])
        for user in rows:
            account = points_repository.find_account(db, user.id)
            writer.writerow([
                user.id, user.username, user.nickname, user.role, user.status,
                account.balance if account else 0, user.daily_points_limit,
                user.create_time.strftime("%Y-%m-%d %H:%M:%S"),
            ])
        return buffer.getvalue()


admin_service = AdminService()
