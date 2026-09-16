"""本服务的 Pydantic 请求与响应模型。"""

from app.schemas.apikey import (
    ApiKeyCreateRequest,
    ApiKeyCreatedOut,
    ApiKeyOut,
    ApiKeyStatusOut,
)
from app.schemas.common import (
    PAGE_SIZE_DEFAULT,
    PAGE_SIZE_MAX,
    build_list_data,
    build_page_data,
)
from app.schemas.internal import PointsDeductOut, PointsDeductRequest, UserCheckOut
from app.schemas.points import PointsAccountOut, PointsLogOut
from app.schemas.user import (
    LoginOut,
    LoginRequest,
    ProfileOut,
    ProfileUpdateRequest,
    RegisterOut,
    RegisterRequest,
)

__all__ = [
    "PAGE_SIZE_DEFAULT",
    "PAGE_SIZE_MAX",
    "ApiKeyCreateRequest",
    "ApiKeyCreatedOut",
    "ApiKeyOut",
    "ApiKeyStatusOut",
    "LoginOut",
    "LoginRequest",
    "PointsAccountOut",
    "PointsDeductOut",
    "PointsDeductRequest",
    "PointsLogOut",
    "ProfileOut",
    "ProfileUpdateRequest",
    "RegisterOut",
    "RegisterRequest",
    "UserCheckOut",
    "build_list_data",
    "build_page_data",
]
