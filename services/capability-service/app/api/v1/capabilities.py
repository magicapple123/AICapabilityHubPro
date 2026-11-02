"""能力登记与管理接口，挂载前缀 `/api/capability`。

均需要登录且通过 user-service 实时管理员授权；状态变更走独立的
`/{capability_id}/status`，编辑接口不接收 status。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.deps import require_admin
from app.core.exceptions import BizException
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

    await capability_service.ensure_provider_binding(payload.executor, payload.provider_alias)
    created = capability_service.create_capability(db, payload)
    await capability_service.invalidate_catalog(created.id)
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

    effective = capability_service.require_capability(db, capability_id)
    await capability_service.ensure_provider_binding(
        payload.executor if payload.executor is not None else effective.executor,
        payload.provider_alias if payload.provider_alias is not None else effective.provider_alias,
    )
    updated = capability_service.update_capability(db, capability_id, payload)
    await capability_service.invalidate_catalog(capability_id)
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
    await capability_service.invalidate_catalog(capability_id)
    return Result.ok(
        CapabilityDeleteOut(id=capability_id).model_dump(), request_id=get_request_id()
    )


@router.post("/{capability_id}/rollback", response_model=Result)
async def rollback_capability(
    capability_id: int,
    payload: dict,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Result:
    """D5：按审计 id 回滚到该次变更之前；回滚本身也写审计。"""

    audit_id = payload.get("audit_id")
    if not isinstance(audit_id, int) or audit_id <= 0:
        raise BizException(2001, "audit_id 必须是正整数")
    capability = capability_service.rollback_capability(db, capability_id, audit_id)
    await capability_service.invalidate_catalog(capability_id)
    return Result.ok(
        capability_service._manage_out(capability).model_dump(mode="json")
        if hasattr(capability_service, "_manage_out") else {"id": capability.id},
        request_id=get_request_id(),
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
    await capability_service.invalidate_catalog(capability_id)
    return Result.ok(
        CapabilityStatusOut(
            id=updated.id, status=updated.status, update_time=updated.update_time
        ).model_dump(),
        request_id=get_request_id(),
    )
