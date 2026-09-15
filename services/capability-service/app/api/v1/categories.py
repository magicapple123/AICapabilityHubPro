"""分类接口，挂载前缀 `/api/capability/categories`。

均需要登录：网关白名单只放行 `/api/capability/market/**`。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.deps import current_user_id
from app.core.constants import CategoryStatus
from app.core.logging import get_request_id
from app.core.result import Result
from app.db.session import get_db
from app.schemas import (
    CategoryCreateRequest,
    CategoryDeleteOut,
    CategoryOut,
    CategoryUpdateRequest,
    build_list_data,
)
from app.service import category_service

router = APIRouter()


@router.get("", response_model=Result)
async def list_categories(
    status: CategoryStatus | None = Query(default=None, description="按分类状态筛选"),
    keyword: str | None = Query(
        default=None, max_length=64, description="按分类名称模糊匹配"
    ),
    _: str = Depends(current_user_id),
    db: Session = Depends(get_db),
) -> Result:
    """分类列表；分类数量少，按契约不分页。"""

    categories = category_service.list_categories(
        db, status=status.value if status is not None else None, keyword=keyword
    )
    return Result.ok(
        build_list_data([CategoryOut.model_validate(item) for item in categories]),
        request_id=get_request_id(),
    )


@router.post("", response_model=Result)
async def create_category(
    payload: CategoryCreateRequest,
    _: str = Depends(current_user_id),
    db: Session = Depends(get_db),
) -> Result:
    """新增分类；名称与编码在未删除范围内唯一，重复返回 2004。"""

    # TODO(契约第 6 节待确认): 运营权限方案未定，当前按“已登录即可访问”处理，
    # 2007 判定位置保留在此处。
    created = category_service.create_category(db, payload)
    return Result.ok(
        CategoryOut.model_validate(created).model_dump(), request_id=get_request_id()
    )


@router.put("/{category_id}", response_model=Result)
async def update_category(
    category_id: int,
    payload: CategoryUpdateRequest,
    _: str = Depends(current_user_id),
    db: Session = Depends(get_db),
) -> Result:
    """编辑分类，仅提交需要变更的字段；分类不存在返回 2003。"""

    updated = category_service.update_category(db, category_id, payload)
    return Result.ok(
        CategoryOut.model_validate(updated).model_dump(), request_id=get_request_id()
    )


@router.delete("/{category_id}", response_model=Result)
async def delete_category(
    category_id: int,
    _: str = Depends(current_user_id),
    db: Session = Depends(get_db),
) -> Result:
    """软删除分类；分类下仍有未删除能力时返回 2005，不做破坏性删除。"""

    category_service.delete_category(db, category_id)
    return Result.ok(
        CategoryDeleteOut(id=category_id).model_dump(), request_id=get_request_id()
    )
