"""能力登记与管理接口，挂载前缀 `/api/capability`。

均需要登录且通过 user-service 实时管理员授权；状态变更走独立的
`/{capability_id}/status`，编辑接口不接收 status。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.deps import require_admin
from app.core.logging import get_request_id
from app.core.result import Result
from app.db.session import get_db
from app.schemas import (
    CapabilityCreateRequest,
    CapabilityDeleteOut,
    CapabilityManageOut,
    CapabilityStatusOut,
    CapabilityStatusUpdateRequest,
    CapabilityUpdateRequest,
)
from app.service import capability_service

router = APIRouter()


@router.post("", response_model=Result)
async def create_capability(
    payload: CapabilityCreateRequest,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Result:
    """登记能力；非管理员 2007，分类不存在 2003，编码重复 2006，status 缺省 draft。"""

    created = capability_service.create_capability(db, payload)
    return Result.ok(
        CapabilityManageOut.from_row(
            created, capability_service.get_category_name(db, created.category_id)
        ).model_dump(),
        request_id=get_request_id(),
    )


@router.put("/{capability_id}", response_model=Result)
async def update_capability(
    capability_id: int,
    payload: CapabilityUpdateRequest,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Result:
    """编辑能力；能力不存在返回 2002，分类不存在返回 2003，编码重复返回 2006。"""

    updated = capability_service.update_capability(db, capability_id, payload)
    return Result.ok(
        CapabilityManageOut.from_row(
            updated, capability_service.get_category_name(db, updated.category_id)
        ).model_dump(),
        request_id=get_request_id(),
    )


@router.delete("/{capability_id}", response_model=Result)
async def delete_capability(
    capability_id: int,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Result:
    """软删除能力；已上架的能力会先置为 offline，能力不存在返回 2002。"""

    capability_service.delete_capability(db, capability_id)
    return Result.ok(
        CapabilityDeleteOut(id=capability_id).model_dump(), request_id=get_request_id()
    )


@router.put("/{capability_id}/status", response_model=Result)
async def update_capability_status(
    capability_id: int,
    payload: CapabilityStatusUpdateRequest,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Result:
    """上架 / 下架能力；status 只接受 draft、online、offline，非法值返回 2001。"""

    updated = capability_service.update_status(db, capability_id, payload)
    return Result.ok(
        CapabilityStatusOut(
            id=updated.id, status=updated.status, update_time=updated.update_time
        ).model_dump(),
        request_id=get_request_id(),
    )
