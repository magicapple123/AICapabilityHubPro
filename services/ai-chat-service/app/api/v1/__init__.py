"""v1 业务路由。

挂载顺序：`/api/chat` 下 ping 与 completions 为固定路径，sessions 路由自身
先注册 `/sessions` 再注册 `/sessions/{session_id}/messages`，不存在抢占问题。
OpenAI 兼容路由单独挂在 `/v1`，与平台自有接口互不影响。
"""

from app.api.v1.chat import router as chat_router
from app.api.v1.openai_compat import router as openai_router
from app.api.v1.ping import router as ping_router
from app.api.v1.sessions import router as sessions_router

__all__ = ["chat_router", "openai_router", "ping_router", "sessions_router"]
