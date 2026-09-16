"""公开能力市场接口，挂载前缀 `/api/capability/market`。

整个前缀属网关白名单，不需要登录（数据库白名单见指南 5.3）。因此这里必须严格
保持“最小暴露”：只返回已上架且未软删除、所属分类也未软删除的能力，
且不输出 service_name、path 等内部配置。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.logging import get_request_id
from app.core.result import Result
from app.db.session import get_db
from app.schemas import (
    PAGE_SIZE_DEFAULT,
    PAGE_SIZE_MAX,
    CapabilityMarketDetailOut,
    CapabilityMarketOut,
    MarketCategoryOut,
    build_list_data,
    build_page_data,
)
from app.service import capability_service

router = APIRouter()


@router.get("", response_model=Result)
async def list_market(
    category_id: int | None = Query(default=None, ge=1, description="按分类筛选"),
    keyword: str | None = Query(
        default=None, max_length=64, description="按能力名称或描述模糊匹配"
    ),
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
    db: Session = Depends(get_db),
) -> Result:
    """能力市场列表；只返回 online 能力。"""

    rows, total = capability_service.list_market(
        db, category_id=category_id, keyword=keyword, page=page, page_size=page_size
    )
    items = [CapabilityMarketOut.from_row(capability, name) for capability, name in rows]
    return Result.ok(
        build_page_data(items, total, page, page_size), request_id=get_request_id()
    )


# 注意：`/categories` 必须声明在 `/{capability_id}` 之前，
# 否则 "categories" 会被当作路径参数尝试转成 int 并返回 2001。
@router.get("/categories", response_model=Result)
async def list_market_categories(db: Session = Depends(get_db)) -> Result:
    """市场筛选栏分类；只返回存在已上架能力的分类。"""

    categories = capability_service.list_market_categories(db)
    return Result.ok(
        build_list_data(
            [MarketCategoryOut.model_validate(item) for item in categories]
        ),
        request_id=get_request_id(),
    )


@router.get("/{capability_id}", response_model=Result)
async def get_market_detail(capability_id: int, db: Session = Depends(get_db)) -> Result:
    """市场详情；未上架或已软删除的能力统一返回 2002，不暴露其存在性。"""

    capability, category_name = capability_service.get_market_detail(db, capability_id)
    return Result.ok(
        CapabilityMarketDetailOut.from_row(capability, category_name).model_dump(),
        request_id=get_request_id(),
    )
