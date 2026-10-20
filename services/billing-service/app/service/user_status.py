"""调用方账号状态校验。

为什么需要它：网关只校验 JWT 签名与有效期，**不知道账号是否已被禁用**，
因此被禁用账号的旧 Token 在过期前仍能通过网关。放行与否必须由业务服务自己判定。

billing-service 没有 `user_db` 的访问权（禁止跨库），状态只能通过 user-service 的
`/internal/user/check`（`points_cost=0`）查询，本模块是该调用的唯一封装：

- 账号被禁用 → user-service 返回 `1005`，原样透传；
- user-service 不可用 → 基座返回 `4002`，与指南 3.4 的降级语义一致。

放在 service 层而不是写成 FastAPI 依赖，是为了固定错误优先级：参数校验（`2001`）
与未认证（`1001`）先返回，跨服务调用只在校验通过后发生；同时也让不依赖数据库与
网络的纯参数测试保持原样。

注意这是「策略校验」而非「认证」：认证已由网关完成，这里只判断账号是否仍可用。
"""

from loguru import logger

from app.core.config import settings
from app.core.exceptions import BizException
from app.core.service_call import call_internal

USER_UNAVAILABLE_CODE = 1005
USER_UNAVAILABLE_MESSAGE = "用户不存在或已被禁用"


class UserStatusService:
    """通过 user-service 的内部契约校验账号是否可用。"""

    async def ensure_admin(self, user_id: int) -> None:
        try:
            data = await call_internal(settings.user_service_name, "GET", "/internal/user/authorization",
                                       params={"user_id": user_id, "required_role": "admin"})
        except BizException as exc:
            if exc.code in {1001, 1005, 1006, 4002}:
                raise
            raise BizException(4002, "授权服务暂不可用") from None
        except Exception:
            raise BizException(4002, "授权服务暂不可用") from None
        if (not isinstance(data, dict) or type(data.get("user_id")) is not int or
                data["user_id"] != user_id or data.get("status") != "normal" or
                data.get("role") != "admin" or data.get("authorized") is not True):
            raise BizException(4002, "授权服务响应格式错误")

    async def ensure_active(self, user_id: int) -> None:
        """账号可用则正常返回，否则抛业务异常。

        `points_cost=0` 只做状态校验，不触发积分判断（余额恒 ≥ 0，不会误报 3001）。
        """

        data = await call_internal(
            settings.user_service_name,
            "GET",
            "/internal/user/check",
            params={"user_id": user_id, "points_cost": 0},
        )
        # 防御式校验：即使对端返回 code=0，也要求明确给出 available=true。
        if not isinstance(data, dict) or not data.get("available"):
            logger.warning("账号状态校验未通过 user_id={}", user_id)
            raise BizException(USER_UNAVAILABLE_CODE, USER_UNAVAILABLE_MESSAGE)


user_status_service = UserStatusService()
