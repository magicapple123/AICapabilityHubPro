from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.logging import get_request_id
from app.core.rate_limit import rate_limiter
from app.core.result import Result
from app.core.security import UserContext, current_user
from app.db.session import get_db
from app.schemas.chat import ChatCompletionRequest
from app.service.chat_service import chat_service
from app.service.capability_adapters import EXECUTORS, SUPPORTED_CODES
from app.core.capability_config import capability_settings
from app.schemas.capability import ChatInput, SummaryInput


router = APIRouter()


@router.get("/executors", response_model=Result)
async def executors(user: UserContext = Depends(current_user)) -> Result:
    chat_service._require_user(user)
    return Result.ok({
        # codes 保留给旧前端；executors 是新契约（D2），市场"暂无执行器"以它为准。
        "codes": list(SUPPORTED_CODES),
        "executors": list(EXECUTORS),
        "executor_protocols": {name: list(spec.protocols) for name, spec in EXECUTORS.items()},
        "input_schemas": {
            "chat-completions": ChatInput.model_json_schema(),
            "long-summary": SummaryInput.model_json_schema(),
            "chat": ChatInput.model_json_schema(),
            "summary": SummaryInput.model_json_schema(),
        },
        "catalog_mode": capability_settings.capability_catalog_mode,
    }, request_id=get_request_id())


@router.post("/completions", response_model=Result)
async def completions(
    request: ChatCompletionRequest,
    user: UserContext = Depends(current_user),
    db: Session = Depends(get_db),
) -> Result:
    """多轮对话主接口：落库会话与消息，并按开关联动积分与计费。"""

    data = await chat_service.complete(db, request, user)
    return Result.ok(data, request_id=get_request_id())
