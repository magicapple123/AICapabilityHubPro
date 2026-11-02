"""B2/B3：readiness 与 Prometheus 指标。

两条关键验收：
- readiness 每次真查库：停库（连接失败）必须 503 + 原因码，恢复后立刻 200（不缓存）；
- `/metrics` 输出必需指标的文本格式，且路由标签用模板避免高基数。
"""

import re

from fastapi.testclient import TestClient

from app.db.session import engine
from app.main import app

client = TestClient(app)


def test_ready_returns_200_when_db_is_up():
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["status"] == "READY"
    assert body["data"]["checks"]["db"] == "up"
    assert body["data"]["service"]
    assert "requestId" in body


def test_ready_returns_503_with_reason_when_db_is_down(monkeypatch):
    monkeypatch.setattr(
        engine, "connect",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("db is down")),
    )
    response = client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == 4003
    assert body["data"]["status"] == "NOT_READY"
    assert body["data"]["reason"] == "DB_UNAVAILABLE"
    assert body["data"]["checks"]["db"] == "down"


def test_ready_recovers_without_restart(monkeypatch):
    """状态不缓存：失败后（连接恢复）下一次请求必须立刻回到 200。"""

    original = engine.connect.__get__(engine, type(engine))
    monkeypatch.setattr(
        engine, "connect",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("db is down")),
    )
    assert client.get("/health/ready").status_code == 503

    monkeypatch.setattr(engine, "connect", original)
    assert client.get("/health/ready").status_code == 200


def test_metrics_exposes_required_series():
    client.get("/health/ready")
    response = client.get("/metrics")
    assert response.status_code == 200
    text = response.text
    for name in (
        "http_requests_total",
        "http_request_duration_seconds",
        "db_pool_checkout_wait_seconds",
        "db_pool_checked_out",
        "db_up",
        "model_call_duration_seconds",
        "points_deduct_total",
        "catalog_query_failures_total",
        "upstream_errors_total",
    ):
        assert name in text, name
    assert 'route="/health/ready"' in text


def test_metrics_route_label_never_contains_raw_id():
    """label 里不能出现真实数字 id，否则基数会随数据增长。"""

    client.get("/health/ready")
    text = client.get("/metrics").text
    offenders = [
        line for line in text.splitlines()
        if line.startswith("http_requests_total") and re.search(r'route="[^"]*/\d+', line)
    ]
    assert not offenders, offenders
