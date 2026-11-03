"""对外模型名清单，挂载前缀 `/api/capability`。

为什么要有它：设置页的「使用方法」抽屉要给出**可直接粘贴的 model 值**。
如果让前端手填，成员写错一个字符就会拿到 `2002 模型未注册`，而这正是 P3 要消灭的
一类"照文档操作却报错"。

为什么不用 `/v1/models`：那个接口要求 `Bearer sk_...`（Secret），而抽屉按安全约定
**不读取、不缓存任何 Secret**，只能拿 access_key。因此服务端提供一个登录后即可读的
别名清单；它只包含"已在市场维度公开"的信息（对外模型名与能力名），不含 base_url、
密钥、执行参数。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.deps import current_user_id
from app.core.logging import get_request_id
from app.core.result import Result
from app.db.session import get_db
from app.service import capability_service

router = APIRouter()


@router.get("/models", response_model=Result)
async def list_published_models(
    _: str = Depends(current_user_id),
    db: Session = Depends(get_db),
) -> Result:
    """已上架 chat 能力的对外模型名；按别名升序。"""

    models = capability_service.list_published_models(db)
    return Result.ok(
        {"list": models, "total": len(models)}, request_id=get_request_id()
    )
