"""用户注册、登录与资料业务逻辑。

错误码只用 10xx 号段，并且一律通过 `BizException` 抛出，由基座全局异常处理器
转换成统一 Result（业务错误 HTTP 仍为 200）：
`1003` 用户名或密码错误、`1004` 用户名已存在、`1005` 用户不存在或已被禁用。
"""

from datetime import datetime

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import (
    REGISTER_BIZ_PREFIX,
    PointBizType,
    PointDirection,
    UserStatus,
)
from app.core.exceptions import BizException
from app.core.jwt_util import create_token
from app.core.password import hash_password, verify_password
from app.models import PointsAccount, PointsLog, User
from app.repository import points_repository, user_repository
from app.repository import PointsRepository, UserRepository
from app.schemas import LoginRequest, ProfileUpdateRequest, RegisterRequest
from app.schemas.user import is_normal_status


def require_available_user(
    db: Session, user_id: int, users: UserRepository | None = None
) -> User:
    """共享的用户状态校验：用户必须存在且为 `normal`，否则抛 1005。

    为什么需要它：网关只校验 JWT 签名与有效期，**不知道用户是否已被禁用**，
    因此被禁用账号在 Token 过期前仍能通过网关。是否放行由业务服务自己判定，
    本函数就是 user-service 各业务的统一入口（本服务拥有 `t_user`，一次主键查询即完成）。

    注意：这是「策略校验」而非「认证」。认证已由网关完成，本函数只判断账号是否
    仍然可用；错误码沿用 1005，与资料接口的既有行为一致。
    """

    repository = users or user_repository
    user = repository.find_by_id(db, user_id)
    if user is None or not is_normal_status(user.status):
        raise BizException(1005, "用户不存在或已被禁用")
    return user


class UserService:
    """账号相关用例：注册、登录、读取与更新资料。"""

    def __init__(
        self,
        users: UserRepository | None = None,
        points: PointsRepository | None = None,
    ) -> None:
        self.users = users or user_repository
        self.points = points or points_repository

    # ------------------------------------------------------------ 注册 / 登录

    def register(self, db: Session, payload: RegisterRequest) -> tuple[User, PointsAccount]:
        """注册并**在同一事务内**创建积分账户、写入赠送流水。

        “注册即建积分账户并赠送初始积分”要求三张表整体成功，否则回滚，
        不能出现“有用户没有账户”的半成功状态。
        """

        if self.users.exists_username(db, payload.username):
            raise BizException(1004, "用户名已存在")

        initial_points = settings.initial_points
        try:
            user = self.users.add(
                db,
                User(
                    role="user",
                    username=payload.username,
                    password_hash=hash_password(payload.password),
                    nickname=payload.nickname or payload.username,
                    status=UserStatus.NORMAL.value,
                ),
            )
            account = self.points.add_account(
                db,
                PointsAccount(
                    user_id=user.id,
                    balance=initial_points,
                    frozen=0,
                    version=1,
                ),
            )
            self.points.add_log(
                db,
                PointsLog(
                    user_id=user.id,
                    direction=PointDirection.IN.value,
                    amount=initial_points,
                    balance_after=initial_points,
                    biz_type=PointBizType.REGISTER.value,
                    # 流水幂等键使用独立命名空间，避免与能力调用的 requestId 混淆。
                    request_id=f"{REGISTER_BIZ_PREFIX}{user.id}",
                    remark="注册赠送初始积分",
                ),
            )
            db.commit()
        except IntegrityError as exc:
            # 并发注册时唯一索引兜底；只记录用户名，绝不记录口令。
            db.rollback()
            logger.warning("注册冲突 username={}", payload.username)
            raise BizException(1004, "用户名已存在") from exc

        db.refresh(user)
        logger.info("用户已注册 user_id={}", user.id)
        return user, account

    def login(self, db: Session, payload: LoginRequest) -> tuple[User, str, datetime]:
        """校验凭据并签发与网关同密钥的 JWT。"""

        user = self.users.find_by_username(db, payload.username)
        # 用户不存在与口令错误返回同一个错误码，避免账号枚举。
        if user is None or not verify_password(payload.password, user.password_hash):
            raise BizException(1003, "用户名或密码错误")
        if not is_normal_status(user.status):
            raise BizException(1005, "用户不存在或已被禁用")

        token, expire_at = create_token(user.id, user.username, role=user.role)
        logger.info("用户已登录 user_id={}", user.id)
        return user, token, expire_at

    # ------------------------------------------------------------ 资料

    def get_profile(self, db: Session, user_id: int) -> User:
        return self.require_user(db, user_id)

    def update_profile(
        self, db: Session, user_id: int, payload: ProfileUpdateRequest
    ) -> User:
        user = self.require_user(db, user_id)
        self.users.update_fields(db, user, {"nickname": payload.nickname})
        db.commit()
        db.refresh(user)
        return user

    # ------------------------------------------------------------ 公共校验

    def require_user(self, db: Session, user_id: int) -> User:
        """取处于正常状态的用户，否则抛 1005；与共享校验函数行为一致。"""

        user = self.users.find_by_id(db, user_id)
        if user is None or not is_normal_status(user.status):
            raise BizException(1005, "用户不存在或已被禁用")
        return user


user_service = UserService()
