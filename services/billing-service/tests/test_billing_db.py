"""billing-service 数据库行为测试。

覆盖 team-tasks 第 4.2 节要求的“幂等写明细 → 调 user 扣分 → 累计日用量”、
扣分失败不得留下半成功状态，以及明细分页与三种用量统计。

所有用例连接真实 MySQL（表由 `sql/01_init.sql` 创建），user-service 用
`fake_user_service` 内存桩替代，数据库不可用时整组自动跳过。
"""

from datetime import date, timedelta

import pytest

from app.core.exceptions import BizException
from tests.conftest import (
    DB_REASON,
    DB_READY,
    FAKE_DEFAULT_BALANCE,
    QaBilling,
    count_records,
    count_usage,
)


TODAY = date.today()


# ---------------------------------------------------------------- 记账成功路径


def test_record_writes_detail_and_usage(qa: QaBilling, fake_user_service) -> None:
    """一次成功上报：写明细 + 扣分 + 累计当日用量。"""

    request_id = qa.next_request_id()
    body = qa.record(points=5, request_id=request_id)

    assert body["code"] == 0
    data = body["data"]
    assert data["request_id"] == request_id
    assert data["cost"] == 5
    assert data["call_status"] == "success"
    assert data["duplicated"] is False
    assert data["balance_after"] == FAKE_DEFAULT_BALANCE - 5
    assert data["stat_date"] == TODAY.isoformat()
    assert data["call_count"] == 1
    assert data["total_cost"] == 5

    assert count_records(request_id) == 1
    assert count_usage(qa.user_id, TODAY) == 1


def test_record_forwards_request_id_to_user_service(qa: QaBilling, fake_user_service) -> None:
    """扣分请求必须复用全链路 requestId，幂等键才能端到端一致。"""

    request_id = qa.next_request_id()
    qa.record(points=3, request_id=request_id)

    assert fake_user_service.deduct_paths == ["/internal/user/points/deduct"]
    service_name, method, path, kwargs = fake_user_service.calls[0]
    payload = kwargs["json"]

    assert service_name == "user-service"
    assert (method, path) == ("POST", "/internal/user/points/deduct")
    assert payload["user_id"] == qa.user_id
    assert payload["amount"] == 3
    assert payload["biz_type"] == "call"
    assert payload["request_id"] == request_id


def test_free_call_skips_deduct_but_still_checks_user(
    qa: QaBilling, fake_user_service
) -> None:
    """单价为 0 的免费能力不产生扣分请求，但账号状态仍需校验，明细照常记录。"""

    body = qa.record(points=0)

    assert body["code"] == 0
    assert body["data"]["cost"] == 0
    assert fake_user_service.deduct_paths == []
    assert fake_user_service.check_paths == ["/internal/user/check"]
    assert count_records(body["data"]["request_id"]) == 1


def test_daily_usage_accumulates_across_calls(qa: QaBilling, fake_user_service) -> None:
    qa.record(points=5)
    qa.record(points=7)
    body = qa.record(points=3)

    assert body["data"]["call_count"] == 3
    assert body["data"]["total_cost"] == 15
    # 同日同用户同能力只保留一行聚合
    assert count_usage(qa.user_id, TODAY) == 1


# ---------------------------------------------------------------- 幂等


def test_repeated_record_is_idempotent(qa: QaBilling, fake_user_service) -> None:
    """重复上报同一 requestId 只计一次费，且不重复调用扣分。"""

    request_id = qa.next_request_id()
    first = qa.record(points=5, request_id=request_id)
    second = qa.record(points=5, request_id=request_id)

    assert first["code"] == 0 and second["code"] == 0
    assert second["data"]["duplicated"] is True
    assert second["data"]["record_id"] == first["data"]["record_id"]
    assert second["data"]["call_count"] == 1
    assert second["data"]["total_cost"] == 5

    assert count_records(request_id) == 1
    assert count_usage(qa.user_id, TODAY) == 1
    assert len(fake_user_service.calls) == 1  # 只扣了一次


def test_same_request_id_with_different_payload_returns_3002(
    qa: QaBilling, fake_user_service
) -> None:
    """同一 requestId 承载了不同调用，明确拒绝而不是静默改写。"""

    request_id = qa.next_request_id()
    qa.record(points=5, request_id=request_id)

    body = qa.record(points=7, request_id=request_id)

    assert body["code"] == 3002
    assert body["data"] is None
    assert count_records(request_id) == 1
    assert len(fake_user_service.calls) == 1


# ---------------------------------------------------------------- 失败不得半成功


@pytest.mark.parametrize(
    ("code", "message"),
    [(3001, "积分不足"), (1005, "用户不存在或已被禁用"), (4002, "下游服务暂不可用")],
)
def test_deduct_failure_leaves_no_half_state(
    qa: QaBilling, fake_user_service, code: int, message: str
) -> None:
    """扣分失败时明细与日用量都回滚，不出现“记了调用但没扣分”。"""

    fake_user_service.error = BizException(code, message)
    request_id = qa.next_request_id()

    body = qa.record(points=5, request_id=request_id)

    assert body["code"] == code
    assert body["data"] is None
    assert count_records(request_id) == 0
    assert count_usage(qa.user_id, TODAY) == 0


def test_failure_does_not_block_retry_with_same_request_id(
    qa: QaBilling, fake_user_service
) -> None:
    """失败回滚后同一 requestId 可以重试成功（明细未被残留占用）。"""

    request_id = qa.next_request_id()
    fake_user_service.error = BizException(3001, "积分不足")
    assert qa.record(points=5, request_id=request_id)["code"] == 3001

    fake_user_service.error = None
    body = qa.record(points=5, request_id=request_id)

    assert body["code"] == 0
    assert body["data"]["duplicated"] is False
    assert count_records(request_id) == 1


# ---------------------------------------------------------------- 明细查询


def test_records_are_isolated_per_user(
    qa: QaBilling, fake_user_service, api
) -> None:
    """调用明细只返回当前用户自己的数据。"""

    qa.record(points=5)
    other = QaBilling(api, index=1)

    assert qa.records()["data"]["total"] == 1
    assert other.records()["data"]["total"] == 0


def test_records_support_paging_and_filters(qa: QaBilling, fake_user_service) -> None:
    qa.record(points=5, service_name="ai-chat-service", status="success")
    qa.record(points=3, service_name="ai-chat-service", status="degraded")
    qa.record(points=2, service_name="rag-service", status="failed")

    page = qa.records(page=1, page_size=2)["data"]
    assert page["total"] == 3
    assert len(page["list"]) == 2
    assert page["page"] == 1 and page["page_size"] == 2

    by_service = qa.records(service_name="rag-service")["data"]
    assert by_service["total"] == 1
    assert by_service["list"][0]["service_name"] == "rag-service"

    by_status = qa.records(call_status="degraded")["data"]
    assert by_status["total"] == 1
    assert by_status["list"][0]["call_status"] == "degraded"


def test_records_respect_date_window(qa: QaBilling, fake_user_service) -> None:
    qa.record(points=5)
    yesterday = TODAY - timedelta(days=1)

    in_range = qa.records(start_date=TODAY.isoformat(), end_date=TODAY.isoformat())
    out_of_range = qa.records(
        start_date=yesterday.isoformat(), end_date=yesterday.isoformat()
    )

    assert in_range["data"]["total"] == 1
    assert out_of_range["data"]["total"] == 0


# ---------------------------------------------------------------- 用量统计


def test_personal_usage_summarises_status_and_dimensions(
    qa: QaBilling, fake_user_service
) -> None:
    qa.record(points=5, status="success")
    qa.record(points=3, status="degraded")
    qa.record(points=2, status="failed", service_name="rag-service")

    data = qa.usage(
        start_date=TODAY.isoformat(), end_date=TODAY.isoformat()
    )["data"]

    assert data["summary"]["call_count"] == 3
    assert data["summary"]["total_cost"] == 10
    assert data["summary"]["success_count"] == 1
    assert data["summary"]["degraded_count"] == 1
    assert data["summary"]["failed_count"] == 1

    # by_day 来自聚合表，与当天明细一致
    assert len(data["by_day"]) == 1
    assert data["by_day"][0]["stat_date"] == TODAY.isoformat()
    assert data["by_day"][0]["call_count"] == 3
    assert data["by_day"][0]["total_cost"] == 10

    services = {item["service_name"]: item for item in data["by_service"]}
    assert services["ai-chat-service"]["total_cost"] == 8
    assert services["rag-service"]["total_cost"] == 2


def test_personal_usage_is_isolated_per_user(
    qa: QaBilling, fake_user_service, api
) -> None:
    qa.record(points=5)
    other = QaBilling(api, index=1)

    data = other.usage(start_date=TODAY.isoformat(), end_date=TODAY.isoformat())["data"]

    assert data["summary"]["call_count"] == 0
    assert data["summary"]["total_cost"] == 0
    assert data["by_day"] == []
    assert data["by_service"] == []


def test_overview_aggregates_across_users(qa: QaBilling, fake_user_service, api) -> None:
    """运营统计按全局口径汇总，并给出用户排行。

    全局统计天然会受库里其它数据影响（例如 `02_seed.sql` 的演示数据），
    因此这里断言**增量**而不是绝对值；排行只断言排序不变式与两名测试用户的存在。
    """

    window = {"start_date": TODAY.isoformat(), "end_date": TODAY.isoformat()}
    before = qa.overview(**window)["data"]["summary"]

    qa.record(points=5)
    other = QaBilling(api, index=1)
    other.record(points=7)

    data = qa.overview(**window)["data"]
    after = data["summary"]

    assert after["call_count"] - before["call_count"] == 2
    assert after["total_cost"] - before["total_cost"] == 12
    assert after["user_count"] - before["user_count"] == 2
    assert after["success_count"] - before["success_count"] == 2

    costs = [item["total_cost"] for item in data["top_users"]]
    assert costs == sorted(costs, reverse=True)

    ranked = {item["user_id"]: item for item in data["top_users"]}
    assert ranked[other.user_id]["total_cost"] == 7
    assert ranked[qa.user_id]["total_cost"] == 5


# ---------------------------------------------------------------- 禁用账号统一拦截

# 网关只校验 JWT 签名与有效期，不知道账号是否已禁用，因此三个查询接口都必须
# 自行校验账号状态（billing 无 user_db 权限，走 /internal/user/check）。
READ_ENDPOINTS = [
    "/api/billing/records",
    "/api/billing/usage",
    "/api/billing/stat/overview",
]


@pytest.mark.parametrize("path", READ_ENDPOINTS)
def test_disabled_user_is_blocked_on_reads(
    qa: QaBilling, fake_user_service, path: str
) -> None:
    fake_user_service.disabled_users.add(qa.user_id)

    body = qa.client.get(path, headers=qa.headers()).json()

    assert body["code"] == 1005
    assert body["data"] is None


@pytest.mark.parametrize("path", READ_ENDPOINTS)
def test_reads_report_4002_when_user_service_unavailable(
    qa: QaBilling, fake_user_service, path: str
) -> None:
    """user-service 不可用时返回 4002，与指南 3.4 的下游降级语义一致。"""

    fake_user_service.error = BizException(4002, "下游服务暂不可用")

    body = qa.client.get(path, headers=qa.headers()).json()

    assert body["code"] == 4002
    assert body["data"] is None


def test_free_call_for_disabled_user_leaves_no_half_state(
    qa: QaBilling, fake_user_service
) -> None:
    """禁用账号连免费能力也不记账：状态校验失败时明细与用量都回滚。"""

    fake_user_service.disabled_users.add(qa.user_id)
    request_id = qa.next_request_id()

    body = qa.record(points=0, request_id=request_id)

    assert body["code"] == 1005
    assert body["data"] is None
    assert count_records(request_id) == 0
    assert count_usage(qa.user_id, TODAY) == 0


def test_reads_work_again_after_user_is_reenabled(
    qa: QaBilling, fake_user_service
) -> None:
    """恢复 normal 后同一个 Token 又能查询，证明拦截只取决于账号状态。"""

    fake_user_service.disabled_users.add(qa.user_id)
    assert qa.records()["code"] == 1005

    fake_user_service.disabled_users.discard(qa.user_id)
    body = qa.records()

    assert body["code"] == 0
    assert body["data"]["total"] == 0
