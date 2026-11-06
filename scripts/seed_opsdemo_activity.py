# -*- coding: utf-8 -*-
"""opsdemo 演示账号（user_db.t_user id=8）模拟使用数据生成器。

设计要点
--------
1. 纯标准库；不依赖 pymysql。所有写入通过「生成 SQL 文件 -> docker cp -> docker exec mysql」完成。
2. 随机性用固定种子（20261104），同一份脚本重复执行得到同样的数据形态。
3. 默认带 reset：先按表清空 user 8 的全部数据，再写入。--no-reset 可关闭。
4. 写库前自动 mysqldump 备份 user 8 相关行到 artifacts/seed-opsdemo/backup-<stamp>/。
5. 写库后用只读 SQL 做 7 类自检，结果写进 summary.json。

口令来源：deploy/.env 的 MYSQL_ROOT_PASSWORD，不落地到任何提交文件。
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import random
import re
import sys
import uuid
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import seed_content_chat_a as content_chat_a  # noqa: E402
import seed_content_chat_b as content_chat_b  # noqa: E402
import seed_content_media as content_media  # noqa: E402
import seed_content_summary as content_summary  # noqa: E402

# ---------------------------------------------------------------- 基础常量

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(PROJECT_ROOT, "deploy", ".env")
CONTAINER = "aihub-pro-mysql"
DEFAULT_OUT_DIR = os.path.join(PROJECT_ROOT, "artifacts", "seed-opsdemo")

USER_ID = 8
RANDOM_SEED = 20261104
SERVICE_NAME = "ai-chat-service"

T_END = dt.datetime(2026, 11, 3, 23, 40, 0)
REGISTER_TIME = dt.datetime(2026, 10, 25, 10, 12, 0)
CALL_EARLIEST_HOUR = (8, 30)
CALL_LATEST_HOUR = (23, 30)

TITLE_MAX = 30
DEGRADED_ASSISTANT = "模型服务暂时不可用，已返回兜底回复，请稍后重试。"

CAPABILITIES: Dict[int, Dict[str, Any]] = {
    1: {
        "code": "chat-completions",
        "name": "多轮对话",
        "price": 5,
        "model": "deepseek-flash",
        "token_source": "upstream",
        "executor": "chat",
    },
    2: {
        "code": "long-summary",
        "name": "长文本摘要",
        "price": 3,
        "model": "deepseek-flash",
        "token_source": "upstream",
        "executor": "summary",
    },
    3: {
        "code": "vision-parse",
        "name": "视觉理解",
        "price": 8,
        "model": "deepseek-flash",
        "token_source": "upstream",
        "executor": "chat",
    },
    2169: {
        "code": "text-to-image",
        "name": "文生图",
        "price": 20,
        "model": "wanx2.1-t2i-turbo",
        "token_source": "missing",
        "executor": "image-generate",
    },
}

API_KEY_PRODUCTION = 3201
API_KEY_DEBUG = 3202
API_KEY_LEGACY = 3203

SESSION_ID_BASE = {1: 9001, 2: 9101, 3: 9201, 2169: 9301}
MESSAGE_ID_BASE = 9401
CALL_ID_BASE = 9501
USAGE_ID_BASE = 9701
POINTS_LOG_ID_BASE = 9801
USER_OPLOG_ID_BASE = 10001
CAP_OPLOG_ID_BASE = 10101

# 每日调用分布（cap 列分别为 cap1 调用次数 / cap2 会话数 / cap3 会话数 / cap4 会话数）
# cap3 的第一条调用必须晚于其 draft->online 审计时间（2026-10-27 10:31:20），
# 因此 10-26 不放视觉理解，10-27 放 2 条，其余日子照旧。
DAY_PLAN: List[Dict[str, Any]] = [
    {"date": "2026-10-25", "cap1_calls": 2, "cap2": 1, "cap3": 0, "cap4": 0, "cap1_sessions": 1, "oc": 0, "pa": 0},
    {"date": "2026-10-26", "cap1_calls": 11, "cap2": 5, "cap3": 0, "cap4": 0, "cap1_sessions": 6, "oc": 3, "pa": 2},
    {"date": "2026-10-27", "cap1_calls": 15, "cap2": 4, "cap3": 2, "cap4": 0, "cap1_sessions": 4, "oc": 4, "pa": 2},
    {"date": "2026-10-28", "cap1_calls": 18, "cap2": 6, "cap3": 2, "cap4": 0, "cap1_sessions": 6, "oc": 6, "pa": 2},
    {"date": "2026-10-29", "cap1_calls": 13, "cap2": 4, "cap3": 2, "cap4": 0, "cap1_sessions": 5, "oc": 5, "pa": 1},
    {"date": "2026-10-30", "cap1_calls": 16, "cap2": 6, "cap3": 2, "cap4": 0, "cap1_sessions": 6, "oc": 7, "pa": 1},
    {"date": "2026-10-31", "cap1_calls": 6, "cap2": 2, "cap3": 1, "cap4": 0, "cap1_sessions": 3, "oc": 3, "pa": 0},
    {"date": "2026-11-01", "cap1_calls": 8, "cap2": 3, "cap3": 1, "cap4": 0, "cap1_sessions": 4, "oc": 4, "pa": 0},
    {"date": "2026-11-02", "cap1_calls": 15, "cap2": 5, "cap3": 2, "cap4": 0, "cap1_sessions": 6, "oc": 6, "pa": 1},
    {"date": "2026-11-03", "cap1_calls": 4, "cap2": 2, "cap3": 2, "cap4": 20, "cap1_sessions": 3, "oc": 6, "pa": 18},
]

# 每日窗口（本地时间）。10-25 是注册当天，首次调用不能早于注册时间。
DEFAULT_WINDOWS = [("09:00", "11:50"), ("13:50", "18:20"), ("20:10", "23:15")]
DAY1_WINDOWS = [("10:40", "11:50"), ("13:50", "18:20"), ("20:10", "23:15")]

# 视觉理解的可用窗口：能力在 2026-10-27 10:31:20 才 draft->online，之后才可调用。
VISION_EARLIEST = ("11:00", "11:50")

# 充值事件（时间, 金额, 原因）
RECHARGES: List[Tuple[dt.datetime, int, str]] = [
    (dt.datetime(2026, 10, 26, 8, 52, 0), 500, "运营预充值：接入联调额度"),
    (dt.datetime(2026, 10, 28, 19, 30, 0), 500, "运营预充值：批量演示数据准备"),
    (dt.datetime(2026, 10, 31, 10, 12, 0), 400, "运营预充值：周末活动演示额度"),
    (dt.datetime(2026, 11, 2, 9, 8, 0), 400, "运营预充值：月度结算前额度补充"),
]

# 摘要能力的降级条目（1 基序号），文生图的降级条目
DEGRADED_SUMMARY_INDEXES = (7, 25)
DEGRADED_IMAGE_INDEX = 12

# 走非 web 入口的对话会话
OPENAI_COMPAT_CHAT_SESSION = "S35"

# 备份说明文案（写进 summary.json 的 backup.note）
NOTE_BACKUP_ORIGINAL = (
    "该目录是首次写库前（round-0，即 opsdemo 原有的测试噪声数据）的原始快照，"
    "也是唯一可用于回滚到「动手之前」的备份；之后的重跑一律 skip_backup=true，"
    "刻意不覆盖它。将来若要回滚，用它恢复后需再跑一次 --no-reset 重建演示数据，"
    "或用 seed.sql 重放。"
)
NOTE_BACKUP_FRESH = (
    "本次写库前按表 mysqldump --where 新导出的 user 8 原始数据（仅含 user 8 相关行），"
    "未覆盖任何历史备份目录。"
)


# ---------------------------------------------------------------- 工具函数


def read_root_password() -> str:
    """从 deploy/.env 读取 MYSQL_ROOT_PASSWORD。"""
    if not os.path.isfile(ENV_PATH):
        raise SystemExit("找不到 deploy/.env，无法读取 MYSQL_ROOT_PASSWORD")
    with open(ENV_PATH, "r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("MYSQL_ROOT_PASSWORD="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if value:
                    return value
    raise SystemExit("deploy/.env 里没有 MYSQL_ROOT_PASSWORD")


def sql_str(value: Optional[str]) -> str:
    """把 Python 字符串转成 MySQL 字符串字面量（含转义）。"""
    if value is None:
        return "NULL"
    out = str(value)
    out = out.replace("\\", "\\\\")
    out = out.replace("'", "\\'")
    out = out.replace("\x00", "\\0")
    out = out.replace("\r", "\\r")
    out = out.replace("\n", "\\n")
    out = out.replace("\x1a", "\\Z")
    return "'" + out + "'"


def sql_dt(value: Optional[dt.datetime]) -> str:
    if value is None:
        return "NULL"
    return "'" + value.strftime("%Y-%m-%d %H:%M:%S") + "'"


def sql_json(value: Any) -> str:
    if value is None:
        return "NULL"
    return sql_str(json.dumps(value, ensure_ascii=False, sort_keys=False))


def sql_int(value: Optional[int]) -> str:
    if value is None:
        return "NULL"
    return str(int(value))


def sql_bool(value: bool) -> str:
    return "1" if value else "0"


def gen_uuid(rng: random.Random) -> str:
    """确定性 UUID4。"""
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def make_title(text: str) -> str:
    return collapse_ws(text)[:TITLE_MAX]


_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")


def estimate_tokens(text: str) -> int:
    """粗略 token 估算：中日韩字符按 1/1.4 计，其余按 1/4 计，至少 1。"""
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    other = len(text) - cjk
    return max(1, int(round(cjk / 1.4 + other / 4.0)))


def parse_hhmm(day: str, hhmm: str) -> dt.datetime:
    hour, minute = hhmm.split(":")
    base = dt.datetime.strptime(day, "%Y-%m-%d")
    return base.replace(hour=int(hour), minute=int(minute))


class WindowMapper(object):
    """把「当日相对秒偏移」映射到真实时间，自动跳过窗口之间的空档。"""

    def __init__(self, windows: Sequence[Tuple[dt.datetime, dt.datetime]]) -> None:
        if not windows:
            raise ValueError("windows 不能为空")
        self.windows = list(windows)
        self.capacity = sum(int((e - s).total_seconds()) for s, e in self.windows)
        if self.capacity <= 0:
            raise ValueError("windows 容量必须为正")

    def at(self, offset_sec: float) -> dt.datetime:
        remain = float(offset_sec)
        for start, end in self.windows:
            span = (end - start).total_seconds()
            if remain < span:
                # 统一截到整秒：DATETIME 列没有小数秒，先截断可保证
                # 落库时间与 duration_ms（整秒差）严格自洽。
                return (start + dt.timedelta(seconds=remain)).replace(microsecond=0)
            remain -= span
        # 超出容量时贴在最后一个窗口末尾前 30 秒，避免越界到窗口外
        return (self.windows[-1][1] - dt.timedelta(seconds=30)).replace(microsecond=0)


# ---------------------------------------------------------------- 数据结构


class RoundRecord(object):
    """一次调用的完整信息。"""

    __slots__ = (
        "session_key",
        "capability_id",
        "round_index",
        "user_text",
        "assistant_text",
        "user_time",
        "assistant_time",
        "degraded",
        "prompt_tokens",
        "completion_tokens",
        "duration_ms",
        "entrypoint",
        "api_key_id",
        "request_id",
        "cost",
        "images",
    )

    def __init__(self, session_key: str, capability_id: int) -> None:
        self.session_key = session_key
        self.capability_id = capability_id
        self.round_index = 0
        self.user_text = ""
        self.assistant_text = ""
        self.user_time: Optional[dt.datetime] = None
        self.assistant_time: Optional[dt.datetime] = None
        self.degraded = False
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.duration_ms = 0
        self.entrypoint = "web"
        self.api_key_id: Optional[int] = None
        self.request_id = ""
        self.cost = 0
        self.images: Optional[List[Dict[str, str]]] = None


class SessionRecord(object):
    __slots__ = ("key", "capability_id", "session_id", "title", "rounds")

    def __init__(self, key: str, capability_id: int, session_id: int) -> None:
        self.key = key
        self.capability_id = capability_id
        self.session_id = session_id
        self.title = ""
        self.rounds: List[RoundRecord] = []

    @property
    def create_time(self) -> dt.datetime:
        return self.rounds[0].user_time  # type: ignore[return-value]

    @property
    def last_message_time(self) -> dt.datetime:
        return max(r.assistant_time for r in self.rounds)  # type: ignore[type-var]


# ---------------------------------------------------------------- 组装会话


def build_chat_sessions() -> List[Dict[str, Any]]:
    sessions = list(content_chat_a.SESSIONS_A) + list(content_chat_b.SESSIONS_B)
    if len(sessions) != 44:
        raise SystemExit("对话会话数量应为 44，实际 %d" % len(sessions))
    total_rounds = sum(len(item["rounds"]) for item in sessions)
    if total_rounds != 108:
        raise SystemExit("对话调用次数应为 108，实际 %d" % total_rounds)
    return sessions


def build_single_turn_sessions() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    docs = [{"key": "M%02d" % (i + 1), "payload": doc} for i, doc in enumerate(content_summary.SUMMARY_DOCS)]
    if len(docs) != 38:
        raise SystemExit("摘要条目应为 38，实际 %d" % len(docs))
    visions = [{"key": "V%02d" % (i + 1), "payload": case} for i, case in enumerate(content_media.VISION_CASES)]
    if len(visions) != 14:
        raise SystemExit("视觉理解条目应为 14，实际 %d" % len(visions))
    images = [{"key": "I%02d" % (i + 1), "payload": case} for i, case in enumerate(content_media.IMAGE_CASES)]
    if len(images) != 20:
        raise SystemExit("文生图条目应为 20，实际 %d" % len(images))
    slugs = [item["payload"]["slug"] for item in images]
    if len(set(slugs)) != len(slugs):
        raise SystemExit("文生图 slug 存在重复")
    return docs, visions, images


# ---------------------------------------------------------------- 排期


def plan_day_times(
    day_cfg: Dict[str, Any],
    blocks: List[Tuple[str, int, int]],
    rng: random.Random,
    windows_spec: Sequence[Tuple[str, str]],
    phase_windows: Sequence[Sequence[Tuple[str, str]]],
) -> Dict[str, List[Tuple[dt.datetime, dt.datetime]]]:
    """为一个排期阶段分配时间。

    blocks: [(session_key, capability_id, n_calls), ...]
    返回 {session_key: [(user_time, assistant_time), ...]}
    """
    day = day_cfg["date"]
    result: Dict[str, List[Tuple[dt.datetime, dt.datetime]]] = {}
    if not blocks:
        return result

    windows = [(parse_hhmm(day, s), parse_hhmm(day, e)) for s, e in phase_windows]
    mapper = WindowMapper(windows)
    capacity = mapper.capacity

    estimates: List[int] = []
    for _key, cap_id, n_calls in blocks:
        per_call = 200 if cap_id != 2169 else 260
        intra = 120 if cap_id != 2169 else 90
        estimates.append(n_calls * per_call + max(0, n_calls - 1) * intra)

    total_est = sum(estimates)
    slack = capacity - total_est
    if slack < 0:
        raise SystemExit("day %s phase 容量不足：capacity=%d est=%d" % (day, capacity, total_est))
    gap = max(20.0, slack / float(len(blocks) + 1))

    cursor = min(gap * 0.5, max(0.0, capacity - total_est - 10.0))
    for idx, (key, cap_id, n_calls) in enumerate(blocks):
        cursor += rng.uniform(0.55, 1.45) * gap
        times: List[Tuple[dt.datetime, dt.datetime]] = []
        for round_idx in range(n_calls):
            if round_idx > 0:
                cursor += rng.uniform(45, 300)
            if cursor >= capacity - 40:
                cursor = max(0.0, capacity - 45 - rng.uniform(5, 30))
            user_off = cursor
            if cap_id == 2169:
                gen_sec = rng.randint(9, 28)
            elif cap_id == 3:
                gen_sec = rng.randint(2, 7)
            else:
                gen_sec = rng.randint(6, 42)
            asst_off = min(user_off + gen_sec, capacity - 5)
            if asst_off <= user_off:
                asst_off = user_off + 1
            user_time = mapper.at(user_off)
            asst_time = mapper.at(asst_off)
            if asst_time <= user_time:
                asst_time = user_time + dt.timedelta(seconds=gen_sec)
            times.append((user_time, asst_time))
            cursor = asst_off
        result[key] = times
    return result


def build_dataset(rng: random.Random) -> Dict[str, Any]:
    chat_sessions_raw = build_chat_sessions()
    doc_items, vision_items, image_items = build_single_turn_sessions()

    sessions: List[SessionRecord] = []
    chat_index = 0
    doc_index = 0
    vision_index = 0
    image_index = 0

    # ---- 逐日排期
    chat_round_times: Dict[str, List[Tuple[dt.datetime, dt.datetime]]] = {}

    for day_cfg in DAY_PLAN:
        date = day_cfg["date"]

        # 当前日要排的 cap1 会话
        day_chat = chat_sessions_raw[chat_index: chat_index + day_cfg["cap1_sessions"]]
        chat_index += day_cfg["cap1_sessions"]
        day_docs = doc_items[doc_index: doc_index + day_cfg["cap2"]]
        doc_index += day_cfg["cap2"]
        day_visions = vision_items[vision_index: vision_index + day_cfg["cap3"]]
        vision_index += day_cfg["cap3"]
        day_images = image_items[image_index: image_index + day_cfg["cap4"]]
        image_index += day_cfg["cap4"]

        windows_spec = DAY1_WINDOWS if date == "2026-10-25" else DEFAULT_WINDOWS
        # 视觉理解必须晚于 draft->online（10-27 10:31:20），所以把它的第一个窗口压到 11:00 之后
        vision_windows = [VISION_EARLIEST] + list(windows_spec[1:])

        single_times: Dict[str, List[Tuple[dt.datetime, dt.datetime]]] = {}

        if date == "2026-11-03":
            # 文生图当天上午才上架、14:26 之后才稳定可调，分四段排
            phase_chat = [(item["key"], 1, len(item["rounds"])) for item in day_chat]
            phase_doc = [("__doc_%d" % i, 2, 1) for i in range(len(day_docs))]
            phase_vis = [("__vis_%d" % i, 3, 1) for i in range(len(day_visions))]
            phase_img = [("__img_%d" % i, 2169, 1) for i in range(len(day_images))]
            chat_round_times.update(
                plan_day_times(day_cfg, phase_chat, rng, windows_spec, [("22:20", "23:25")])
            )
            single_times.update(
                plan_day_times(day_cfg, phase_doc, rng, windows_spec, [("09:10", "11:45")])
            )
            single_times.update(
                plan_day_times(day_cfg, phase_vis, rng, windows_spec, [("13:50", "14:25")])
            )
            single_times.update(
                plan_day_times(day_cfg, phase_img, rng, windows_spec, [("14:40", "21:50")])
            )
        else:
            phase_chat = [(item["key"], 1, len(item["rounds"])) for item in day_chat]
            chat_round_times.update(
                plan_day_times(day_cfg, phase_chat, rng, windows_spec, windows_spec)
            )
            if day_docs:
                single_times.update(
                    plan_day_times(
                        day_cfg,
                        [("__doc_%d" % i, 2, 1) for i in range(len(day_docs))],
                        rng,
                        windows_spec,
                        windows_spec,
                    )
                )
            if day_visions:
                single_times.update(
                    plan_day_times(
                        day_cfg,
                        [("__vis_%d" % i, 3, 1) for i in range(len(day_visions))],
                        rng,
                        windows_spec,
                        vision_windows,
                    )
                )

        # ---- 生成 cap1 会话
        for item in day_chat:
            sess_id = SESSION_ID_BASE[1] + len([s for s in sessions if s.capability_id == 1])
            sess = SessionRecord(item["key"], 1, sess_id)
            times = chat_round_times[item["key"]]
            degraded_rounds = set(item.get("degraded") or [])
            entrypoint = "openai_compat" if item["key"] == OPENAI_COMPAT_CHAT_SESSION else "web"
            for pos, (user_text, assistant_text) in enumerate(item["rounds"], start=1):
                rec = RoundRecord(item["key"], 1)
                rec.round_index = pos
                rec.user_text = user_text
                rec.degraded = pos in degraded_rounds
                rec.assistant_text = DEGRADED_ASSISTANT if rec.degraded else assistant_text
                if not rec.degraded and not rec.assistant_text:
                    raise SystemExit("会话 %s 第 %d 轮 assistant 内容为空" % (item["key"], pos))
                rec.user_time, rec.assistant_time = times[pos - 1]
                rec.entrypoint = entrypoint
                sess.rounds.append(rec)
            sess.title = make_title(item["rounds"][0][0])
            sessions.append(sess)

        # ---- 生成 cap2（摘要）
        for i, item in enumerate(day_docs):
            sess_id = SESSION_ID_BASE[2] + len([s for s in sessions if s.capability_id == 2])
            sess = SessionRecord(item["key"], 2, sess_id)
            source_text, summary_text = item["payload"]
            rec = RoundRecord(item["key"], 2)
            rec.round_index = 1
            rec.user_text = source_text
            rec.degraded = (doc_index - day_cfg["cap2"] + i + 1) in DEGRADED_SUMMARY_INDEXES
            rec.assistant_text = DEGRADED_ASSISTANT if rec.degraded else summary_text
            rec.user_time, rec.assistant_time = single_times["__doc_%d" % i][0]
            sess.rounds.append(rec)
            sess.title = make_title(source_text)
            sessions.append(sess)

        # ---- 生成 cap3（视觉理解）
        for i, item in enumerate(day_visions):
            sess_id = SESSION_ID_BASE[3] + len([s for s in sessions if s.capability_id == 3])
            sess = SessionRecord(item["key"], 3, sess_id)
            user_text, assistant_text = item["payload"]
            rec = RoundRecord(item["key"], 3)
            rec.round_index = 1
            rec.user_text = user_text
            rec.assistant_text = assistant_text
            rec.user_time, rec.assistant_time = single_times["__vis_%d" % i][0]
            sess.rounds.append(rec)
            sess.title = make_title(user_text)
            sessions.append(sess)

        # ---- 生成 cap4（文生图）
        for i, item in enumerate(day_images):
            sess_id = SESSION_ID_BASE[2169] + len([s for s in sessions if s.capability_id == 2169])
            sess = SessionRecord(item["key"], 2169, sess_id)
            payload = item["payload"]
            rec = RoundRecord(item["key"], 2169)
            rec.round_index = 1
            rec.user_text = payload["prompt"]
            rec.degraded = (image_index - day_cfg["cap4"] + i + 1) == DEGRADED_IMAGE_INDEX
            rec.assistant_text = DEGRADED_ASSISTANT if rec.degraded else ""
            rec.images = [
                {
                    "url": "https://picsum.photos/seed/%s/1024/1024" % payload["slug"],
                    "revised_prompt": payload["revised"],
                }
            ]
            rec.user_time, rec.assistant_time = single_times["__img_%d" % i][0]
            sess.rounds.append(rec)
            sess.title = make_title(payload["prompt"])
            sessions.append(sess)

    if chat_index != len(chat_sessions_raw):
        raise SystemExit("cap1 会话未全部排期")
    if doc_index != len(doc_items) or vision_index != len(vision_items) or image_index != len(image_items):
        raise SystemExit("单轮会话未全部排期")

    # ---- 入口与 Key 归属
    assign_entrypoints(sessions, rng)

    # ---- 补齐调用明细字段（token、耗时、成本、request_id）
    for sess in sessions:
        for rec in sess.rounds:
            fill_round_details(sess, rec, rng)

    # ---- 积分流水（注册 + 4 次充值 + 调用扣减）
    points_logs, account = build_points_log(sessions, rng)

    # ---- 日用量
    usage_rows = build_usage_daily(sessions)

    # ---- API Key
    api_keys = build_api_keys(rng)

    # ---- 审计日志
    cap_logs = build_capability_oplog(rng)
    user_logs = build_user_oplog(api_keys, points_logs, rng)

    return {
        "sessions": sessions,
        "points_logs": points_logs,
        "account": account,
        "usage_rows": usage_rows,
        "api_keys": api_keys,
        "cap_logs": cap_logs,
        "user_logs": user_logs,
    }


def assign_entrypoints(sessions: List[SessionRecord], rng: random.Random) -> None:
    """按天分配入口：cap1 默认 web（S35 走 openai_compat），单轮会话按 tp 配额分配。"""
    pa_candidates: List[RoundRecord] = []
    for day_cfg in DAY_PLAN:
        date = day_cfg["date"]
        day_sessions = [
            s for s in sessions
            if s.rounds[0].user_time is not None and s.rounds[0].user_time.strftime("%Y-%m-%d") == date
        ]
        non_chat = [s for s in day_sessions if s.capability_id != 1]
        # 排序：文生图优先走 platform_api，其次视觉理解，最后摘要
        non_chat.sort(key=lambda s: (0 if s.capability_id == 2169 else (1 if s.capability_id == 3 else 2), s.session_id))
        pa_count = day_cfg["pa"]
        oc_count = day_cfg["oc"]
        for idx, sess in enumerate(non_chat):
            if idx < pa_count:
                sess.rounds[0].entrypoint = "platform_api"
                pa_candidates.append(sess.rounds[0])
            elif idx < pa_count + oc_count:
                sess.rounds[0].entrypoint = "openai_compat"
            else:
                sess.rounds[0].entrypoint = "web"

    # openai_compat 一律用 Key A
    for sess in sessions:
        for rec in sess.rounds:
            if rec.entrypoint == "openai_compat":
                rec.api_key_id = API_KEY_PRODUCTION

    # platform_api：10-29 14:12 之前只有 Key A；之后按 3 取 1 用 Key B
    threshold = dt.datetime(2026, 10, 29, 14, 13, 0)
    pa_candidates.sort(key=lambda r: (r.user_time, r.request_id))
    after_idx = 0
    for rec in pa_candidates:
        if rec.user_time is not None and rec.user_time >= threshold:
            rec.api_key_id = API_KEY_DEBUG if after_idx % 3 == 0 else API_KEY_PRODUCTION
            after_idx += 1
        else:
            rec.api_key_id = API_KEY_PRODUCTION


def fill_round_details(sess: SessionRecord, rec: RoundRecord, rng: random.Random) -> None:
    cap = CAPABILITIES[rec.capability_id]
    rec.request_id = gen_uuid(rng)
    gap_sec = int((rec.assistant_time - rec.user_time).total_seconds())  # type: ignore[operator]
    rec.duration_ms = max(1000, gap_sec * 1000)

    if rec.capability_id == 2169:
        rec.prompt_tokens = 0
        rec.completion_tokens = 0
    elif rec.degraded:
        rec.prompt_tokens = 0
        rec.completion_tokens = 0
    else:
        history = "".join(r.user_text + r.assistant_text for r in sess.rounds[: rec.round_index - 1])
        rec.prompt_tokens = estimate_tokens(history + rec.user_text) + 8
        rec.completion_tokens = estimate_tokens(rec.assistant_text)

    rec.cost = 0 if rec.degraded else cap["price"]


def build_points_log(
    sessions: List[SessionRecord], rng: random.Random
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []

    entries.append(
        {
            "sort_key": (REGISTER_TIME, 1),
            "user_id": USER_ID,
            "direction": "in",
            "amount": 100,
            "biz_type": "register",
            "request_id": "register-8",
            "remark": "注册赠送初始积分",
            "create_time": REGISTER_TIME,
        }
    )

    for when, amount, reason in RECHARGES:
        entries.append(
            {
                "sort_key": (when, 2),
                "user_id": USER_ID,
                "direction": "in",
                "amount": amount,
                "biz_type": "admin_adjust",
                "request_id": "admin-%s-8-%d" % (gen_uuid(rng), amount),
                "remark": "运营调整：%s" % reason,
                "create_time": when,
                "_reason": reason,
            }
        )

    for sess in sessions:
        for rec in sess.rounds:
            if rec.cost <= 0:
                continue
            cap = CAPABILITIES[rec.capability_id]
            entries.append(
                {
                    "sort_key": (rec.user_time, 3),
                    "user_id": USER_ID,
                    "direction": "out",
                    "amount": rec.cost,
                    "biz_type": "call",
                    "request_id": rec.request_id,
                    "remark": "%s mode=per_call price=%d" % (cap["code"], rec.cost),
                    "create_time": rec.user_time,
                }
            )

    entries.sort(key=lambda item: item["sort_key"])

    seen_times: Dict[dt.datetime, int] = {}
    for entry in entries:
        seen_times[entry["create_time"]] = seen_times.get(entry["create_time"], 0) + 1

    balance = 0
    for idx, entry in enumerate(entries):
        if entry["direction"] == "in":
            balance += entry["amount"]
        else:
            balance -= entry["amount"]
        if balance < 0:
            raise SystemExit("余额链出现负数：%s %s" % (entry["create_time"], entry["request_id"]))
        entry["balance_after"] = balance
        entry["id"] = POINTS_LOG_ID_BASE + idx

    account = {
        "balance": balance,
        "frozen": 0,
        "version": len(entries),
        "update_time": entries[-1]["create_time"],
    }
    return entries, account


def build_usage_daily(sessions: List[SessionRecord]) -> List[Dict[str, Any]]:
    buckets: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for sess in sessions:
        for rec in sess.rounds:
            key = (rec.user_time.strftime("%Y-%m-%d"), rec.capability_id)  # type: ignore[union-attr]
            bucket = buckets.get(key)
            if bucket is None:
                bucket = {
                    "stat_date": key[0],
                    "user_id": USER_ID,
                    "capability_id": key[1],
                    "call_count": 0,
                    "total_cost": 0,
                    "first_time": rec.user_time,
                    "last_time": rec.user_time,
                }
                buckets[key] = bucket
            bucket["call_count"] += 1
            bucket["total_cost"] += rec.cost
            if rec.user_time < bucket["first_time"]:  # type: ignore[operator]
                bucket["first_time"] = rec.user_time
            if rec.user_time > bucket["last_time"]:  # type: ignore[operator]
                bucket["last_time"] = rec.user_time

    rows = []
    for idx, key in enumerate(sorted(buckets.keys())):
        bucket = buckets[key]
        rows.append(
            {
                "id": USAGE_ID_BASE + idx,
                "stat_date": bucket["stat_date"],
                "user_id": bucket["user_id"],
                "capability_id": bucket["capability_id"],
                "call_count": bucket["call_count"],
                "total_cost": bucket["total_cost"],
                "create_time": bucket["first_time"],
                "update_time": bucket["last_time"],
            }
        )
    return rows


def build_api_keys(rng: random.Random) -> List[Dict[str, Any]]:
    specs = [
        {
            "id": API_KEY_PRODUCTION,
            "name": "生产环境集成",
            "status": "enabled",
            "expire_time": None,
            "create_time": dt.datetime(2026, 10, 26, 9, 5, 12),
            "update_time": dt.datetime(2026, 10, 26, 9, 5, 12),
        },
        {
            "id": API_KEY_DEBUG,
            "name": "本地调试 Key",
            "status": "enabled",
            "expire_time": None,
            "create_time": dt.datetime(2026, 10, 29, 14, 12, 40),
            "update_time": dt.datetime(2026, 10, 29, 14, 12, 40),
        },
        {
            "id": API_KEY_LEGACY,
            "name": "旧版脚本 Key",
            "status": "disabled",
            "expire_time": dt.datetime(2026, 10, 31, 23, 59, 59),
            "create_time": dt.datetime(2026, 10, 25, 16, 20, 33),
            "update_time": dt.datetime(2026, 11, 1, 9, 12, 8),
        },
    ]
    keys = []
    for spec in specs:
        access_key = "ak_" + "".join(rng.choice("0123456789abcdef") for _ in range(24))
        secret = "sk_" + "".join(rng.choice("0123456789abcdef") for _ in range(48))
        item = dict(spec)
        item["access_key"] = access_key
        item["secret_hash"] = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        item["secret_mask"] = "sk_****" + secret[-4:]
        item["user_id"] = USER_ID
        keys.append(item)
    return keys


# ---------------------------------------------------------------- 能力目录审计


def cap_snapshot(code: str, name: str, category_id: int, price: int, description: str, **overrides: Any) -> Dict[str, Any]:
    snap: Dict[str, Any] = {
        "code": code,
        "name": name,
        "path": "/api/chat/completions",
        "unit": "",
        "category_id": category_id,
        "billing_mode": "per_call",
        "price_per_call": price,
        "max_output_tokens": 1024,
        "exposed_to_market": 1,
        "openai_alias": None,
        "provider_alias": "",
        "status": "online",
        "description": description,
    }
    snap.update(overrides)
    return snap


CHAT_DESC_FINAL = "多轮对话与文本生成，支持 Mock 与真实模型；主闭环演示能力"
SUMMARY_DESC_FINAL = "把长文档压缩成可执行的结论与行动项"
VISION_DESC_FINAL = "从图片中识别对象与结构；保持 draft 用于验证市场接口不会返回未上架能力"
IMAGE_DESC_FINAL = "根据文本提示词生成图片（DashScope 通义万相）"


def build_capability_oplog(rng: random.Random) -> List[Dict[str, Any]]:
    chat_final = cap_snapshot("chat-completions", "多轮对话", 1, 5, CHAT_DESC_FINAL)
    summary_final = cap_snapshot("long-summary", "长文本摘要", 1, 3, SUMMARY_DESC_FINAL)
    vision_final = cap_snapshot(
        "vision-parse", "视觉理解", 2, 8, VISION_DESC_FINAL, openai_alias="ds-vision", provider_alias="ds2"
    )
    image_final = cap_snapshot(
        "text-to-image",
        "文生图",
        2,
        20,
        IMAGE_DESC_FINAL,
        openai_alias="qwen_text2image",
        provider_alias="dashscope-image",
    )

    rows: List[Dict[str, Any]] = []

    def add(when: dt.datetime, resource_type: str, resource_id: str, action: str,
            before: Optional[Dict[str, Any]], after: Optional[Dict[str, Any]]) -> None:
        rows.append(
            {
                "create_time": when,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "action": action,
                "before_json": before,
                "after_json": after,
            }
        )

    # cap1：多轮对话（2 条）
    add(dt.datetime(2026, 10, 28, 16, 44, 2), "capability", "1", "update",
        {"max_output_tokens": 512}, {"max_output_tokens": 1024})
    add(dt.datetime(2026, 11, 3, 0, 26, 11), "capability", "1", "update",
        {"description": "多轮对话与文本生成，支持 Mock 与真实模型"},
        {"description": CHAT_DESC_FINAL})

    # cap2：长文本摘要（2 条，含一次描述回滚）
    add(dt.datetime(2026, 11, 2, 23, 28, 53), "capability", "2", "update",
        {"description": SUMMARY_DESC_FINAL},
        {"description": "把长文档压缩成结论与行动项（试验文案）"})
    add(dt.datetime(2026, 11, 2, 23, 29, 10), "capability", "2", "rollback",
        {"description": "把长文档压缩成结论与行动项（试验文案）"},
        {"description": SUMMARY_DESC_FINAL})

    # cap3：视觉理解（10 条）
    vision_draft = cap_snapshot(
        "vision-parse", "视觉理解", 2, 8, VISION_DESC_FINAL,
        status="draft", max_output_tokens=512, exposed_to_market=0,
        openai_alias=None, provider_alias="",
    )
    add(dt.datetime(2026, 10, 26, 9, 12, 40), "capability", "3", "create", None, vision_draft)
    add(dt.datetime(2026, 10, 27, 10, 31, 20), "capability", "3", "status",
        {"status": "draft"}, {"status": "online"})
    add(dt.datetime(2026, 10, 28, 15, 2, 11), "capability", "3", "update",
        {"openai_alias": None}, {"openai_alias": "ds-vision"})
    add(dt.datetime(2026, 10, 28, 15, 20, 47), "capability", "3", "update",
        {"provider_alias": ""}, {"provider_alias": "ds2"})
    add(dt.datetime(2026, 10, 29, 10, 15, 33), "capability", "3", "update",
        {"max_output_tokens": 512}, {"max_output_tokens": 1024})
    add(dt.datetime(2026, 10, 30, 18, 22, 5), "capability", "3", "status",
        {"status": "online"}, {"status": "offline"})
    add(dt.datetime(2026, 10, 30, 18, 41, 19), "capability", "3", "status",
        {"status": "offline"}, {"status": "online"})
    add(dt.datetime(2026, 11, 3, 20, 38, 22), "capability", "3", "update",
        {"description": VISION_DESC_FINAL},
        {"description": "从图片中识别对象与结构（试验文案，待评估）"})
    add(dt.datetime(2026, 11, 3, 20, 41, 5), "capability", "3", "rollback",
        {"description": "从图片中识别对象与结构（试验文案，待评估）"},
        {"description": VISION_DESC_FINAL})
    add(dt.datetime(2026, 11, 3, 20, 44, 10), "capability", "3", "update",
        {"exposed_to_market": 0}, {"exposed_to_market": 1})

    # cap2169：文生图（9 条）
    image_draft = cap_snapshot(
        "text-to-image", "文生图", 2, 20, "根据文本提示词生成图片",
        status="draft", max_output_tokens=512, exposed_to_market=0,
        openai_alias=None, provider_alias="",
    )
    add(dt.datetime(2026, 11, 3, 8, 33, 38), "capability", "2169", "create", None, image_draft)
    add(dt.datetime(2026, 11, 3, 9, 2, 10), "capability", "2169", "status",
        {"status": "draft"}, {"status": "online"})
    add(dt.datetime(2026, 11, 3, 9, 20, 44), "capability", "2169", "update",
        {"openai_alias": None}, {"openai_alias": "qwen_text2image"})
    add(dt.datetime(2026, 11, 3, 9, 36, 2), "capability", "2169", "update",
        {"provider_alias": ""}, {"provider_alias": "dashscope-image"})
    add(dt.datetime(2026, 11, 3, 13, 58, 40), "capability", "2169", "update",
        {"max_output_tokens": 512}, {"max_output_tokens": 1024})
    add(dt.datetime(2026, 11, 3, 14, 4, 15), "capability", "2169", "update",
        {"exposed_to_market": 0}, {"exposed_to_market": 1})
    add(dt.datetime(2026, 11, 3, 14, 12, 55), "capability", "2169", "status",
        {"status": "online"}, {"status": "offline"})
    add(dt.datetime(2026, 11, 3, 14, 26, 7), "capability", "2169", "status",
        {"status": "offline"}, {"status": "online"})
    add(dt.datetime(2026, 11, 3, 19, 45, 46), "capability", "2169", "update",
        {"description": "根据文本提示词生成图片"},
        {"description": IMAGE_DESC_FINAL})

    # 分类排序调整（1 条）
    add(dt.datetime(2026, 11, 3, 0, 12, 8), "category", "2", "update",
        {"code": "multimodal", "name": "多模态", "sort": 30, "status": "enabled"},
        {"code": "multimodal", "name": "多模态", "sort": 20, "status": "enabled"})

    rows.sort(key=lambda row: row["create_time"])
    for idx, row in enumerate(rows):
        row["id"] = CAP_OPLOG_ID_BASE + idx
        row["request_id"] = gen_uuid(rng)
    if len(rows) != 24:
        raise SystemExit("capability 审计条数应为 24，实际 %d" % len(rows))
    return rows


def build_user_oplog(
    api_keys: List[Dict[str, Any]], points_logs: List[Dict[str, Any]], rng: random.Random
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    # 4 条积分调整，与 4 次充值一一对应
    for entry in points_logs:
        if entry["biz_type"] != "admin_adjust":
            continue
        before_balance = entry["balance_after"] - entry["amount"]
        rows.append(
            {
                "create_time": entry["create_time"],
                "resource_type": "points",
                "resource_id": str(USER_ID),
                "action": "adjust_points",
                "before_json": {"balance": before_balance, "daily_points_limit": 0},
                "after_json": {
                    "balance": entry["balance_after"],
                    "amount": entry["amount"],
                    "reason": entry["_reason"],
                },
            }
        )

    # 3 条 Key 创建（创建时一定 enabled，禁用是之后单独的 apikey/status 动作）
    for key in api_keys:
        masked = key["access_key"][:8] + "****" + key["access_key"][-4:]
        rows.append(
            {
                "create_time": key["create_time"],
                "resource_type": "apikey",
                "resource_id": str(key["id"]),
                "action": "create",
                "before_json": None,
                "after_json": {
                    "name": key["name"],
                    "access_key": masked,
                    "secret_mask": key["secret_mask"],
                    "status": "enabled",
                    "expire_time": key["expire_time"].strftime("%Y-%m-%d %H:%M:%S") if key["expire_time"] else None,
                },
            }
        )

    # 1 条 Key 禁用
    rows.append(
        {
            "create_time": dt.datetime(2026, 11, 1, 9, 12, 8),
            "resource_type": "apikey",
            "resource_id": str(API_KEY_LEGACY),
            "action": "status",
            "before_json": {"status": "enabled"},
            "after_json": {"status": "disabled"},
        }
    )

    # 6 条示例用户启停
    user_status_plan = [
        (dt.datetime(2026, 10, 30, 15, 8, 41), "552", "normal", "disabled", "示例账号异常登录临时停用"),
        (dt.datetime(2026, 10, 30, 18, 2, 9), "552", "disabled", "normal", "核实为本人操作，恢复账号"),
        (dt.datetime(2026, 11, 1, 11, 26, 30), "663", "normal", "disabled", "试用额度异常消耗，临时停用"),
        (dt.datetime(2026, 11, 1, 16, 41, 12), "663", "disabled", "normal", "客户确认后恢复账号"),
        (dt.datetime(2026, 11, 2, 14, 5, 55), "896", "normal", "disabled", "违规提示词批量调用，临时停用"),
        (dt.datetime(2026, 11, 2, 20, 17, 3), "896", "disabled", "normal", "已签署使用承诺书，恢复账号"),
    ]
    for when, uid, before_status, after_status, _reason in user_status_plan:
        rows.append(
            {
                "create_time": when,
                "resource_type": "user",
                "resource_id": uid,
                "action": "status",
                "before_json": {"status": before_status},
                "after_json": {"status": after_status},
            }
        )

    rows.sort(key=lambda row: row["create_time"])
    for idx, row in enumerate(rows):
        row["id"] = USER_OPLOG_ID_BASE + idx
        row["request_id"] = gen_uuid(rng)
    if len(rows) != 14:
        raise SystemExit("user 审计条数应为 14，实际 %d" % len(rows))
    return rows


# ---------------------------------------------------------------- SQL 渲染

DELETE_STATEMENTS = [
    "DELETE FROM user_db.t_points_log WHERE user_id = 8",
    "DELETE FROM user_db.t_api_key WHERE user_id = 8",
    "DELETE FROM user_db.t_operation_log WHERE operator_id = '8'",
    "DELETE FROM billing_db.t_call_record WHERE user_id = 8",
    "DELETE FROM billing_db.t_usage_daily WHERE user_id = 8",
    "DELETE FROM ai_chat_db.t_chat_message WHERE user_id = '8'",
    "DELETE FROM ai_chat_db.t_chat_session WHERE user_id = '8'",
    # spec 的清理表里没列 capability 审计，但为了让「capability 审计 = 24 条」可重放，
    # 这里同样清掉 operator_id = '8' 的旧审计行（写库前已备份）。
    "DELETE FROM capability_db.t_operation_log WHERE operator_id = '8'",
]

BACKUP_TABLES = [
    ("user_db", "t_points_log", "user_id = 8"),
    ("user_db", "t_api_key", "user_id = 8"),
    ("user_db", "t_operation_log", "operator_id = '8'"),
    ("billing_db", "t_call_record", "user_id = 8"),
    ("billing_db", "t_usage_daily", "user_id = 8"),
    ("ai_chat_db", "t_chat_message", "user_id = '8'"),
    ("ai_chat_db", "t_chat_session", "user_id = '8'"),
    ("capability_db", "t_operation_log", "operator_id = '8'"),
]


def render_sql(dataset: Dict[str, Any], reset: bool) -> str:
    lines: List[str] = []
    add = lines.append

    add("-- opsdemo 模拟使用数据（自动生成，请勿手工编辑）")
    add("SET NAMES utf8mb4;")
    add("SET SESSION sql_mode = 'STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION';")
    add("SET FOREIGN_KEY_CHECKS = 0;")
    add("")
    add("START TRANSACTION;")
    add("")

    if reset:
        add("-- 1. 清理 user 8 的既有数据")
        for stmt in DELETE_STATEMENTS:
            add(stmt + ";")
        add("")

    # 2. API Key
    add("-- 2. API Key（只写哈希与掩码）")
    for key in dataset["api_keys"]:
        add(
            "INSERT INTO user_db.t_api_key "
            "(id, user_id, name, access_key, secret_hash, secret_mask, status, expire_time, create_time, update_time, is_deleted) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0);"
            % (
                sql_int(key["id"]),
                sql_int(key["user_id"]),
                sql_str(key["name"]),
                sql_str(key["access_key"]),
                sql_str(key["secret_hash"]),
                sql_str(key["secret_mask"]),
                sql_str(key["status"]),
                sql_dt(key["expire_time"]),
                sql_dt(key["create_time"]),
                sql_dt(key["update_time"]),
            )
        )
    add("")

    # 3. 会话
    add("-- 3. 会话")
    sessions: List[SessionRecord] = dataset["sessions"]
    for sess in sessions:
        add(
            "INSERT INTO ai_chat_db.t_chat_session "
            "(id, user_id, title, last_message_time, create_time, update_time, is_deleted) "
            "VALUES (%s, '8', %s, %s, %s, %s, 0);"
            % (
                sql_int(sess.session_id),
                sql_str(sess.title),
                sql_dt(sess.last_message_time),
                sql_dt(sess.create_time),
                sql_dt(sess.last_message_time),
            )
        )
    add("")

    # 4. 消息
    add("-- 4. 消息")
    message_id = MESSAGE_ID_BASE
    for sess in sessions:
        for rec in sess.rounds:
            add(
                "INSERT INTO ai_chat_db.t_chat_message "
                "(id, session_id, user_id, role, content, call_status, token_count, error_code, create_time, update_time, is_deleted) "
                "VALUES (%s, %s, '8', 'user', %s, %s, 0, NULL, %s, %s, 0);"
                % (
                    sql_int(message_id),
                    sql_int(sess.session_id),
                    sql_str(rec.user_text),
                    sql_str("degraded" if rec.degraded else "success"),
                    sql_dt(rec.user_time),
                    sql_dt(rec.user_time),
                )
            )
            message_id += 1
            status = "degraded" if rec.degraded else "success"
            token_count = 0 if rec.degraded else rec.prompt_tokens + rec.completion_tokens
            add(
                "INSERT INTO ai_chat_db.t_chat_message "
                "(id, session_id, user_id, role, content, call_status, token_count, error_code, create_time, update_time, is_deleted) "
                "VALUES (%s, %s, '8', 'assistant', %s, %s, %s, NULL, %s, %s, 0);"
                % (
                    sql_int(message_id),
                    sql_int(sess.session_id),
                    sql_str(rec.assistant_text),
                    sql_str(status),
                    sql_int(token_count),
                    sql_dt(rec.assistant_time),
                    sql_dt(rec.assistant_time),
                )
            )
            message_id += 1
    add("")

    # 5. 调用账单
    add("-- 5. 调用账单")
    call_id = CALL_ID_BASE
    for sess in sessions:
        for rec in sess.rounds:
            cap = CAPABILITIES[rec.capability_id]
            token_source = "missing" if (rec.degraded or rec.capability_id == 2169) else cap["token_source"]
            add(
                "INSERT INTO billing_db.t_call_record "
                "(id, request_id, user_id, capability_id, service_name, unit_price, cost, billing_mode, "
                "prompt_tokens, completion_tokens, token_source, units, call_status, duration_ms, model_name, "
                "images, api_key_id, entrypoint, create_time, update_time, is_deleted) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, 'per_call', %s, %s, %s, 1, %s, %s, %s, %s, %s, %s, %s, %s, 0);"
                % (
                    sql_int(call_id),
                    sql_str(rec.request_id),
                    sql_int(USER_ID),
                    sql_int(rec.capability_id),
                    sql_str(SERVICE_NAME),
                    sql_int(cap["price"]),
                    sql_int(rec.cost),
                    sql_int(rec.prompt_tokens),
                    sql_int(rec.completion_tokens),
                    sql_str(token_source),
                    sql_str("degraded" if rec.degraded else "success"),
                    sql_int(rec.duration_ms),
                    sql_str(cap["model"]),
                    sql_json(rec.images),
                    sql_int(rec.api_key_id),
                    sql_str(rec.entrypoint),
                    sql_dt(rec.user_time),
                    sql_dt(rec.user_time),
                )
            )
            call_id += 1
    add("")

    # 6. 日用量
    add("-- 6. 日用量")
    for row in dataset["usage_rows"]:
        add(
            "INSERT INTO billing_db.t_usage_daily "
            "(id, stat_date, user_id, capability_id, call_count, total_cost, create_time, update_time, is_deleted) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0);"
            % (
                sql_int(row["id"]),
                sql_str(row["stat_date"]),
                sql_int(row["user_id"]),
                sql_int(row["capability_id"]),
                sql_int(row["call_count"]),
                sql_int(row["total_cost"]),
                sql_dt(row["create_time"]),
                sql_dt(row["update_time"]),
            )
        )
    add("")

    # 7. 积分流水
    add("-- 7. 积分流水")
    for entry in dataset["points_logs"]:
        add(
            "INSERT INTO user_db.t_points_log "
            "(id, user_id, direction, amount, balance_after, biz_type, request_id, remark, create_time, update_time, is_deleted) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0);"
            % (
                sql_int(entry["id"]),
                sql_int(entry["user_id"]),
                sql_str(entry["direction"]),
                sql_int(entry["amount"]),
                sql_int(entry["balance_after"]),
                sql_str(entry["biz_type"]),
                sql_str(entry["request_id"]),
                sql_str(entry["remark"]),
                sql_dt(entry["create_time"]),
                sql_dt(entry["create_time"]),
            )
        )
    add("")

    # 8. 账户
    account = dataset["account"]
    add("-- 8. 积分账户")
    add(
        "UPDATE user_db.t_points_account SET balance = %s, frozen = %s, version = %s, update_time = %s "
        "WHERE user_id = %s;"
        % (
            sql_int(account["balance"]),
            sql_int(account["frozen"]),
            sql_int(account["version"]),
            sql_dt(account["update_time"]),
            sql_int(USER_ID),
        )
    )
    add("")

    # 9. 审计日志
    add("-- 9. capability 审计")
    for row in dataset["cap_logs"]:
        add(
            "INSERT INTO capability_db.t_operation_log "
            "(id, operator_id, operator_name, resource_type, resource_id, action, before_json, after_json, request_id, create_time, is_deleted) "
            "VALUES (%s, '8', 'opsdemo', %s, %s, %s, %s, %s, %s, %s, 0);"
            % (
                sql_int(row["id"]),
                sql_str(row["resource_type"]),
                sql_str(row["resource_id"]),
                sql_str(row["action"]),
                sql_json(row["before_json"]),
                sql_json(row["after_json"]),
                sql_str(row["request_id"]),
                sql_dt(row["create_time"]),
            )
        )
    add("")
    add("-- 10. user 审计")
    for row in dataset["user_logs"]:
        add(
            "INSERT INTO user_db.t_operation_log "
            "(id, operator_id, operator_name, resource_type, resource_id, action, before_json, after_json, request_id, create_time, is_deleted) "
            "VALUES (%s, '8', 'opsdemo', %s, %s, %s, %s, %s, %s, %s, 0);"
            % (
                sql_int(row["id"]),
                sql_str(row["resource_type"]),
                sql_str(row["resource_id"]),
                sql_str(row["action"]),
                sql_json(row["before_json"]),
                sql_json(row["after_json"]),
                sql_str(row["request_id"]),
                sql_dt(row["create_time"]),
            )
        )
    add("")

    add("COMMIT;")
    add("")
    return "\n".join(lines)


# ---------------------------------------------------------------- 自检 SQL

CHECK_SQL = r"""
SELECT 'C01' AS chk, '账单条数 = 180' AS name,
       IF(COUNT(*) = 180, 1, 0) AS ok, CAST(COUNT(*) AS CHAR) AS detail
FROM billing_db.t_call_record WHERE user_id = 8 AND is_deleted = 0
UNION ALL
SELECT 'C02', 'capability 分布 108/38/14/20',
       IF(SUM(capability_id = 1) = 108 AND SUM(capability_id = 2) = 38
          AND SUM(capability_id = 3) = 14 AND SUM(capability_id = 2169) = 20, 1, 0),
       CONCAT(SUM(capability_id = 1), '/', SUM(capability_id = 2), '/', SUM(capability_id = 3), '/', SUM(capability_id = 2169))
FROM billing_db.t_call_record WHERE user_id = 8 AND is_deleted = 0
UNION ALL
SELECT 'C03', '会话数 = 116', IF(COUNT(*) = 116, 1, 0), CAST(COUNT(*) AS CHAR)
FROM ai_chat_db.t_chat_session WHERE user_id = '8' AND is_deleted = 0
UNION ALL
SELECT 'C04', '消息数 = 360', IF(COUNT(*) = 360, 1, 0), CAST(COUNT(*) AS CHAR)
FROM ai_chat_db.t_chat_message WHERE user_id = '8' AND is_deleted = 0
UNION ALL
SELECT 'C05', '积分流水 = 178', IF(COUNT(*) = 178, 1, 0), CAST(COUNT(*) AS CHAR)
FROM user_db.t_points_log WHERE user_id = 8 AND is_deleted = 0
UNION ALL
SELECT 'C06', '流水构成 register1/admin4/call173',
       IF(SUM(biz_type = 'register') = 1 AND SUM(biz_type = 'admin_adjust') = 4 AND SUM(biz_type = 'call') = 173, 1, 0),
       CONCAT(SUM(biz_type = 'register'), '/', SUM(biz_type = 'admin_adjust'), '/', SUM(biz_type = 'call'))
FROM user_db.t_points_log WHERE user_id = 8 AND is_deleted = 0
UNION ALL
SELECT 'C07', '余额链递推无断点', IF(IFNULL(SUM(bad), 0) = 0, 1, 0), CONCAT('断点数=', IFNULL(SUM(bad), 0))
FROM (
  SELECT CASE WHEN prev_balance IS NOT NULL
              AND balance_after <> prev_balance + IF(direction = 'in', amount, -amount)
         THEN 1 ELSE 0 END AS bad
  FROM (
    SELECT balance_after, direction, amount,
           LAG(balance_after) OVER (ORDER BY create_time, id) AS prev_balance
    FROM user_db.t_points_log WHERE user_id = 8 AND is_deleted = 0
  ) chain
) chk
UNION ALL
SELECT 'C08', '余额无负数且首条为 100',
       IF(MIN(balance_after) >= 0 AND (SELECT balance_after FROM user_db.t_points_log
                                       WHERE user_id = 8 AND biz_type = 'register' ORDER BY create_time LIMIT 1) = 100, 1, 0),
       CONCAT('min=', MIN(balance_after))
FROM user_db.t_points_log WHERE user_id = 8 AND is_deleted = 0
UNION ALL
SELECT 'C09', '账户余额/版本/冻结与流水一致',
       IF(a.balance = (SELECT balance_after FROM user_db.t_points_log WHERE user_id = 8 AND is_deleted = 0
                       ORDER BY create_time DESC, id DESC LIMIT 1)
          AND a.version = (SELECT COUNT(*) FROM user_db.t_points_log WHERE user_id = 8 AND is_deleted = 0)
          AND a.frozen = 0
          AND a.update_time = (SELECT MAX(create_time) FROM user_db.t_points_log WHERE user_id = 8 AND is_deleted = 0), 1, 0),
       CONCAT('balance=', a.balance, ',version=', a.version)
FROM user_db.t_points_account a WHERE a.user_id = 8
UNION ALL
SELECT 'C10', '每笔 cost>0 账单都有同 request_id/金额/时间/类型流水',
       IF(COUNT(*) = 0, 1, 0), CONCAT('缺失=', COUNT(*))
FROM billing_db.t_call_record c
WHERE c.user_id = 8 AND c.is_deleted = 0 AND c.cost > 0
  AND NOT EXISTS (
    SELECT 1 FROM user_db.t_points_log p
    WHERE p.request_id = c.request_id AND p.user_id = 8 AND p.is_deleted = 0
      AND p.direction = 'out' AND p.biz_type = 'call'
      AND p.amount = c.cost AND p.create_time = c.create_time)
UNION ALL
SELECT 'C11', '每条 call 流水都有对应账单',
       IF(COUNT(*) = 0, 1, 0), CONCAT('缺失=', COUNT(*))
FROM user_db.t_points_log p
WHERE p.user_id = 8 AND p.is_deleted = 0 AND p.biz_type = 'call'
  AND NOT EXISTS (
    SELECT 1 FROM billing_db.t_call_record c
    WHERE c.request_id = p.request_id AND c.user_id = 8 AND c.is_deleted = 0
      AND c.cost = p.amount AND c.create_time = p.create_time)
UNION ALL
SELECT 'C12', '降级 7 条且降级账单无流水',
       IF((SELECT COUNT(*) FROM billing_db.t_call_record WHERE user_id = 8 AND is_deleted = 0 AND call_status = 'degraded') = 7
          AND (SELECT COUNT(*) FROM billing_db.t_call_record c
               WHERE c.user_id = 8 AND c.is_deleted = 0 AND c.cost = 0
                 AND EXISTS (SELECT 1 FROM user_db.t_points_log p WHERE p.request_id = c.request_id)) = 0, 1, 0),
       (SELECT CAST(COUNT(*) AS CHAR) FROM billing_db.t_call_record WHERE user_id = 8 AND is_deleted = 0 AND call_status = 'degraded')
UNION ALL
SELECT 'C13', 't_usage_daily 与账单按(日期,能力)聚合一致',
       IF(COUNT(*) = 0, 1, 0), CONCAT('不一致=', COUNT(*))
FROM (
  SELECT d.stat_date AS sd, d.capability_id AS cid, d.call_count AS dc, d.total_cost AS dtc,
         b.cnt AS bc, b.cost AS btc
  FROM billing_db.t_usage_daily d
  LEFT JOIN (
    SELECT DATE(create_time) AS day, capability_id, COUNT(*) AS cnt, SUM(cost) AS cost
    FROM billing_db.t_call_record WHERE user_id = 8 AND is_deleted = 0
    GROUP BY DATE(create_time), capability_id
  ) b ON b.day = d.stat_date AND b.capability_id = d.capability_id
  WHERE d.user_id = 8 AND d.is_deleted = 0
) u
WHERE u.bc IS NULL OR u.dc <> u.bc OR u.dtc <> u.btc
UNION ALL
SELECT 'C14', 't_usage_daily 无多余组合',
       IF(COUNT(*) = 0, 1, 0), CONCAT('多余=', COUNT(*))
FROM (
  SELECT DATE(create_time) AS day, capability_id
  FROM billing_db.t_call_record WHERE user_id = 8 AND is_deleted = 0
  GROUP BY DATE(create_time), capability_id
) b
WHERE NOT EXISTS (
  SELECT 1 FROM billing_db.t_usage_daily d
  WHERE d.user_id = 8 AND d.is_deleted = 0
    AND d.stat_date = b.day AND d.capability_id = b.capability_id)
UNION ALL
SELECT 'C15', '会话 create_time = 首条 user 消息时间',
       IF(COUNT(*) = 0, 1, 0), CONCAT('不一致=', COUNT(*))
FROM ai_chat_db.t_chat_session s
WHERE s.user_id = '8' AND s.is_deleted = 0
  AND s.create_time <> (SELECT MIN(m.create_time) FROM ai_chat_db.t_chat_message m
                        WHERE m.session_id = s.id AND m.role = 'user' AND m.is_deleted = 0)
UNION ALL
SELECT 'C16', '会话 last_message_time = 末条 assistant 时间',
       IF(COUNT(*) = 0, 1, 0), CONCAT('不一致=', COUNT(*))
FROM ai_chat_db.t_chat_session s
WHERE s.user_id = '8' AND s.is_deleted = 0
  AND s.last_message_time <> (SELECT MAX(m.create_time) FROM ai_chat_db.t_chat_message m
                              WHERE m.session_id = s.id AND m.role = 'assistant' AND m.is_deleted = 0)
UNION ALL
SELECT 'C17', 'user 消息 token_count = 0',
       IF(COUNT(*) = 0, 1, 0), CONCAT('异常=', COUNT(*))
FROM ai_chat_db.t_chat_message WHERE user_id = '8' AND is_deleted = 0 AND role = 'user' AND token_count <> 0
UNION ALL
SELECT 'C18', 'assistant token_count = prompt + completion（cap1 总量对齐）',
       IF(
         (SELECT IFNULL(SUM(token_count), 0) FROM ai_chat_db.t_chat_message
          WHERE user_id = '8' AND role = 'assistant' AND session_id BETWEEN 9001 AND 9044) =
         (SELECT IFNULL(SUM(prompt_tokens + completion_tokens), 0) FROM billing_db.t_call_record
          WHERE user_id = 8 AND capability_id = 1 AND is_deleted = 0), 1, 0),
       CONCAT(
         (SELECT IFNULL(SUM(token_count), 0) FROM ai_chat_db.t_chat_message
          WHERE user_id = '8' AND role = 'assistant' AND session_id BETWEEN 9001 AND 9044), '/',
         (SELECT IFNULL(SUM(prompt_tokens + completion_tokens), 0) FROM billing_db.t_call_record
          WHERE user_id = 8 AND capability_id = 1 AND is_deleted = 0))
UNION ALL
SELECT 'C19', '消息时间在会话内严格递增',
       IF(COUNT(*) = 0, 1, 0), CONCAT('逆序=', COUNT(*))
FROM (
  SELECT id, create_time,
         LAG(create_time) OVER (PARTITION BY session_id ORDER BY create_time, id) AS prev_time
  FROM ai_chat_db.t_chat_message WHERE user_id = '8' AND is_deleted = 0
) t
WHERE t.prev_time IS NOT NULL AND t.create_time <= t.prev_time
UNION ALL
SELECT 'C20', '所有时间落在 10-25 10:12 ~ 11-03 23:40',
       IF(COUNT(*) = 0, 1, 0), CONCAT('越界=', COUNT(*))
FROM (
  SELECT create_time AS t FROM billing_db.t_call_record WHERE user_id = 8
  UNION ALL SELECT create_time FROM user_db.t_points_log WHERE user_id = 8
  UNION ALL SELECT create_time FROM ai_chat_db.t_chat_session WHERE user_id = '8'
  UNION ALL SELECT create_time FROM ai_chat_db.t_chat_message WHERE user_id = '8'
  UNION ALL SELECT create_time FROM user_db.t_operation_log WHERE operator_id = '8'
  UNION ALL SELECT create_time FROM capability_db.t_operation_log WHERE operator_id = '8'
) allt
WHERE allt.t < '2026-10-25 10:12:00' OR allt.t > '2026-11-03 23:40:00'
UNION ALL
SELECT 'C21', '调用时间都在 08:30-23:30 内',
       IF(COUNT(*) = 0, 1, 0), CONCAT('越界=', COUNT(*))
FROM billing_db.t_call_record
WHERE user_id = 8
  AND (TIME(create_time) < '08:30:00' OR TIME(create_time) > '23:30:00')
UNION ALL
SELECT 'C22', '入口与 Key 归属正确',
       IF(COUNT(*) = 0, 1, 0), CONCAT('异常=', COUNT(*))
FROM billing_db.t_call_record
WHERE user_id = 8 AND is_deleted = 0
  AND ( (entrypoint = 'web' AND api_key_id IS NOT NULL)
     OR (entrypoint = 'openai_compat' AND api_key_id IS NULL)
     OR (entrypoint = 'platform_api' AND api_key_id IS NULL)
     OR (api_key_id IS NOT NULL AND api_key_id NOT IN (3201, 3202)) )
UNION ALL
SELECT 'C23', 'request_id 全为 UUID4 且不重复',
       IF(
         (SELECT COUNT(*) FROM billing_db.t_call_record WHERE user_id = 8
          AND request_id NOT REGEXP '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$') = 0
         AND (SELECT COUNT(*) FROM user_db.t_points_log WHERE user_id = 8
              AND biz_type = 'call'
              AND request_id NOT REGEXP '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$') = 0
         AND (SELECT COUNT(*) FROM (
                SELECT request_id FROM billing_db.t_call_record WHERE user_id = 8
                GROUP BY request_id HAVING COUNT(*) > 1) dup1) = 0
         AND (SELECT COUNT(*) FROM (
                SELECT request_id FROM user_db.t_points_log WHERE user_id = 8
                GROUP BY request_id HAVING COUNT(*) > 1) dup2) = 0, 1, 0),
       'uuid+唯一'
UNION ALL
SELECT 'C24', '文生图账单：images/零 token/missing/9-28 秒',
       IF(COUNT(*) = 0, 1, 0), CONCAT('异常=', COUNT(*))
FROM billing_db.t_call_record
WHERE user_id = 8 AND capability_id = 2169 AND is_deleted = 0
  AND NOT (
    JSON_VALID(images) AND JSON_LENGTH(images) = 1
    AND JSON_UNQUOTE(JSON_EXTRACT(images, '$[0].url')) LIKE 'https://picsum.photos/seed/%'
    AND JSON_UNQUOTE(JSON_EXTRACT(images, '$[0].revised_prompt')) IS NOT NULL
    AND prompt_tokens = 0 AND completion_tokens = 0 AND token_source = 'missing'
    AND duration_ms BETWEEN 9000 AND 28000)
UNION ALL
SELECT 'C25', '文生图 assistant：成功为空串、降级为兜底文案，token 均为 0',
       IF(COUNT(*) = 0, 1, 0), CONCAT('异常=', COUNT(*))
FROM ai_chat_db.t_chat_message
WHERE user_id = '8' AND role = 'assistant' AND session_id BETWEEN 9301 AND 9320
  AND ( token_count <> 0
     OR (call_status = 'success' AND content <> '')
     OR (call_status = 'degraded' AND content <> '模型服务暂时不可用，已返回兜底回复，请稍后重试。') )
UNION ALL
SELECT 'C26', '标题非空且互不相同（>=110 个不同标题）',
       IF(SUM(CHAR_LENGTH(title) = 0) = 0 AND COUNT(DISTINCT title) >= 110, 1, 0),
       CONCAT('不同标题=', COUNT(DISTINCT title))
FROM ai_chat_db.t_chat_session WHERE user_id = '8' AND is_deleted = 0
UNION ALL
SELECT 'C27', '审计条数 capability=24 / user=14',
       IF((SELECT COUNT(*) FROM capability_db.t_operation_log WHERE operator_id = '8') = 24
          AND (SELECT COUNT(*) FROM user_db.t_operation_log WHERE operator_id = '8') = 14, 1, 0),
       CONCAT((SELECT COUNT(*) FROM capability_db.t_operation_log WHERE operator_id = '8'), '/',
              (SELECT COUNT(*) FROM user_db.t_operation_log WHERE operator_id = '8'))
UNION ALL
SELECT 'C28', '每日调用量 3/16/21/26/19/24/9/12/22/28',
       IF(COUNT(*) = 10 AND SUM(IF(x.got = w.want, 1, 0)) = 10, 1, 0),
       CONCAT('天=', COUNT(*), ' 命中=', SUM(IF(x.got = w.want, 1, 0)))
FROM (
  SELECT DATE(create_time) AS d, COUNT(*) AS got
  FROM billing_db.t_call_record WHERE user_id = 8 AND is_deleted = 0
  GROUP BY DATE(create_time)
) x
JOIN (
  SELECT '2026-10-25' AS d, 3 AS want UNION ALL SELECT '2026-10-26', 16 UNION ALL
  SELECT '2026-10-27', 21 UNION ALL SELECT '2026-10-28', 26 UNION ALL
  SELECT '2026-10-29', 19 UNION ALL SELECT '2026-10-30', 24 UNION ALL
  SELECT '2026-10-31', 9 UNION ALL SELECT '2026-11-01', 12 UNION ALL
  SELECT '2026-11-02', 22 UNION ALL SELECT '2026-11-03', 28
) w ON w.d = x.d
UNION ALL
SELECT 'C29', '实扣积分合计 = 1120', IF(SUM(cost) = 1120, 1, 0), CAST(SUM(cost) AS CHAR)
FROM billing_db.t_call_record WHERE user_id = 8 AND is_deleted = 0
UNION ALL
SELECT 'C31', '视觉理解调用均晚于 cap3 draft→online 审计时间',
       IF(COUNT(*) = 0, 1, 0), CONCAT('早于上架=', COUNT(*))
FROM billing_db.t_call_record
WHERE user_id = 8 AND capability_id = 3 AND is_deleted = 0
  AND create_time <= (
    SELECT create_time FROM capability_db.t_operation_log
    WHERE operator_id = '8' AND resource_type = 'capability' AND resource_id = '3'
      AND action = 'status'
      AND JSON_UNQUOTE(JSON_EXTRACT(after_json, '$.status')) = 'online'
      AND JSON_UNQUOTE(JSON_EXTRACT(before_json, '$.status')) = 'draft'
    ORDER BY create_time LIMIT 1)
UNION ALL
SELECT 'C32', 'apikey/create 快照 status 一律为 enabled',
       IF(COUNT(*) = 0, 1, 0), CONCAT('异常=', COUNT(*))
FROM user_db.t_operation_log
WHERE operator_id = '8' AND resource_type = 'apikey' AND action = 'create'
  AND JSON_UNQUOTE(JSON_EXTRACT(after_json, '$.status')) <> 'enabled'
UNION ALL
SELECT 'C33', 'Key 3203 审计链 enabled → disabled 自洽',
       IF(COUNT(*) = 2, 1, 0), CONCAT('相关审计=', COUNT(*))
FROM user_db.t_operation_log
WHERE operator_id = '8' AND resource_type = 'apikey' AND resource_id = '3203'
  AND ( (action = 'create' AND JSON_UNQUOTE(JSON_EXTRACT(after_json, '$.status')) = 'enabled')
     OR (action = 'status' AND JSON_UNQUOTE(JSON_EXTRACT(before_json, '$.status')) = 'enabled'
         AND JSON_UNQUOTE(JSON_EXTRACT(after_json, '$.status')) = 'disabled') )
UNION ALL
SELECT 'C34', '单轮会话 duration_ms = 首末消息秒差 × 1000',
       IF(COUNT(*) = 0, 1, 0), CONCAT('不一致=', COUNT(*))
FROM billing_db.t_call_record c
JOIN ai_chat_db.t_chat_session s
  ON s.user_id = '8' AND s.is_deleted = 0 AND s.id BETWEEN 9101 AND 9320 AND s.create_time = c.create_time
WHERE c.user_id = 8 AND c.is_deleted = 0
  AND c.duration_ms <> TIMESTAMPDIFF(SECOND, s.create_time, s.last_message_time) * 1000
UNION ALL
SELECT 'C35', '消息时间无小数秒（DATETIME 一致，无截断偏差）',
       IF(COUNT(*) = 0, 1, 0), CONCAT('含小数=', COUNT(*))
FROM (
  SELECT create_time AS t FROM billing_db.t_call_record WHERE user_id = 8
  UNION ALL SELECT create_time FROM ai_chat_db.t_chat_message WHERE user_id = '8'
  UNION ALL SELECT last_message_time FROM ai_chat_db.t_chat_session WHERE user_id = '8'
) tt
WHERE MICROSECOND(tt.t) <> 0
UNION ALL
SELECT 'C30', 'API Key 3 把（2 enabled + 1 disabled 且过期）',
       IF(COUNT(*) = 3 AND SUM(status = 'enabled') = 2 AND SUM(status = 'disabled') = 1
          AND MAX(CASE WHEN status = 'disabled' THEN IF(expire_time IS NOT NULL, 1, 0) ELSE 1 END) = 1, 1, 0),
       CONCAT(COUNT(*), ' 把')
FROM user_db.t_api_key WHERE user_id = 8 AND is_deleted = 0
"""


# ---------------------------------------------------------------- 执行封装


class Runner(object):
    def __init__(self, password: str, dry_run: bool = False) -> None:
        self.password = password
        self.dry_run = dry_run
        self.remote_dir = "/tmp/seed_opsdemo"

    def run(self, argv: List[str], description: str) -> str:
        import subprocess

        proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            raise SystemExit(
                "%s 失败（exit=%d）\nSTDOUT:\n%s\nSTDERR:\n%s"
                % (description, proc.returncode, proc.stdout, proc.stderr)
            )
        return proc.stdout

    def ensure_remote_dir(self) -> None:
        self.run(["docker", "exec", CONTAINER, "mkdir", "-p", self.remote_dir], "创建容器临时目录")

    def push(self, local_path: str, remote_name: str) -> None:
        self.run(
            ["docker", "cp", local_path, "%s:%s/%s" % (CONTAINER, self.remote_dir, remote_name)],
            "复制 %s 到容器" % remote_name,
        )

    def pull_dir(self, remote_path: str, local_path: str) -> None:
        os.makedirs(local_path, exist_ok=True)
        self.run(
            ["docker", "cp", "%s:%s/." % (CONTAINER, remote_path), local_path],
            "从容器取回 %s" % remote_path,
        )

    def write_remote_script(self, local_path: str, content: str) -> None:
        with open(local_path, "w", encoding="utf-8", newline="\n") as fp:
            fp.write(content)

    def exec_script(self, script_name: str, description: str) -> str:
        return self.run(
            ["docker", "exec", CONTAINER, "bash", "%s/%s" % (self.remote_dir, script_name), self.password],
            description,
        )

    def query(self, sql_text: str, name: str) -> List[List[str]]:
        """在容器里跑只读 SQL，返回按行切分的结果（TSV）。"""
        local_path = os.path.join(self.local_tmp_dir, name)
        with open(local_path, "w", encoding="utf-8", newline="\n") as fp:
            fp.write(sql_text)
        self.push(local_path, name)
        out = self.run(
            [
                "docker", "exec", CONTAINER, "bash", "-c",
                'export MYSQL_PWD="$1"; mysql -uroot --default-character-set=utf8mb4 -N -B < %s/%s'
                % (self.remote_dir, name),
                "_",
                self.password,
            ],
            "执行只读 SQL %s" % name,
        )
        rows: List[List[str]] = []
        for line in out.splitlines():
            if not line.strip():
                continue
            rows.append(line.split("\t"))
        return rows


def run_backup(runner: Runner, backup_dir: str) -> Dict[str, int]:
    """mysqldump --where 备份 user 8 相关行。"""
    os.makedirs(backup_dir, exist_ok=True)
    lines = ["set -e", 'export MYSQL_PWD="$1"', 'OUT=%s/backup' % runner.remote_dir,
             'rm -rf "$OUT"', 'mkdir -p "$OUT"', ""]
    for schema, table, where in BACKUP_TABLES:
        lines.append(
            'mysqldump -uroot --default-character-set=utf8mb4 --no-create-info --complete-insert '
            '--skip-extended-insert --where="%s" %s %s > "$OUT/%s.%s.sql"'
            % (where, schema, table, schema, table)
        )
    lines.append('echo "__BACKUP_OK__"')
    script_path = os.path.join(os.path.dirname(backup_dir), "_backup.sh")
    runner.write_remote_script(script_path, "\n".join(lines) + "\n")
    runner.push(script_path, "backup.sh")
    runner.exec_script("backup.sh", "导出 user 8 备份")
    runner.pull_dir(runner.remote_dir + "/backup", backup_dir)
    return {
        "backup_dir": backup_dir,
        "files": sorted(os.listdir(backup_dir)) if os.path.isdir(backup_dir) else [],
    }


def run_seed(runner: Runner, sql_path: str) -> None:
    lines = ["set -e", 'export MYSQL_PWD="$1"']
    lines.append("mysql -uroot --default-character-set=utf8mb4 < %s/seed.sql" % runner.remote_dir)
    lines.append('echo "__SEED_OK__"')
    script_path = os.path.join(runner.local_tmp_dir, "_seed.sh")
    runner.write_remote_script(script_path, "\n".join(lines) + "\n")
    runner.push(sql_path, "seed.sql")
    runner.push(script_path, "seed.sh")
    runner.exec_script("seed.sh", "执行 seed.sql")


def parse_checks(rows: List[List[str]]) -> List[Dict[str, Any]]:
    checks = []
    for row in rows:
        if len(row) < 4:
            continue
        checks.append({"id": row[0], "name": row[1], "ok": row[2] == "1", "detail": row[3]})
    return checks


# ---------------------------------------------------------------- 主流程


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="生成 opsdemo（user 8）模拟使用数据")
    parser.add_argument("--reset", action="store_true", default=True, help="写入前清空 user 8 数据（默认开启）")
    parser.add_argument("--no-reset", dest="reset", action="store_false", help="保留既有数据直接追加")
    parser.add_argument("--dry-run", action="store_true", help="只生成 SQL 文件，不连数据库")
    parser.add_argument("--skip-backup", action="store_true", help="跳过备份（重跑时保留首次的原始备份）")
    parser.add_argument("--check-only", action="store_true", help="不写库，只跑只读自检并刷新 summary.json")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help="产物目录")
    args = parser.parse_args(argv)

    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    rng = random.Random(RANDOM_SEED)
    dataset = build_dataset(rng)

    sql_text = render_sql(dataset, reset=args.reset)
    sql_path = os.path.join(out_dir, "seed.sql")
    with open(sql_path, "w", encoding="utf-8", newline="\n") as fp:
        fp.write(sql_text)

    sessions: List[SessionRecord] = dataset["sessions"]
    calls = [rec for sess in sessions for rec in sess.rounds]
    degraded_count = sum(1 for rec in calls if rec.degraded)
    total_cost = sum(rec.cost for rec in calls)

    print("已生成 %s" % sql_path)
    print("会话 %d，调用 %d，降级 %d，实扣积分 %d" % (len(sessions), len(calls), degraded_count, total_cost))

    if args.dry_run:
        print("--dry-run：跳过备份与写库")
        return 0

    password = read_root_password()
    runner = Runner(password)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    next_backup_dir = os.path.join(out_dir, "backup-%s" % stamp)
    runner.local_tmp_dir = os.path.join(out_dir, "_tmp-%s" % stamp)
    os.makedirs(runner.local_tmp_dir, exist_ok=True)
    summary_path = os.path.join(out_dir, "summary.json")

    runner.ensure_remote_dir()

    existing_backups = sorted(
        name for name in os.listdir(out_dir)
        if name.startswith("backup-") and os.path.isdir(os.path.join(out_dir, name))
    )

    # 上一次 summary（用于 check-only 时保留真实写库的信息）
    previous: Dict[str, Any] = {}
    if os.path.isfile(summary_path):
        try:
            with open(summary_path, "r", encoding="utf-8") as fp:
                previous = json.load(fp)
        except (ValueError, OSError):
            previous = {}
    previous_exec = previous.get("execution") or {}

    if args.check_only:
        print("--check-only：跳过备份与写库，只跑只读自检")
        keep = os.path.join(out_dir, existing_backups[0]) if existing_backups else "(无)"
        backup_info = {
            "backup_dir": keep,
            "files": sorted(os.listdir(keep)) if existing_backups else [],
            "note": NOTE_BACKUP_ORIGINAL,
        }
    else:
        print("步骤 1/3：备份 user 8 既有数据 -> %s" % next_backup_dir)
        if args.skip_backup:
            keep = os.path.join(out_dir, existing_backups[0]) if existing_backups else "(无)"
            backup_info = {
                "backup_dir": keep,
                "files": sorted(os.listdir(keep)) if existing_backups else [],
                "note": NOTE_BACKUP_ORIGINAL,
            }
            print("        --skip-backup：沿用已有备份 %s" % keep)
        else:
            backup_info = run_backup(runner, next_backup_dir)
            backup_info["note"] = NOTE_BACKUP_FRESH
            print("        备份文件 %d 个" % len(backup_info["files"]))

        print("步骤 2/3：写入 seed.sql")
        run_seed(runner, sql_path)

    print("步骤 3/3：只读自检")
    check_rows = runner.query(CHECK_SQL, "checks.sql")
    checks = parse_checks(check_rows)
    failed = [item for item in checks if not item["ok"]]

    now_str = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row_total = (
        len(calls)                       # t_call_record
        + len(dataset["usage_rows"])     # t_usage_daily
        + len(sessions)                  # t_chat_session
        + len(calls) * 2                 # t_chat_message
        + len(dataset["points_logs"])    # t_points_log
        + len(dataset["api_keys"])       # t_api_key
        + len(dataset["cap_logs"])       # capability_db.t_operation_log
        + len(dataset["user_logs"])      # user_db.t_operation_log
    )

    if args.check_only:
        execution = {
            "mode": "check_only",
            "last_write": previous_exec.get("last_write"),
            "last_check": {
                "run_at": now_str,
                "checks_total": len(checks),
                "checks_passed": len(checks) - len(failed),
                "checks_failed": len(failed),
            },
        }
    else:
        execution = {
            "mode": "write",
            "last_write": {
                "run_at": now_str,
                "reset": bool(args.reset),
                "skip_backup": bool(args.skip_backup),
                "sql_path": sql_path,
                "backup_dir": backup_info["backup_dir"],
                "backup_files": len(backup_info["files"]),
                "wrote_rows": row_total,
            },
            "last_check": {
                "run_at": now_str,
                "checks_total": len(checks),
                "checks_passed": len(checks) - len(failed),
                "checks_failed": len(failed),
            },
        }

    summary = build_summary(dataset, checks, backup_info, sql_path, execution)
    with open(summary_path, "w", encoding="utf-8", newline="\n") as fp:
        json.dump(summary, fp, ensure_ascii=False, indent=2)
        fp.write("\n")

    print("自检 %d 项，通过 %d 项，失败 %d 项" % (len(checks), len(checks) - len(failed), len(failed)))
    for item in failed:
        print("  [FAIL] %s %s -> %s" % (item["id"], item["name"], item["detail"]))
    print("摘要已写入 %s" % summary_path)

    return 0 if not failed else 2


def build_summary(
    dataset: Dict[str, Any],
    checks: List[Dict[str, Any]],
    backup_info: Dict[str, Any],
    sql_path: str,
    execution: Dict[str, Any],
) -> Dict[str, Any]:
    sessions: List[SessionRecord] = dataset["sessions"]
    calls = [rec for sess in sessions for rec in sess.rounds]

    def counter(values: Iterable[Any]) -> Dict[str, int]:
        result: Dict[str, int] = {}
        for value in values:
            key = str(value)
            result[key] = result.get(key, 0) + 1
        return result

    points_logs = dataset["points_logs"]
    total_in = sum(e["amount"] for e in points_logs if e["direction"] == "in")
    total_out = sum(e["amount"] for e in points_logs if e["direction"] == "out")

    return {
        "user": {"id": USER_ID, "username": "opsdemo", "nickname": "运营演示"},
        "sql_path": sql_path,
        "execution": execution,
        "backup": backup_info,
        "row_counts": {
            "billing_db.t_call_record": len(calls),
            "billing_db.t_usage_daily": len(dataset["usage_rows"]),
            "ai_chat_db.t_chat_session": len(sessions),
            "ai_chat_db.t_chat_message": len(calls) * 2,
            "user_db.t_points_log": len(points_logs),
            "user_db.t_api_key": len(dataset["api_keys"]),
            "capability_db.t_operation_log": len(dataset["cap_logs"]),
            "user_db.t_operation_log": len(dataset["user_logs"]),
        },
        "points": {
            "total_in": total_in,
            "total_out": total_out,
            "opening_balance": 0,
            "closing_balance": dataset["account"]["balance"],
            "version": dataset["account"]["version"],
            "first_log_time": points_logs[0]["create_time"].strftime("%Y-%m-%d %H:%M:%S"),
            "last_log_time": points_logs[-1]["create_time"].strftime("%Y-%m-%d %H:%M:%S"),
            "register_amount": 100,
            "adjustments": [
                {
                    "time": e["create_time"].strftime("%Y-%m-%d %H:%M:%S"),
                    "amount": e["amount"],
                    "reason": e["_reason"],
                    "balance_after": e["balance_after"],
                }
                for e in points_logs
                if e["biz_type"] == "admin_adjust"
            ],
        },
        "distribution": {
            "by_capability": counter(rec.capability_id for rec in calls),
            "by_capability_cost": {
                str(cid): sum(rec.cost for rec in calls if rec.capability_id == cid)
                for cid in (1, 2, 3, 2169)
            },
            "by_entrypoint": counter(rec.entrypoint for rec in calls),
            "by_call_status": counter("degraded" if rec.degraded else "success" for rec in calls),
            "by_api_key": counter(rec.api_key_id for rec in calls),
            "sessions_by_capability": counter(sess.capability_id for sess in sessions),
            "by_day": counter(rec.user_time.strftime("%Y-%m-%d") for rec in calls),
            "degraded_by_capability": counter(rec.capability_id for rec in calls if rec.degraded),
        },
        "checks": {
            "total": len(checks),
            "passed": sum(1 for item in checks if item["ok"]),
            "failed": [item for item in checks if not item["ok"]],
            "items": checks,
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
