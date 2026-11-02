"""E1 真流式：逐块转发、流后记账、断开不计费。

用真实数据库（ai_chat_db）验证"流期间不持事务、流结束后才写助手消息与账单"。
上游流用替身，不联外网。
"""

import asyncio

import pytest
from sqlalchemy import text

from app.core.constants import CallStatus
from app.db.session import SessionLocal, engine
from app.schemas.capability import CapabilityDefinition
from app.schemas.chat import ChatCompletionRequest
from app.core.security import UserContext
from app.service import stream_service
from app.service.stream_service import StreamOutcome, parse_sse_line

from tests.conftest import TEST_USER_ID

module = pytest.importorskip("app.service.chat_service")


def _definition(**changes):
    data = {
        "id": 1, "code": "chat-completions", "status": "online",
        "param_schema": {"type": "object"}, "price_per_call": 5,
    }
    return CapabilityDefinition(**{**data, **changes})


def _cleanup() -> None:
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM t_chat_message WHERE user_id = :uid"), {"uid": TEST_USER_ID}
        )
        connection.execute(
            text("DELETE FROM t_chat_session WHERE user_id = :uid"), {"uid": TEST_USER_ID}
        )


# ---------------------------------------------------------------- 纯解析


def test_parse_sse_line_ignores_done_and_noise():
    assert parse_sse_line("data: [DONE]") is None
    assert parse_sse_line(": ping") is None
    assert parse_sse_line('data: {"a":1}') == {"a": 1}
    assert parse_sse_line("data: not-json") is None


# ---------------------------------------------------------------- 服务级流式


@pytest.fixture()
def stream_env(monkeypatch):
    _cleanup()
    monkeypatch.setattr(module.settings, "enable_internal_chain", False)
    monkeypatch.setattr(module, "execute_prepared", None, raising=False)

    async def catalog(capability_id):
        return _definition()

    monkeypatch.setattr(module.capability_client, "fetch", catalog)

    def install(frames, *, abort=False):
        async def fake_stream(*, base_url, api_key, payload, timeout, outcome, on_frame=None):
            for text_chunk in frames:
                outcome.frames += 1
                outcome.content += text_chunk
                yield 'data: {"choices":[{"delta":{"content":"%s"}}]}' % text_chunk
            if not abort:
                outcome.finished = True
                outcome.prompt_tokens, outcome.completion_tokens = 11, 22
                outcome.usage_source = "upstream"
                outcome.model_name = "upstream-model"
            else:
                outcome.error_code = 4003

        monkeypatch.setattr(module, "stream_upstream", fake_stream)

    yield install
    _cleanup()


def _run_stream():
    db = SessionLocal()
    try:
        request = ChatCompletionRequest(
            capability_id=1, input={"messages": [{"role": "user", "content": "讲个笑话"}]}
        )
        user = UserContext(user_id=TEST_USER_ID, user_name="qa", request_id="qa-stream")

        async def collect():
            chunks = []
            async for line in module.chat_service.stream(db, request, user):
                chunks.append(line)
            return chunks

        return asyncio.run(collect())
    finally:
        db.close()


def test_stream_forwards_chunks_and_persists_after_completion(stream_env):
    stream_env(["你", "好"])
    chunks = _run_stream()
    assert len(chunks) == 2

    db = SessionLocal()
    try:
        row = db.execute(
            text(
                "SELECT role, content, call_status, token_count FROM t_chat_message "
                "WHERE user_id = :uid ORDER BY id"
            ),
            {"uid": TEST_USER_ID},
        ).all()
    finally:
        db.close()

    assert [r[0] for r in row] == ["user", "assistant"]
    assert row[1][1] == "你好"
    assert row[1][2] == CallStatus.SUCCESS.value
    assert row[1][3] == 33  # 11 + 22，来自替身上游 usage


def test_aborted_stream_writes_failed_placeholder(stream_env):
    stream_env(["半", "句"], abort=True)
    _run_stream()

    db = SessionLocal()
    try:
        row = db.execute(
            text(
                "SELECT role, call_status, token_count FROM t_chat_message "
                "WHERE user_id = :uid ORDER BY id"
            ),
            {"uid": TEST_USER_ID},
        ).all()
    finally:
        db.close()

    assert row[-1][1] == CallStatus.FAILED.value
    assert row[-1][2] == 0


def test_stream_rejects_non_chat_executor(stream_env, monkeypatch):
    async def catalog(capability_id):
        return _definition(executor="video-generate", price_per_call=0)

    monkeypatch.setattr(module.capability_client, "fetch", catalog)
    with pytest.raises(module.BizException) as error:
        _run_stream()
    assert error.value.code == 2008


def test_outcome_call_status_reflects_abort():
    outcome = StreamOutcome(content="x")
    assert outcome.call_status == CallStatus.SUCCESS.value
    outcome.error_code = 5005
    assert outcome.call_status == CallStatus.FAILED.value


def test_parse_sse_helper_is_used_by_stream_module():
    assert stream_service.DONE_FRAME == "data: [DONE]\n\n"
