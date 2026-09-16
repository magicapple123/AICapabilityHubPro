"""Schema 通用基类、分页边界与部分更新校验辅助。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_serializer

# 接口契约第 0 节：时间统一返回 YYYY-MM-DD HH:MM:SS（本地时区）。
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"

# 接口契约第 0 节分页约定：page_size 默认 10，最大 100。
PAGE_SIZE_DEFAULT = 10
PAGE_SIZE_MAX = 100


class BaseOut(BaseModel):
    """出参基类：统一按契约序列化时间字段。

    `check_fields=False` 让子类只声明实际拥有的时间字段也能复用同一序列化逻辑。
    """

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("create_time", "update_time", check_fields=False)
    def format_datetime(self, value: datetime, _info: object) -> str:
        return value.strftime(DATETIME_FORMAT)


def build_page_data(
    items: list[BaseOut], total: int, page: int, page_size: int
) -> dict[str, object]:
    """按契约第 0 节组装分页 data：list / total / page / page_size。"""

    return {
        "list": [item.model_dump() for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def build_list_data(items: list[BaseOut]) -> dict[str, object]:
    """组装不分页的列表 data：list / total。"""

    return {"list": [item.model_dump() for item in items], "total": len(items)}


def validate_partial_update(payload: BaseModel, *, non_nullable: tuple[str, ...]) -> None:
    """校验部分更新请求。

    - 至少要提交一个字段，否则无法判断更新意图；
    - `non_nullable` 中列出的字段不允许显式传 null，避免把数据库非空列写成 NULL。
    """

    if not payload.model_fields_set:
        raise ValueError("至少需要提交一个待更新字段")
    for name in non_nullable:
        if name in payload.model_fields_set and getattr(payload, name) is None:
            raise ValueError(f"{name} 不允许为 null")
