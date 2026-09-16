"""积分余额、流水与内部扣分业务逻辑。

本模块承担闭环节点的两个内部职责（指南 3.3 / 11.2）：

1. `check`：能力服务执行前校验用户状态与可用积分，不足时返回 `3001`（指南 3.4）；
2. `deduct`：以乐观条件更新扣分并写流水，同一 `requestId` 只扣一次。

并发与幂等设计：
- **幂等**：`t_points_log` 的 `(request_id, is_deleted)` 唯一索引是幂等键的最终防线。
  扣分时先插入流水占位并 flush，若唯一索引冲突说明该 requestId 已扣过分，
  直接回滚并返回首次扣分结果（`duplicated=true`），余额不会二次减少。
- **防超扣**：扣减使用 `WHERE balance >= :cost` 的条件更新，以影响行数判定结果，
  不使用“先查余额再更新”的读改写流程。
"""

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.constants import PointDirection
from app.core.exceptions import BizException
from app.models import PointsAccount, PointsLog, User
from app.repository import PointsRepository, UserRepository
from app.repository import points_repository, user_repository
from app.schemas import PointsDeductOut, PointsDeductRequest, PointsLogOut
from app.service.user_service import require_available_user

# 余额不足与用户异常的错误码语义：
# - 用户维度异常用 1005（10xx 号段）；
# - 积分不足按指南 5.2 / 3.4 使用计费号段 3001，与 billing-service 判定口径一致。
INSUFFICIENT_POINTS_CODE = 3001
INSUFFICIENT_POINTS_MESSAGE = "积分不足"
USER_UNAVAILABLE_MESSAGE = "用户不存在或已被禁用"


class PointsService:
    """积分账户与流水的用例。"""

    def __init__(
        self,
        points: PointsRepository | None = None,
        users: UserRepository | None = None,
    ) -> None:
        self.points = points or points_repository
        self.users = users or user_repository

    # ------------------------------------------------------------ 对外查询

    def get_account(self, db: Session, user_id: int) -> PointsAccount:
        """取当前用户积分账户；用户被禁用或账户缺失都按 1005 处理。"""

        # 网关只认 Token，不禁用账号；因此每个受保护查询都要自己确认账号仍可用。
        self._require_available_user(db, user_id)
        account = self.points.find_account(db, user_id)
        if account is None:
            raise BizException(1005, USER_UNAVAILABLE_MESSAGE)
        return account

    def list_logs(
        self,
        db: Session,
        user_id: int,
        *,
        direction: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> tuple[list[PointsLogOut], int]:
        self._require_available_user(db, user_id)
        rows, total = self.points.list_logs(
            db, user_id, direction=direction, page=page, page_size=page_size
        )
        return [PointsLogOut.from_log(row) for row in rows], total

    # ------------------------------------------------------------ 内部接口

    def check(self, db: Session, user_id: int, points_cost: int) -> dict[str, object]:
        """`GET /internal/user/check`：返回用户状态与可用积分。"""

        user = self._require_available_user(db, user_id)
        account = self.points.find_account(db, user_id)
        balance = account.balance if account is not None else 0

        # 能力执行前拦截：余额不足时不进入能力执行与记账流程。
        if balance < points_cost:
            raise BizException(INSUFFICIENT_POINTS_CODE, INSUFFICIENT_POINTS_MESSAGE)

        return {
            "user_id": user.id,
            "username": user.username,
            "status": user.status,
            "balance": balance,
            "points_cost": points_cost,
            "available": True,
        }

    def deduct(
        self, db: Session, payload: PointsDeductRequest, caller_user_id: str
    ) -> PointsDeductOut:
        """`POST /internal/user/points/deduct`：扣分 + 写流水，幂等。"""

        # 内部接口不重复解析 JWT，但必须校验链路身份，防止越权扣他人积分。
        if str(payload.user_id) != caller_user_id:
            raise BizException(1001, "缺少或伪造的链路身份")

        self._require_available_user(db, payload.user_id)

        # 快路径：该 requestId 已扣过分，直接返回首次结果。
        existing = self.points.find_log_by_request_id(db, payload.request_id)
        if existing is not None:
            logger.info(
                "重复扣分请求已幂等命中 request_id={} user_id={}",
                payload.request_id,
                payload.user_id,
            )
            return self._duplicated_result(existing)

        try:
            # 先插入流水占位，用唯一索引抢占幂等键，再执行扣减。
            log = self.points.add_log(
                db,
                PointsLog(
                    user_id=payload.user_id,
                    direction=PointDirection.OUT.value,
                    amount=payload.amount,
                    balance_after=0,
                    biz_type=payload.biz_type.value,
                    request_id=payload.request_id,
                    remark=payload.remark or "能力调用扣分",
                ),
            )
        except IntegrityError:
            # 并发同 requestId：另一个请求已经占了幂等键，按重放处理。
            db.rollback()
            existing = self.points.find_log_by_request_id(db, payload.request_id)
            if existing is None:
                logger.error("扣分幂等冲突但未找到流水 request_id={}", payload.request_id)
                raise BizException(4003, "系统内部错误") from None
            return self._duplicated_result(existing)

        affected = self.points.try_deduct(db, payload.user_id, payload.amount)
        if affected == 0:
            # 回滚会一并撤销上面插入的流水，不留半成功状态。
            db.rollback()
            logger.info("积分不足扣分失败 user_id={}", payload.user_id)
            raise BizException(INSUFFICIENT_POINTS_CODE, INSUFFICIENT_POINTS_MESSAGE)

        balance_after = self.points.read_balance(db, payload.user_id) or 0
        log.balance_after = balance_after
        db.commit()
        logger.info(
            "积分已扣减 user_id={} amount={} balance_after={}",
            payload.user_id,
            payload.amount,
            balance_after,
        )
        return PointsDeductOut(
            user_id=payload.user_id,
            amount=payload.amount,
            balance_after=balance_after,
            duplicated=False,
        )

    # ------------------------------------------------------------ 内部工具

    @staticmethod
    def _duplicated_result(log: PointsLog) -> PointsDeductOut:
        return PointsDeductOut(
            user_id=log.user_id,
            amount=log.amount,
            balance_after=log.balance_after,
            duplicated=True,
        )

    def _require_available_user(self, db: Session, user_id: int) -> User:
        return require_available_user(db, user_id, self.users)


points_service = PointsService()
