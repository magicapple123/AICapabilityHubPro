"""审计操作者上下文（B1）。

为什么用 ContextVar 而不是给每个 service 方法加 `operator` 参数：
service 的签名已被大量测试与内部调用依赖，加参数会强迫所有调用方改签名；
而"操作者"本质是请求级上下文，与 `use_identity` 的处理方式一致。
`require_admin` 在授权通过后写入，service 在构造审计行时读取；
读不到（例如测试直接调 service）就跳过审计，不制造假的 operator。
"""

from contextvars import ContextVar

from app.core.security import UserContext

_audit_actor: ContextVar[UserContext | None] = ContextVar("audit_actor", default=None)


def set_audit_actor(actor: UserContext) -> None:
    _audit_actor.set(actor)


def current_audit_actor() -> UserContext | None:
    return _audit_actor.get()
