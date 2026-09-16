from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.logging import get_request_id
from app.core.result import Result
from app.core.security import UserContext, current_user
from app.db.session import get_db
from app.schemas.chat import ChatCompletionRequest
from app.service.chat_service import chat_service


router = APIRouter()


@router.post("/completions", response_model=Result)
async def completions(
    request: ChatCompletionRequest,
    user: UserContext = Depends(current_user),
    db: Session = Depends(get_db),
) -> Result:
    """多轮对话主接口：落库会话与消息，并按开关联动积分与计费。"""

    data = await chat_service.complete(db, request, user)
    return Result.ok(data, request_id=get_request_id())
