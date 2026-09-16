"""Schema 通用基类、分页边界与统计时间范围解析。

与 capability-service / user-service 的同名模块保持一致：
时间统一 `YYYY-MM-DD HH:MM:SS`，分页统一 `list / total / page / page_size`。
日期型字段（`stat_date`、`start_date`、`end_date`）直接使用 `date`，
由 Pydantic 序列化为 `YYYY-MM-DD`，不需要额外处理。

统计时间范围约定写在接口契约第 0 节：
未显式传参时回看最近 `STAT_DEFAULT_RANGE_DAYS` 天（含今天）；
跨度不得超过 `MAX_STAT_RANGE_DAYS` 天，否则按参数错误处理。
"""

from datetime import date, datetime, timedelta

from pydantic import BaseModel, ConfigDict, field_serializer

from app.core.constants import MAX_STAT_RANGE_DAYS
from app.core.exceptions import BizException

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DATE_FORMAT = "%Y-%m-%d"

PAGE_SIZE_DEFAULT = 10
PAGE_SIZE_MAX = 100

# 未显式传参时的默认回看天数。
STAT_DEFAULT_RANGE_DAYS = 30

# 参数类错误统一使用平台约定的 2001（由基座处理 Schema 错误，这里保持一致）。
INVALID_PARAM_CODE = 2001
INVALID_PARAM_MESSAGE = "参数不符合 Schema"


class BaseOut(BaseModel):
    """出参基类：统一按契约序列化时间与日期字段。

    `check_fields=False` 让子类只声明实际拥有的字段也能复用同一序列化逻辑。
    """

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("create_time", "update_time", check_fields=False)
    def format_datetime(self, value: datetime | None, _info: object) -> str | None:
        if value is None:
            return None
        return value.strftime(DATETIME_FORMAT)

    @field_serializer("stat_date", "start_date", "end_date", check_fields=False)
    def format_date(self, value: date | None, _info: object) -> str | None:
        if value is None:
            return None
        return value.strftime(DATE_FORMAT)


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


def resolve_date_range(
    start_date: date | None, end_date: date | None
) -> tuple[date, date]:
    """解析并校验统计时间范围；非法范围抛 2001。

    `today` 取服务器本地日期（容器 TZ 为 Asia/Shanghai），保证与
    `t_call_record.create_time` / `t_usage_daily.stat_date` 的口径一致。
    """

    today = date.today()
    resolved_end = end_date or today
    resolved_start = start_date or (resolved_end - timedelta(days=STAT_DEFAULT_RANGE_DAYS - 1))

    if resolved_start > resolved_end:
        raise BizException(INVALID_PARAM_CODE, INVALID_PARAM_MESSAGE)
    if (resolved_end - resolved_start).days + 1 > MAX_STAT_RANGE_DAYS:
        raise BizException(INVALID_PARAM_CODE, INVALID_PARAM_MESSAGE)
    return resolved_start, resolved_end
