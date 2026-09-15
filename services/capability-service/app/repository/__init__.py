"""本服务的数据访问层；只访问 capability_db，禁止跨库查询。"""

from app.repository.capability_repository import CapabilityRepository, capability_repository
from app.repository.category_repository import CategoryRepository, category_repository

__all__ = [
    "CapabilityRepository",
    "CategoryRepository",
    "capability_repository",
    "category_repository",
]
