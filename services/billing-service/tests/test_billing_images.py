"""D3 文生图产物落库回归测试。

历史缺陷：`BillingService.record` 直接把 `BillingImage` 模型塞进 `t_call_record.images`
（MySQL JSON 列），flush 时 `json.dumps` 抛
`TypeError: Object of type BillingImage is not JSON serializable`，
真实调用因此返回 `4003 系统内部错误`。

两条防线：
1. 纯内存用例：落库前必须转成 `[{url, revised_prompt}]` 纯 dict，且可被 `json.dumps`
   序列化（不需要数据库，任何环境都会跑）；
2. 连库用例（`qa` 夹具，`TEST_DB_ISOLATED=1` 的独立测试库）：写入后直接读
   `t_call_record.images`，再走对外查询接口原样读回。
"""

import json
from datetime import date

from sqlalchemy import text

from app.db.session import engine
from app.schemas import BillingImage, BillingRecordRequest
from app.service.billing_service import images_for_storage

TODAY = date.today()


def _payload(images: list[dict]) -> BillingRecordRequest:
    return BillingRecordRequest(
        request_id="qa-d3-images",
        user_id=1,
        capability_id=2169,
        service_name="ai-chat-service",
        model="wanx2.1-t2i-turbo",
        points=20,
        status="success",
        duration_ms=11000,
        images=images,
    )


# ---------------------------------------------------------------- 纯内存（不连库）


def test_images_are_converted_to_plain_dicts() -> None:
    """缺陷复现：转换后必须是原生 dict，否则 JSON 列写入失败。"""

    payload = _payload(
        [
            {"url": "https://dashscope.oss/a.png", "revised_prompt": "一只柴犬"},
            {"url": "https://dashscope.oss/b.png", "revised_prompt": ""},
        ]
    )
    assert all(isinstance(item, BillingImage) for item in payload.images)

    stored = images_for_storage(payload.images)

    assert stored == [
        {"url": "https://dashscope.oss/a.png", "revised_prompt": "一只柴犬"},
        {"url": "https://dashscope.oss/b.png", "revised_prompt": ""},
    ]
    assert all(type(item) is dict for item in stored)
    # 关键断言：驱动写 JSON 列时就是这一步序列化，修复前在这里抛 TypeError。
    assert json.loads(json.dumps(stored)) == stored


def test_empty_images_stay_null() -> None:
    """非文生图调用保持 NULL，不写空数组，避免历史记录语义变化。"""

    assert images_for_storage([]) is None
    assert images_for_storage(_payload([]).images) is None


# ---------------------------------------------------------------- 落库与读回（连库）


def test_images_persist_as_dicts_and_read_back(qa, fake_user_service) -> None:
    request_id = qa.next_request_id()
    images = [
        {"url": "https://dashscope.oss/qa-1.png", "revised_prompt": "赛博朋克柴犬"},
        {"url": "https://dashscope.oss/qa-2.png", "revised_prompt": ""},
    ]

    body = qa.record(
        points=20,
        request_id=request_id,
        capability_id=2169,
        model="wanx2.1-t2i-turbo",
        duration_ms=11000,
        images=images,
    )
    assert body["code"] == 0, body
    assert body["data"]["images"] == images

    listed = qa.records(start_date=TODAY.isoformat(), end_date=TODAY.isoformat())
    row = [item for item in listed["data"]["list"] if item["request_id"] == request_id][0]
    assert row["images"] == images
    assert row["capability_id"] == 2169
    assert row["duration_ms"] == 11000

    # 直接读库：列里必须是纯 dict 数组，而不是被驱动字符串化后的怪结构。
    with engine.connect() as connection:
        raw = connection.execute(
            text("SELECT images FROM t_call_record WHERE request_id = :rid"),
            {"rid": request_id},
        ).scalar_one()
    stored = json.loads(raw) if isinstance(raw, str) else raw
    assert stored == images
    assert all(type(item) is dict for item in stored)
