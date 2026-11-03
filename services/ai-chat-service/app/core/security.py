from fastapi import Header
from pydantic import BaseModel


class UserContext(BaseModel):
    """调用者身份；由网关注入，或在 OpenAI 兼容层用 API Key 自行解析。

    `api_key_id` / `entrypoint` 是 P6 新增的**归因元数据**，不参与任何鉴权判断：
    - `api_key_id` 为 None 表示这次调用没有 Key 身份（网页调试台、登录 JWT 直调）；
    - `entrypoint` 只用于账单上的入口标记，取值 `web` / `platform_api` / `openai_compat`。
    """

    user_id: str = ""
    user_name: str = ""
    request_id: str = ""
    api_key_id: int | None = None
    entrypoint: str = "web"


def _optional_key_id(raw: str) -> int | None:
    """解析 `X-User-Key-Id`；非法值一律当"没有 Key 身份"，不阻断主流程。"""

    text = (raw or "").strip()
    if not text.isdigit():
        return None
    value = int(text)
    return value if value > 0 else None


def current_user(
    x_user_id: str = Header(default="", alias="X-User-Id"),
    x_user_name: str = Header(default="", alias="X-User-Name"),
    x_request_id: str = Header(default="", alias="X-Request-Id"),
    x_user_key_id: str = Header(default="", alias="X-User-Key-Id"),
) -> UserContext:
    """读取网关注入的身份，不在业务服务内重复解析 JWT。

    `X-User-Key-Id` 只在用 API Key 换来的 JWT 调 `/api/**` 时才有值：
    网关会先清掉所有外部 `x-user-*` 头再写入，因此外部伪造同名头不会到达这里。
    """

    key_id = _optional_key_id(x_user_key_id)
    return UserContext(
        user_id=x_user_id,
        user_name=x_user_name,
        request_id=x_request_id,
        api_key_id=key_id,
        entrypoint="platform_api" if key_id is not None else "web",
    )
