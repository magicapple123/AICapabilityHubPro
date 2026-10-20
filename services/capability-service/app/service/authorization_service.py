"""运营接口的实时管理员授权。

capability-service 不跨库读取用户角色，统一通过 `call_internal` 调用
user-service 的 `GET /internal/user/authorization`。只有“返回 ID 与当前身份一致、
账号 normal、角色 admin、authorized 为 true”同时成立才放行；超时、端点缺失、
响应格式异常或拒绝授权一律失败关闭。

权限码约定（与 docs/api-contract/pro-shared.md 一致）：user 授权接口对普通用户
返回 1007，capability 对外映射 2007；1006 保留“API Key 不存在”语义。为兼容可能
尚未同步码值的旧 user 构建，本模块在授权端点把 1006 也视为拒绝（仅拒绝，不放行）。
"""

from typing import Any

from loguru import logger

from app.core.config import settings
from app.core.exceptions import BizException
from app.core.service_call import call_internal

AUTHORIZATION_PATH = "/internal/user/authorization"
PERMISSION_DENIED_CODE = 2007
DEPENDENCY_FAILURE_CODE = 4002
PERMISSION_DENIED_MESSAGE = "无运营权限，仅管理员可执行该操作"
DEPENDENCY_FAILURE_MESSAGE = "运营权限校验服务不可用，已拒绝本次操作"

# 1007 为共享契约新增的“权限不足”；1006 仅作为旧 user 构建的兼容拒绝码。
_PERMISSION_DENIED_CODES = frozenset({1007, 1006})


def _parse_user_id(user_id: str) -> int:
    """把网关注入的身份转换成正整数；非法身份按依赖异常失败关闭。"""

    try:
        value = int(str(user_id).strip())
    except (TypeError, ValueError):
        value = 0
    if value < 1:
        raise BizException(DEPENDENCY_FAILURE_CODE, DEPENDENCY_FAILURE_MESSAGE)
    return value


def _decision(data: Any, expected_user_id: int) -> bool | None:
    """校验授权响应；结构不可信返回 None，结构可信但非管理员返回 False。"""

    if not isinstance(data, dict):
        return None
    returned_id = data.get("user_id")
    status = data.get("status")
    role = data.get("role")
    authorized = data.get("authorized")
    if type(returned_id) is not int or returned_id != expected_user_id:
        return None
    if not isinstance(status, str) or not isinstance(role, str):
        return None
    if type(authorized) is not bool:
        return None
    return status == "normal" and role == "admin" and authorized is True


async def require_admin(user_id: str) -> None:
    """要求当前用户是启用中的管理员，否则抛出 2007/4002。"""

    target_user_id = _parse_user_id(user_id)
    try:
        data = await call_internal(
            settings.user_service_name,
            "GET",
            AUTHORIZATION_PATH,
            params={"user_id": target_user_id, "required_role": "admin"},
        )
    except BizException as exc:
        if exc.code in _PERMISSION_DENIED_CODES:
            logger.info("运营操作被拒绝 reason=permission_denied user_id={}", target_user_id)
            raise BizException(PERMISSION_DENIED_CODE, PERMISSION_DENIED_MESSAGE) from exc
        logger.warning(
            "运营授权依赖异常 code={} user_id={}", exc.code, target_user_id
        )
        raise BizException(DEPENDENCY_FAILURE_CODE, DEPENDENCY_FAILURE_MESSAGE) from exc
    except Exception as exc:  # 网络、解析等未知异常都必须失败关闭
        logger.warning(
            "运营授权调用失败 type={} user_id={}", type(exc).__name__, target_user_id
        )
        raise BizException(DEPENDENCY_FAILURE_CODE, DEPENDENCY_FAILURE_MESSAGE) from exc

    decision = _decision(data, target_user_id)
    if decision is None:
        logger.warning("运营授权响应不可信 user_id={}", target_user_id)
        raise BizException(DEPENDENCY_FAILURE_CODE, DEPENDENCY_FAILURE_MESSAGE)
    if not decision:
        logger.info("运营操作被拒绝 reason=not_admin user_id={}", target_user_id)
        raise BizException(PERMISSION_DENIED_CODE, PERMISSION_DENIED_MESSAGE)
