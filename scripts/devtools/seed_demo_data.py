#!/usr/bin/env python3
"""给本地开发库播种一批"看起来像真的"演示数据，方便账号 opsdemo 观察各页面效果。

覆盖范围
========
- ``user_db.t_points_account``：把 opsdemo（user_id=8）的余额从真实值抬到 8,000~12,000；
- ``user_db.t_points_log``：新增约 20 条流水（充值 + 能力调用扣费），
  ``balance_after`` 按插入顺序逐条累加，最后一条精确等于账户余额；
- ``billing_db.t_call_record``：新增约 21 条调用明细，覆盖 capability_id 1/2，
  状态覆盖 success / degraded / failed，token 与耗时带真实量级；
- ``billing_db.t_usage_daily``：由上面的调用明细**自然派生**（同事务内累加），
  不额外造表，保证"每日趋势"与"区间汇总"两个口径的金额一致；
- ``ai_chat_db``：3 个中文会话、共 13 条消息，其中 1 条降级、
  1 条硬失败（带 error_code）。

三条必须守住的约束
==================
1. **幂等**：脚本写入的每一行都带标记，执行前先按标记清一遍再写，重复执行不叠加。
   - ``t_points_log.request_id`` / ``t_call_record.request_id``：
     统一前缀 ``DEMO-SEED-``（``DEMO-SEED-C01`` 形式给调用，``DEMO-SEED-R01`` 给充值，
     调用与其扣费流水**复用同一个 requestId**，与线上"全链路 requestId"语义一致）；
   - ``t_chat_session`` / ``t_chat_message``：会话表没有空闲标记列，且标题会直接显示在
     前端侧边栏，写标记会污染演示观感。因此以**本地状态文件**
     ``scripts/devtools/.seed_demo_data_state.json`` 记录写入的会话 ID 作为权威标记，
     并额外以三条固定标题兜底（状态文件丢失时仍能定位并清理）。
2. **可一键清理**：``--clean`` 删除本脚本写入的全部行，并把余额/version 回退到执行前
   的真实值。回退方式是"当前余额 - 本次标记流水的净额"，不依赖任何外部记录，
   所以即使状态文件丢失也能算对。
3. **不碰别人的数据**：只写 ``user_id = 8`` 的行；除按标记清理外不 UPDATE / DELETE
   任何既有行；余额只在**当前真实值**基础上 UPDATE（且是绝对赋值，天然幂等）。

金额口径（与 services 里的真实实现严格对齐，不是凭字段名猜的）
=============================================================
- 计价规则见 ``services/ai-chat-service/app/service/pricing.py``：
  ``per_call`` → ``price_per_call``；``per_token`` →
  ``ceil((prompt*price_1k_in + completion*price_1k_out) / 1000)``；``per_unit`` →
  ``price_per_unit * units``；**降级与失败恒为 0**（``billable=False``）。
- 只有 ``billable`` 的调用才落一条 ``biz_type='call'`` 的扣费流水，反过来，
  本次播种里每条 ``cost > 0`` 的调用都一定有一条同 requestId 的扣费流水，
  不会出现"记账了但没扣分"的半成功状态（billing_service 明确禁止这种数据）。
- ``t_call_record.unit_price``：``per_call`` 写 ``price_per_call``，其它模式写 NULL
  （见 ``execution_billing.report_execution``）。
- ``t_usage_daily`` 只累加不软删（见 ``usage_repository``），清理时用等量减回，
  减到 0/0 的行直接删除，避免留下空壳行。

为什么新流水的时间都集中在"最后一次既有流水之后"
================================================
``t_points_log.balance_after`` 是一条链：第 n 条的 ``balance_after`` 必须等于第 n-1 条
加减本条金额。既有演示数据里这条链已经闭合在"当前余额"上，如果本脚本把流水**回溯**
插入到既有行之间，链就会断（而且不能用 UPDATE 去改既有行的 ``balance_after``，
那是别人的数据）。因此：**所有新流水的时间都严格晚于"既有流水里最晚的 create_time"**。
调用明细与日用量没有链式约束，但为了保持"每条 cost>0 的调用都有对应扣费"，
它们也跟随同一时间窗。趋势图上的早期日期由既有数据自然覆盖。

用法
====
::

    # 1) 只看计划，不写库
    python scripts/devtools/seed_demo_data.py --dry-run

    # 2) 真正写入（先清旧的再写新的，可重复执行）
    python scripts/devtools/seed_demo_data.py

    # 3) 写入并做一致性自检
    python scripts/devtools/seed_demo_data.py --verify

    # 4) 一键清理，回到执行前的状态
    python scripts/devtools/seed_demo_data.py --clean

需要 ``pymysql`` + ``sqlalchemy``（仓库已有）。数据库连接默认取 ``.env`` 里的
``MYSQL_ROOT_PASSWORD`` 连 ``127.0.0.1:3307``；也可用环境变量显式指定：

::

    set DEMO_SEED_DB_URL=mysql+pymysql://root:<password>@127.0.0.1:3307/user_db?charset=utf8mb4

本脚本只做 DML：不建表、不改 schema、不调用任何真实模型接口、不重启任何服务。
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from dataclasses import dataclass
from datetime import date, datetime, time as clock_time, timedelta
from pathlib import Path
from typing import Any, Sequence

# 允许以 `python scripts/devtools/seed_demo_data.py` 直接运行：
# 把 scripts/ 放进 sys.path，才能 import devtools.environment（与 reset_demo_data.py 一致）。
_SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import URL, Connection, Engine, make_url

from devtools.environment import PROJECT_ROOT, read_env

# ---------------------------------------------------------------- 常量

DEMO_USER_ID = 8
DEMO_USERNAME = "opsdemo"

#: 标记前缀：所有本脚本写入的流水与调用明细都用它，清理时按它反查。
REQUEST_PREFIX = "DEMO-SEED-"

#: 数据库连接的环境变量名（值形如 mysql+pymysql://root:pwd@127.0.0.1:3307/user_db）。
DB_URL_ENV = "DEMO_SEED_DB_URL"
DEFAULT_DB_HOST = "127.0.0.1"
DEFAULT_DB_PORT = 3307
DEFAULT_DB_USER = "root"

#: 状态文件：记录写入的会话 ID，作为 t_chat_session / t_chat_message 的权威标记。
STATE_FILENAME = ".seed_demo_data_state.json"
STATE_PATH = Path(__file__).resolve().parent / STATE_FILENAME

#: 本次播种要用的两个在线能力（价格从 capability_db 实时读，不写死）。
CAPABILITY_CODES = ("chat-completions", "long-summary")

#: 目标余额区间与期望落点；实际值由流水数学推出来，落点只用于选充值金额。
BALANCE_MIN = 8_000
BALANCE_MAX = 12_000
BALANCE_TARGET = 8_500

#: 调用明细条数：18 条计费成功 + 2 条降级 + 1 条失败 = 21 条。
TOTAL_CALLS = 21
SUCCESS_CALLS = 18
DEGRADED_CALLS = 2
FAILED_CALLS = 1

#: 两笔充值金额（先大额再小额，模拟两次充值）。
RECHARGE_AMOUNTS = (5_000, 3_500)

#: 固定随机种子：同样的库状态跑两次得到完全一样的数据，便于对比和复现。
RANDOM_SEED = 20261102

#: 调用时间的"白天时段"：08:00~23:00，避免演示数据里出现凌晨三点的调用。
BUSINESS_HOURS_START = clock_time(8, 0)
BUSINESS_HOURS_END = clock_time(23, 0)
#: 相邻调用之间至少留 10 分钟，否则退回整段窗口铺点。
MIN_GAP_SECONDS = 600.0
#: 时间抖动幅度（秒）：±2 分钟，让时刻看起来不像机器生成。
JITTER_SECONDS = 120.0

#: 失败/降级调用的错误码，取值见 ai-chat-service app/core/constants.ModelErrorCode。
ERROR_CODE_TIMEOUT = 5001
ERROR_CODE_UPSTREAM_FAULT = 5005

#: 真实实现里降级/失败占位消息的固定文案，复用它们比自造句子更像线上数据。
DEGRADED_REPLY = "模型服务暂时不可用，已返回兜底回复，请稍后重试。"
FAILED_REPLY = "本次调用失败，未能生成回复，请稍后重试。"

#: 兜底标记：状态文件丢失时，仍按这三条标题定位本脚本写过的会话。
CHAT_TITLES = (
    "帮我对比按次计费和按 token 计费，内部培训要用",
    "总结这次灰度发布暴露的三个问题，附改进建议",
    "自建模型网关一直返回 502，排查顺序怎么走",
)

#: 统计行数用的表清单（交付里要能一眼看到"前 → 后 → clean 后"）。
TABLE_SNAPSHOT = (
    ("user_db", "t_points_account"),
    ("user_db", "t_points_log"),
    ("billing_db", "t_call_record"),
    ("billing_db", "t_usage_daily"),
    ("ai_chat_db", "t_chat_session"),
    ("ai_chat_db", "t_chat_message"),
)


# ---------------------------------------------------------------- 数据结构


@dataclass(frozen=True)
class Capability:
    """capability_db.t_capability 的计价快照。"""

    id: int
    code: str
    billing_mode: str
    price_per_call: int
    price_per_1k_input: int
    price_per_1k_output: int
    price_per_unit: int
    unit: str

    def cost(
        self,
        *,
        prompt_tokens: int,
        completion_tokens: int,
        units: int,
        billable: bool,
    ) -> int:
        """按能力的当时计价规则复算本次消耗；降级/失败恒为 0。

        与 ``services/ai-chat-service/app/service/pricing.py::call_cost`` 逐分支对齐：
        整数运算、向上取整，不使用浮点。
        """

        if not billable:
            return 0
        if self.billing_mode == "per_token":
            weighted = (
                prompt_tokens * self.price_per_1k_input
                + completion_tokens * self.price_per_1k_output
            )
            return 0 if weighted <= 0 else -(-weighted // 1000)
        if self.billing_mode == "per_unit":
            return self.price_per_unit * max(units, 1)
        return self.price_per_call

    @property
    def registered_unit_price(self) -> int | None:
        """t_call_record.unit_price 应登记的值：per_call 记单价，其它模式记 NULL。"""

        return self.price_per_call if self.billing_mode == "per_call" else None


@dataclass(frozen=True)
class CallPlan:
    """一条待写入的调用明细。"""

    request_id: str
    capability: Capability
    create_time: datetime
    call_status: str
    cost: int
    prompt_tokens: int
    completion_tokens: int
    token_source: str
    units: int
    duration_ms: int
    model_name: str
    service_name: str = "ai-chat-service"

    @property
    def billable(self) -> bool:
        """是否产生扣费；只有 billable 的调用才落扣费流水。"""

        return self.cost > 0


@dataclass(frozen=True)
class PointsLogPlan:
    """一条待写入的积分流水（balance_after 已按时间顺序算好）。"""

    request_id: str
    direction: str
    amount: int
    balance_after: int
    biz_type: str
    remark: str
    create_time: datetime


@dataclass(frozen=True)
class ChatMessagePlan:
    """一条待写入的会话消息。"""

    role: str
    content: str
    call_status: str
    token_count: int
    error_code: int | None
    create_time: datetime


@dataclass(frozen=True)
class ChatSessionPlan:
    """一个待写入的会话及其消息。"""

    title: str
    create_time: datetime
    last_message_time: datetime
    messages: tuple[ChatMessagePlan, ...]


@dataclass(frozen=True)
class Baseline:
    """执行前的真实基线：用于算出"清理后应该回到哪里"。"""

    balance: int
    frozen: int
    version: int
    ledger_tail: datetime | None
    marked_net: int
    marked_count: int

    @property
    def pristine_balance(self) -> int:
        """去掉本脚本标记流水之后的余额，即 clean 应该还原到的值。"""

        return self.balance - self.marked_net

    @property
    def pristine_version(self) -> int:
        """去掉本脚本标记流水之后的 version。"""

        return self.version - self.marked_count


@dataclass(frozen=True)
class SeedPlan:
    """一次性算好的完整播种计划。"""

    baseline: Baseline
    calls: tuple[CallPlan, ...]
    points_logs: tuple[PointsLogPlan, ...]
    usage_deltas: tuple[tuple[date, int, int, int], ...]
    chat_sessions: tuple[ChatSessionPlan, ...]

    @property
    def net_points(self) -> int:
        """本次写入流水的净额（收入 - 支出）。"""

        total = 0
        for log in self.points_logs:
            total += log.amount if log.direction == "in" else -log.amount
        return total

    @property
    def final_balance(self) -> int:
        """写入完成后的账户余额。"""

        return self.baseline.pristine_balance + self.net_points

    @property
    def total_messages(self) -> int:
        return sum(len(session.messages) for session in self.chat_sessions)


# ---------------------------------------------------------------- 连接


def resolve_engine() -> tuple[Engine, str]:
    """按环境变量 / .env 组装数据库连接，返回 (engine, 密码来源说明)。

    密码永远不落代码：优先 ``DEMO_SEED_DB_URL``，其次同进程的 ``MYSQL_ROOT_PASSWORD``，
    最后读仓库 ``.env``（本地开发库由 ``scripts/init_dev.py`` 生成）。
    """

    raw_url = os.environ.get(DB_URL_ENV, "").strip()
    if raw_url:
        parsed = make_url(raw_url)
        url = parsed.set(database="user_db")
        engine = create_engine(url, pool_pre_ping=True, future=True)
        return engine, f"环境变量 {DB_URL_ENV}"

    password = os.environ.get("MYSQL_ROOT_PASSWORD", "").strip()
    source = "环境变量 MYSQL_ROOT_PASSWORD"
    if not password:
        password = read_env(PROJECT_ROOT / ".env").get("MYSQL_ROOT_PASSWORD", "")
        source = ".env 的 MYSQL_ROOT_PASSWORD"
    if not password:
        raise SystemExit(
            "未找到数据库密码。请任选其一：\n"
            f"  1) 设置 {DB_URL_ENV}=mysql+pymysql://root:<password>@127.0.0.1:3307/user_db?charset=utf8mb4\n"
            "  2) 设置 MYSQL_ROOT_PASSWORD\n"
            "  3) 先运行 python scripts/init_dev.py 生成 .env"
        )

    url = URL.create(
        drivername="mysql+pymysql",
        username=DEFAULT_DB_USER,
        password=password,
        host=DEFAULT_DB_HOST,
        port=DEFAULT_DB_PORT,
        database="user_db",
        query={"charset": "utf8mb4"},
    )
    engine = create_engine(url, pool_pre_ping=True, future=True)
    return engine, source


# ---------------------------------------------------------------- 读库


def _scalar(conn: Connection, sql: str, params: dict[str, Any]) -> Any:
    return conn.execute(text(sql), params).scalar()


def _as_int(value: Any) -> int:
    """把驱动返回值安全转成 int（可能是 Decimal / str / None，不能直接 int()）。"""

    return 0 if value is None else int(value)


def _clamp_moment(moment: datetime, low: datetime, high: datetime) -> datetime:
    """把时间夹在 [low, high] 内并抹掉微秒，保证写库的值合法。"""

    return min(max(moment, low), high).replace(microsecond=0)


def table_counts(conn: Connection) -> dict[str, int]:
    """六张相关表的全表行数。"""

    counts: dict[str, int] = {}
    for schema, table in TABLE_SNAPSHOT:
        counts[f"{schema}.{table}"] = int(
            _scalar(conn, f"SELECT COUNT(*) FROM {schema}.{table} WHERE 1=1", {}) or 0
        )
    return counts


def user_row_counts(conn: Connection, user_id: int) -> dict[str, int]:
    """只统计 opsdemo 自己的行数，便于确认"到底给它加了多少"。"""

    return {
        "t_points_log": int(
            _scalar(
                conn,
                "SELECT COUNT(*) FROM user_db.t_points_log "
                "WHERE user_id = :u AND is_deleted = 0",
                {"u": user_id},
            )
            or 0
        ),
        "t_call_record": int(
            _scalar(
                conn,
                "SELECT COUNT(*) FROM billing_db.t_call_record "
                "WHERE user_id = :u AND is_deleted = 0",
                {"u": user_id},
            )
            or 0
        ),
        "t_usage_daily": int(
            _scalar(
                conn,
                "SELECT COUNT(*) FROM billing_db.t_usage_daily WHERE user_id = :u",
                {"u": user_id},
            )
            or 0
        ),
        "t_chat_session": int(
            _scalar(
                conn,
                "SELECT COUNT(*) FROM ai_chat_db.t_chat_session "
                "WHERE user_id = :u AND is_deleted = 0",
                {"u": str(user_id)},
            )
            or 0
        ),
    }


def read_baseline(conn: Connection, user_id: int) -> Baseline:
    """读取账户真实基线，并把"本脚本标记流水"从基线里剔除出去。"""

    account = conn.execute(
        text(
            "SELECT balance, frozen, version FROM user_db.t_points_account "
            "WHERE user_id = :u AND is_deleted = 0"
        ),
        {"u": user_id},
    ).one_or_none()
    if account is None:
        raise SystemExit(f"user_id={user_id} 没有积分账户，请先确认账号是否存在")

    marked = conn.execute(
        text(
            "SELECT direction, amount FROM user_db.t_points_log "
            "WHERE user_id = :u AND is_deleted = 0 AND request_id LIKE :prefix"
        ),
        {"u": user_id, "prefix": f"{REQUEST_PREFIX}%"},
    ).all()
    marked_net = 0
    for direction, amount in marked:
        marked_net += _as_int(amount) if direction == "in" else -_as_int(amount)

    # 真实账本尾部：刻意排除本脚本写过的行，否则重复执行时窗口会一直往后漂。
    tail = _scalar(
        conn,
        "SELECT MAX(create_time) FROM user_db.t_points_log "
        "WHERE user_id = :u AND is_deleted = 0 AND request_id NOT LIKE :prefix",
        {"u": user_id, "prefix": f"{REQUEST_PREFIX}%"},
    )

    return Baseline(
        balance=int(account[0]),
        frozen=int(account[1]),
        version=int(account[2]),
        ledger_tail=tail,
        marked_net=marked_net,
        marked_count=len(marked),
    )


def read_user(conn: Connection, user_id: int) -> tuple[str, str, str]:
    """取 (username, role, status)，用于确认播种对象没写错。"""

    row = conn.execute(
        text(
            "SELECT username, role, status FROM user_db.t_user "
            "WHERE id = :u AND is_deleted = 0"
        ),
        {"u": user_id},
    ).one_or_none()
    if row is None:
        raise SystemExit(f"user_id={user_id} 不存在或已删除")
    return str(row[0]), str(row[1]), str(row[2])


def read_capabilities(conn: Connection) -> dict[str, Capability]:
    """从 capability_db 实时读两个在线能力的计价规则（不写死价格）。"""

    placeholders = ", ".join(f":code{i}" for i in range(len(CAPABILITY_CODES)))
    params: dict[str, Any] = {f"code{i}": code for i, code in enumerate(CAPABILITY_CODES)}
    rows = conn.execute(
        text(
            "SELECT id, code, billing_mode, price_per_call, price_per_1k_input, "
            "       price_per_1k_output, price_per_unit, unit, status "
            f"FROM capability_db.t_capability WHERE code IN ({placeholders}) AND is_deleted = 0"
        ),
        params,
    ).all()

    capabilities: dict[str, Capability] = {}
    for row in rows:
        capability = Capability(
            id=int(row[0]),
            code=str(row[1]),
            billing_mode=str(row[2]),
            price_per_call=int(row[3]),
            price_per_1k_input=int(row[4]),
            price_per_1k_output=int(row[5]),
            price_per_unit=int(row[6]),
            unit=str(row[7]),
        )
        if str(row[8]) != "online":
            raise SystemExit(
                f"能力 {capability.code} 当前状态是 {row[8]}，播种出来的调用记录会与"
                "市场页不一致，请先上架该能力"
            )
        capabilities[capability.code] = capability

    missing = [code for code in CAPABILITY_CODES if code not in capabilities]
    if missing:
        raise SystemExit(f"capability_db 缺少能力：{', '.join(missing)}")
    return capabilities


# ---------------------------------------------------------------- 计划


def _business_segments(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """把窗口切成"每天 08:00~23:00"的若干段，避免演示数据出现凌晨 3 点的调用。"""

    segments: list[tuple[datetime, datetime]] = []
    day = start.date()
    last_day = end.date()
    while day <= last_day:
        low = max(datetime.combine(day, BUSINESS_HOURS_START), start)
        high = min(datetime.combine(day, BUSINESS_HOURS_END), end)
        if high > low:
            segments.append((low, high))
        day += timedelta(days=1)
    return segments


def _spread_times(
    start: datetime, end: datetime, count: int, rng: random.Random
) -> list[datetime]:
    """在窗口内均匀铺 count 个时间点，优先落在白天时段，返回严格递增的列表。"""

    if count <= 0:
        return []
    if end <= start:
        raise SystemExit("可用的记账时间窗口为空，请检查既有流水的时间是否已到当前时刻")

    segments = _business_segments(start, end)
    capacity = sum((hi - lo).total_seconds() for lo, hi in segments)
    if not segments or capacity < count * MIN_GAP_SECONDS:
        # 白天时段放不下（例如窗口只剩半小时）：退回整段窗口，
        # 宁可出现夜间调用，也不能丢数据或让时间重复。
        segments = [(start, end)]
        capacity = (end - start).total_seconds()

    times: list[datetime] = []
    for index in range(count):
        # 用"目标进度"跨越多个时段，保证整体分布均匀而不是每天各占一半。
        offset = capacity * (index + 0.5) / count
        for segment_index, (low, high) in enumerate(segments):
            length = (high - low).total_seconds()
            if offset <= length or segment_index == len(segments) - 1:
                jitter = rng.uniform(-JITTER_SECONDS, JITTER_SECONDS)
                moment = low + timedelta(seconds=min(max(offset + jitter, 0.0), length))
                times.append(moment.replace(microsecond=0))
                break
            offset -= length

    times.sort()
    # 去重：同一秒两条会让"按 time 排序"产生歧义，这里强制间隔 1 秒。
    for index in range(1, len(times)):
        if times[index] <= times[index - 1]:
            times[index] = times[index - 1] + timedelta(seconds=1)
    for index in range(1, len(times)):
        if times[index] > end:
            times[index] = end
    return times


def _status_sequence(rng: random.Random) -> list[str]:
    """构造状态序列：大部分成功，少量降级，个别失败，再打散顺序。"""

    statuses = (
        ["success"] * SUCCESS_CALLS
        + ["degraded"] * DEGRADED_CALLS
        + ["failed"] * FAILED_CALLS
    )
    rng.shuffle(statuses)
    return statuses


def _capability_sequence(
    capabilities: dict[str, Capability], total: int, rng: random.Random
) -> list[Capability]:
    """构造能力序列：chat-completions 约占七成，long-summary 约占三成。"""

    chat = capabilities["chat-completions"]
    summary = capabilities["long-summary"]
    summary_count = max(1, round(total * 0.3))
    sequence = [chat] * (total - summary_count) + [summary] * summary_count
    rng.shuffle(sequence)
    return sequence


def _token_profile(
    capability: Capability, status: str, rng: random.Random
) -> tuple[int, int, str]:
    """按能力与状态给出 (prompt_tokens, completion_tokens, token_source)。

    与线上一致：降级拿不到上游 usage（missing，token 记 0）；失败连调用都没跑完
    （unknown，token 记 0）；成功则用上游 usage（upstream）的量级。
    """

    if status == "degraded":
        return 0, 0, "missing"
    if status == "failed":
        return 0, 0, "unknown"

    if capability.code == "long-summary":
        return rng.randint(1_600, 3_400), rng.randint(140, 420), "upstream"
    return rng.randint(320, 1_400), rng.randint(90, 620), "upstream"


def _duration_profile(status: str, rng: random.Random) -> int:
    """耗时量级：成功 6~16 秒，降级基本卡在 30 秒超时，失败在 1~4 秒内就被拒。"""

    if status == "degraded":
        return rng.randint(30_000, 30_012)
    if status == "failed":
        return rng.randint(1_100, 3_600)
    return rng.randint(6_800, 16_000)


def build_plan(conn: Connection, user_id: int, now: datetime) -> SeedPlan:
    """把整批数据先算出来（不写库），方便 --dry-run 精确预览。"""

    baseline = read_baseline(conn, user_id)
    capabilities = read_capabilities(conn)
    rng = random.Random(RANDOM_SEED)

    # 窗口下界：既有账本尾部之后 1 分钟；同时不超过 6 天前，避免把数据摊到月份以外。
    ledger_tail = baseline.ledger_tail or (now - timedelta(days=1))
    window_start = max(ledger_tail + timedelta(minutes=1), now - timedelta(days=6))
    window_end = now - timedelta(minutes=2)
    if window_end <= window_start:
        raise SystemExit(
            "既有流水的最后一条就在刚刚，暂时没有可用的记账窗口；"
            "请等待几分钟后重试，或先用 --clean 清掉旧数据"
        )

    times = _spread_times(window_start, window_end, TOTAL_CALLS, rng)
    statuses = _status_sequence(rng)
    capability_sequence = _capability_sequence(capabilities, TOTAL_CALLS, rng)

    calls: list[CallPlan] = []
    for index, (moment, status, capability) in enumerate(
        zip(times, statuses, capability_sequence), start=1
    ):
        prompt_tokens, completion_tokens, token_source = _token_profile(
            capability, status, rng
        )
        units = 1
        cost = capability.cost(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            units=units,
            billable=status == "success",
        )
        calls.append(
            CallPlan(
                request_id=f"{REQUEST_PREFIX}C{index:02d}",
                capability=capability,
                create_time=moment,
                call_status=status,
                cost=cost,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                token_source=token_source,
                units=units,
                duration_ms=_duration_profile(status, rng),
                model_name="deepseek-flash",
            )
        )

    calls.sort(key=lambda item: item.create_time)

    # 充值时间也落在白天时段：第一笔在窗口开头，第二笔在最后一天早上，
    # 语义是"先充值、随后消耗"，避免出现凌晨充值的假数据。
    segments = _business_segments(window_start, window_end)
    first_segment = segments[0] if segments else (window_start, window_end)
    last_segment = segments[-1] if segments else (window_start, window_end)
    recharge_times = (
        _clamp_moment(first_segment[0] + timedelta(minutes=2), *first_segment),
        _clamp_moment(last_segment[0] + timedelta(minutes=20), *last_segment),
    )
    if recharge_times[0] == recharge_times[1]:
        recharge_times = (
            recharge_times[0],
            _clamp_moment(first_segment[0] + timedelta(minutes=4), *first_segment),
        )
    recharges = [
        PointsLogPlan(
            request_id=f"{REQUEST_PREFIX}R{index + 1:02d}",
            direction="in",
            amount=amount,
            balance_after=0,  # 下面按时间顺序统一重算
            biz_type="recharge",
            remark=f"积分充值（演示数据）｜订单 DP{moment:%Y%m%d}{index + 1:02d}",
            create_time=moment.replace(microsecond=0),
        )
        for index, (amount, moment) in enumerate(
            zip(RECHARGE_AMOUNTS, recharge_times)
        )
    ]

    call_logs = [
        PointsLogPlan(
            request_id=call.request_id,
            direction="out",
            amount=call.cost,
            balance_after=0,
            biz_type="call",
            remark=f"{call.capability.code} price={call.cost}",
            create_time=call.create_time,
        )
        for call in calls
        if call.billable
    ]

    ordered = sorted(
        recharges + call_logs, key=lambda item: (item.create_time, item.request_id)
    )

    # 逐条累加：这样 balance_after 天然与"插入顺序 + 金额"自洽，末条即账户余额。
    ledger: list[PointsLogPlan] = []
    running = baseline.pristine_balance
    for entry in ordered:
        running += entry.amount if entry.direction == "in" else -entry.amount
        if running < 0:
            raise SystemExit(
                f"计划会让余额变成负数（request_id={entry.request_id}），"
                "请减少调用条数或提高充值金额"
            )
        ledger.append(
            PointsLogPlan(
                request_id=entry.request_id,
                direction=entry.direction,
                amount=entry.amount,
                balance_after=running,
                biz_type=entry.biz_type,
                remark=entry.remark,
                create_time=entry.create_time,
            )
        )

    final_balance = running
    if not BALANCE_MIN <= final_balance <= BALANCE_MAX:
        raise SystemExit(
            f"计划余额 {final_balance} 不在 {BALANCE_MIN}~{BALANCE_MAX} 区间，"
            "请调整 RECHARGE_AMOUNTS"
        )

    # 用量按天/按能力聚合，全部由调用明细派生（同一份数据，两个口径不会打架）。
    usage: dict[tuple[date, int], list[int]] = {}
    for call in calls:
        key = (call.create_time.date(), call.capability.id)
        bucket = usage.setdefault(key, [0, 0])
        bucket[0] += 1
        bucket[1] += call.cost

    usage_deltas = tuple(
        (stat_date, capability_id, counts[0], counts[1])
        for (stat_date, capability_id), counts in sorted(usage.items())
    )

    return SeedPlan(
        baseline=baseline,
        calls=tuple(calls),
        points_logs=tuple(ledger),
        usage_deltas=usage_deltas,
        chat_sessions=build_chat_sessions(now),
    )


def build_chat_sessions(now: datetime) -> tuple[ChatSessionPlan, ...]:
    """构造 3 个中文会话：1 个全成功、1 个含降级、1 个含硬失败（带 error_code）。"""

    def moment(day_offset: int, hour: int, minute: int, second: int = 0) -> datetime:
        day = (now - timedelta(days=day_offset)).date()
        return datetime.combine(day, clock_time(hour, minute, second))

    session_success = ChatSessionPlan(
        title=CHAT_TITLES[0],
        create_time=moment(1, 15, 20),
        last_message_time=moment(1, 15, 23),
        messages=(
            ChatMessagePlan(
                role="user",
                content="帮我对比按次计费和按 token 计费，内部培训要用，尽量讲人话。",
                call_status="success",
                token_count=0,  # 与线上一致：用户消息不猜 token，等上游 usage
                error_code=None,
                create_time=moment(1, 15, 20),
            ),
            ChatMessagePlan(
                role="assistant",
                content=(
                    "按次计费只认“调用了一次”，跟这次调用多大无关：多轮对话固定 5 积分，"
                    "长文本摘要固定 3 积分，账最好核，缺点是长文调用对平台不划算。"
                    "按 token 计费按实际用量结算，公式是 "
                    "ceil((输入 tokens×每千输入价 + 输出 tokens×每千输出价)/1000)，"
                    "基准 1000 tokens = 1 积分，短请求省钱、长请求更公平。"
                ),
                call_status="success",
                token_count=386,
                error_code=None,
                create_time=moment(1, 15, 21),
            ),
            ChatMessagePlan(
                role="user",
                content="那上游不返回 usage 的时候平台怎么处理？",
                call_status="success",
                token_count=0,
                error_code=None,
                create_time=moment(1, 15, 21, 40),
            ),
            ChatMessagePlan(
                role="assistant",
                content=(
                    "按 token 计费的能力会失败关闭：直接拒绝结算并返回 5002，"
                    "不会用字符数估算糊弄过去；Mock 模式估算出来的 token 同样不算真值。"
                    "按次计费不受影响，照常扣一次单价。"
                ),
                call_status="success",
                token_count=152,
                error_code=None,
                create_time=moment(1, 15, 23),
            ),
        ),
    )

    session_degraded = ChatSessionPlan(
        title=CHAT_TITLES[1],
        create_time=moment(2, 10, 5, 12),
        last_message_time=moment(2, 10, 9, 20),
        messages=(
            ChatMessagePlan(
                role="user",
                content="总结这次灰度发布暴露的问题，挑最重要的三个，每个给一条改进建议。",
                call_status="success",
                token_count=0,
                error_code=None,
                create_time=moment(2, 10, 5, 12),
            ),
            ChatMessagePlan(
                role="assistant",
                content=(
                    "三个问题：一、灰度期间旧版调用仍按 capability_id=0 上报，"
                    "按能力统计出现缺口；二、摘要能力超时后的降级回复没有提示用户这是兜底内容；"
                    "三、积分流水与调用明细在并发下出现约 30 秒时间差，对账脚本会误报。"
                    "建议分别对应：统一上报能力 ID、前端显式标注降级、对账改按 requestId 关联。"
                ),
                call_status="success",
                token_count=298,
                error_code=None,
                create_time=moment(2, 10, 5, 41),
            ),
            ChatMessagePlan(
                role="user",
                content="第二条再展开一点，前端怎么标注比较合适？",
                call_status="success",
                token_count=0,
                error_code=None,
                create_time=moment(2, 10, 7, 3),
            ),
            ChatMessagePlan(
                role="assistant",
                content=DEGRADED_REPLY,
                call_status="degraded",
                token_count=0,
                error_code=ERROR_CODE_TIMEOUT,
                create_time=moment(2, 10, 7, 33),
            ),
            ChatMessagePlan(
                role="user",
                content="先按这个思路整理，明天我再补充细节。",
                call_status="success",
                token_count=0,
                error_code=None,
                create_time=moment(2, 10, 9, 20),
            ),
        ),
    )

    session_failed = ChatSessionPlan(
        title=CHAT_TITLES[2],
        create_time=moment(0, 9, 12, 40),
        last_message_time=moment(0, 9, 21, 6),
        messages=(
            ChatMessagePlan(
                role="user",
                content="我们自建的模型网关接进来之后一直返回 502，排查应该按什么顺序走？",
                call_status="success",
                token_count=0,
                error_code=None,
                create_time=moment(0, 9, 12, 40),
            ),
            ChatMessagePlan(
                role="assistant",
                content=(
                    "先分层排查：一、网关到供应商的连通性，https、证书、30 秒超时是否偏短；"
                    "二、供应商侧模型名是否与 default_model 一致，502 常见于上游路由不到模型；"
                    "三、用 requestId 串起调用记录与执行收据，确认是执行失败还是计费失败；"
                    "四、最后确认降级是否生效，超时与响应格式异常都会被折算成降级而不是报错。"
                ),
                call_status="success",
                token_count=271,
                error_code=None,
                create_time=moment(0, 9, 13, 8),
            ),
            ChatMessagePlan(
                role="user",
                content="好，我按这个顺序试一下。",
                call_status="success",
                token_count=0,
                error_code=None,
                create_time=moment(0, 9, 20, 2),
            ),
            ChatMessagePlan(
                role="assistant",
                content=FAILED_REPLY,
                call_status="failed",
                token_count=0,
                error_code=ERROR_CODE_UPSTREAM_FAULT,
                create_time=moment(0, 9, 21, 6),
            ),
        ),
    )

    return (session_success, session_degraded, session_failed)


# ---------------------------------------------------------------- 写库


INSERT_POINTS_LOG = text(
    "INSERT INTO user_db.t_points_log "
    "  (user_id, direction, amount, balance_after, biz_type, request_id, remark, "
    "   create_time, update_time, is_deleted) "
    "VALUES (:user_id, :direction, :amount, :balance_after, :biz_type, :request_id, "
    "        :remark, :create_time, :create_time, 0)"
)

INSERT_CALL_RECORD = text(
    "INSERT INTO billing_db.t_call_record "
    "  (request_id, user_id, capability_id, service_name, unit_price, cost, billing_mode, "
    "   prompt_tokens, completion_tokens, token_source, units, call_status, duration_ms, "
    "   model_name, create_time, update_time, is_deleted) "
    "VALUES (:request_id, :user_id, :capability_id, :service_name, :unit_price, :cost, "
    "        :billing_mode, :prompt_tokens, :completion_tokens, :token_source, :units, "
    "        :call_status, :duration_ms, :model_name, :create_time, :create_time, 0)"
)

# 与 usage_repository.upsert_daily 同构：原子累加，绝不做"读-改-写"。
UPSERT_USAGE_DAILY = text(
    "INSERT INTO billing_db.t_usage_daily "
    "  (stat_date, user_id, capability_id, call_count, total_cost, create_time, update_time, is_deleted) "
    "VALUES (:stat_date, :user_id, :capability_id, :call_count, :total_cost, :now, :now, 0) AS incoming "
    "ON DUPLICATE KEY UPDATE "
    "  call_count = t_usage_daily.call_count + incoming.call_count, "
    "  total_cost = t_usage_daily.total_cost + incoming.total_cost, "
    "  update_time = incoming.update_time"
)

INSERT_CHAT_SESSION = text(
    "INSERT INTO ai_chat_db.t_chat_session "
    "  (user_id, title, last_message_time, create_time, update_time, is_deleted) "
    "VALUES (:user_id, :title, :last_message_time, :create_time, :create_time, 0)"
)

INSERT_CHAT_MESSAGE = text(
    "INSERT INTO ai_chat_db.t_chat_message "
    "  (session_id, user_id, role, content, call_status, token_count, error_code, "
    "   create_time, update_time, is_deleted) "
    "VALUES (:session_id, :user_id, :role, :content, :call_status, :token_count, "
    "        :error_code, :create_time, :create_time, 0)"
)

UPDATE_ACCOUNT = text(
    "UPDATE user_db.t_points_account "
    "SET balance = :balance, version = :version, update_time = NOW() "
    "WHERE user_id = :user_id AND is_deleted = 0"
)


def apply_plan(conn: Connection, plan: SeedPlan, user_id: int) -> list[int]:
    """把计划写进四个库；调用方负责事务边界。返回新建的会话 ID。"""

    for log in plan.points_logs:
        conn.execute(
            INSERT_POINTS_LOG,
            {
                "user_id": user_id,
                "direction": log.direction,
                "amount": log.amount,
                "balance_after": log.balance_after,
                "biz_type": log.biz_type,
                "request_id": log.request_id,
                "remark": log.remark,
                "create_time": log.create_time,
            },
        )

    for call in plan.calls:
        conn.execute(
            INSERT_CALL_RECORD,
            {
                "request_id": call.request_id,
                "user_id": user_id,
                "capability_id": call.capability.id,
                "service_name": call.service_name,
                "unit_price": call.capability.registered_unit_price,
                "cost": call.cost,
                "billing_mode": call.capability.billing_mode,
                "prompt_tokens": call.prompt_tokens,
                "completion_tokens": call.completion_tokens,
                "token_source": call.token_source,
                "units": call.units,
                "call_status": call.call_status,
                "duration_ms": call.duration_ms,
                "model_name": call.model_name,
                "create_time": call.create_time,
            },
        )

    now = datetime.now().replace(microsecond=0)
    for stat_date, capability_id, call_count, total_cost in plan.usage_deltas:
        conn.execute(
            UPSERT_USAGE_DAILY,
            {
                "stat_date": stat_date,
                "user_id": user_id,
                "capability_id": capability_id,
                "call_count": call_count,
                "total_cost": total_cost,
                "now": now,
            },
        )

    session_ids: list[int] = []
    for session in plan.chat_sessions:
        result = conn.execute(
            INSERT_CHAT_SESSION,
            {
                "user_id": str(user_id),
                "title": session.title,
                "last_message_time": session.last_message_time,
                "create_time": session.create_time,
            },
        )
        session_id = int(result.lastrowid or 0)
        if session_id <= 0:
            raise SystemExit("写入会话失败：没有拿到自增主键")
        session_ids.append(session_id)
        for message in session.messages:
            conn.execute(
                INSERT_CHAT_MESSAGE,
                {
                    "session_id": session_id,
                    "user_id": str(user_id),
                    "role": message.role,
                    "content": message.content,
                    "call_status": message.call_status,
                    "token_count": message.token_count,
                    "error_code": message.error_code,
                    "create_time": message.create_time,
                },
            )

    conn.execute(
        UPDATE_ACCOUNT,
        {
            "balance": plan.final_balance,
            "version": plan.baseline.pristine_version + len(plan.points_logs),
            "user_id": user_id,
        },
    )
    return session_ids


# ---------------------------------------------------------------- 清理


def read_state() -> dict[str, Any]:
    """读取状态文件；损坏或缺失都当成空状态处理，不阻断流程。"""

    if not STATE_PATH.exists():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def collect_chat_session_ids(
    conn: Connection, user_id: int, state: dict[str, Any]
) -> list[int]:
    """定位本脚本写过的会话：状态文件为主，固定标题兜底。"""

    session_ids: set[int] = set()
    for value in state.get("chat_session_ids", []) or []:
        try:
            session_ids.add(int(value))
        except (TypeError, ValueError):
            continue

    rows = conn.execute(
        text(
            "SELECT id, title FROM ai_chat_db.t_chat_session "
            "WHERE user_id = :u AND is_deleted = 0"
        ),
        {"u": str(user_id)},
    ).all()
    for session_id, title in rows:
        if str(title) in CHAT_TITLES:
            session_ids.add(_as_int(session_id))
    return sorted(session_ids)


def clean(conn: Connection, user_id: int, *, dry_run: bool) -> dict[str, int]:
    """删除本脚本写入的全部行，并把余额/version/用量聚合回退到执行前。"""

    state = read_state()

    marked_logs = conn.execute(
        text(
            "SELECT direction, amount FROM user_db.t_points_log "
            "WHERE user_id = :u AND request_id LIKE :prefix"
        ),
        {"u": user_id, "prefix": f"{REQUEST_PREFIX}%"},
    ).all()
    net = 0
    for direction, amount in marked_logs:
        net += _as_int(amount) if direction == "in" else -_as_int(amount)
    log_count = len(marked_logs)

    marked_calls = conn.execute(
        text(
            "SELECT DATE(create_time) AS stat_date, capability_id, "
            "       COUNT(*) AS call_count, COALESCE(SUM(cost), 0) AS total_cost "
            "FROM billing_db.t_call_record "
            "WHERE user_id = :u AND request_id LIKE :prefix AND is_deleted = 0 "
            "GROUP BY stat_date, capability_id"
        ),
        {"u": user_id, "prefix": f"{REQUEST_PREFIX}%"},
    ).all()
    call_count = sum(_as_int(row[2]) for row in marked_calls)

    session_ids = collect_chat_session_ids(conn, user_id, state)
    message_count = 0
    if session_ids:
        message_count = int(
            _scalar(
                conn,
                "SELECT COUNT(*) FROM ai_chat_db.t_chat_message "
                "WHERE user_id = :u AND session_id IN :ids",
                {"u": str(user_id), "ids": session_ids},
            )
            or 0
        )

    report = {
        "points_log": log_count,
        "call_record": call_count,
        "usage_daily": len(marked_calls),
        "chat_session": len(session_ids),
        "chat_message": message_count,
        "points_net": net,
    }
    if dry_run:
        return report

    # 1) 会话消息 -> 会话（先子后父，避免悬挂消息）
    if session_ids:
        statement = text(
            "DELETE FROM ai_chat_db.t_chat_message "
            "WHERE user_id = :u AND session_id IN :ids"
        ).bindparams(bindparam("ids", expanding=True))
        conn.execute(statement, {"u": str(user_id), "ids": session_ids})

        statement = text(
            "DELETE FROM ai_chat_db.t_chat_session WHERE user_id = :u AND id IN :ids"
        ).bindparams(bindparam("ids", expanding=True))
        conn.execute(statement, {"u": str(user_id), "ids": session_ids})

    # 2) 调用明细
    conn.execute(
        text("DELETE FROM billing_db.t_call_record WHERE user_id = :u AND request_id LIKE :prefix"),
        {"u": user_id, "prefix": f"{REQUEST_PREFIX}%"},
    )

    # 3) 积分流水
    conn.execute(
        text("DELETE FROM user_db.t_points_log WHERE user_id = :u AND request_id LIKE :prefix"),
        {"u": user_id, "prefix": f"{REQUEST_PREFIX}%"},
    )

    # 4) 日用量：按当初加的量减回去（表只累加不软删，所以用等量减）
    for stat_date, capability_id, row_call_count, row_total_cost in marked_calls:
        params = {
            "stat_date": stat_date,
            "capability_id": _as_int(capability_id),
            "call_count": _as_int(row_call_count),
            "total_cost": _as_int(row_total_cost),
            "u": user_id,
        }
        conn.execute(
            text(
                "UPDATE billing_db.t_usage_daily "
                "SET call_count = call_count - :call_count, "
                "    total_cost = total_cost - :total_cost, "
                "    update_time = NOW() "
                "WHERE stat_date = :stat_date AND user_id = :u AND capability_id = :capability_id"
            ),
            params,
        )
        # 完全由本次播种创建出来的聚合行，减到 0 后直接删掉，不留空壳。
        conn.execute(
            text(
                "DELETE FROM billing_db.t_usage_daily "
                "WHERE stat_date = :stat_date AND user_id = :u AND capability_id = :capability_id "
                "  AND call_count <= 0 AND total_cost <= 0"
            ),
            params,
        )

    # 5) 余额与 version 回退到执行前
    if log_count:
        conn.execute(
            text(
                "UPDATE user_db.t_points_account "
                "SET balance = balance - :net, version = GREATEST(version - :steps, 0), "
                "    update_time = NOW() "
                "WHERE user_id = :u AND is_deleted = 0"
            ),
            {"net": net, "steps": log_count, "u": user_id},
        )

    if STATE_PATH.exists():
        STATE_PATH.unlink()
    return report


def write_state(user_id: int, session_ids: Sequence[int], plan: SeedPlan) -> None:
    """记录本次写入的会话 ID，作为对话表清理的权威标记。"""

    payload = {
        "user_id": user_id,
        "username": DEMO_USERNAME,
        "created_at": datetime.now().replace(microsecond=0).isoformat(sep=" "),
        "request_id_prefix": REQUEST_PREFIX,
        "chat_session_ids": list(session_ids),
        "chat_titles": list(CHAT_TITLES),
        "points_log_rows": len(plan.points_logs),
        "call_record_rows": len(plan.calls),
        "points_net": plan.net_points,
        "balance_after": plan.final_balance,
    }
    STATE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------- 自检


def verify(conn: Connection, user_id: int) -> bool:
    """写完之后的一致性自检，全部通过才算交付。"""

    checks: list[tuple[str, bool, str]] = []

    account = conn.execute(
        text(
            "SELECT balance, version FROM user_db.t_points_account "
            "WHERE user_id = :u AND is_deleted = 0"
        ),
        {"u": user_id},
    ).one_or_none()
    if account is None:
        print("自检失败：找不到积分账户")
        return False
    balance = int(account[0])

    # 1) 按 id（= 插入顺序 = 前端展示顺序）逐条累加，必须与 balance_after 完全吻合
    rows = conn.execute(
        text(
            "SELECT id, direction, amount, balance_after, request_id, create_time "
            "FROM user_db.t_points_log WHERE user_id = :u AND is_deleted = 0 ORDER BY id"
        ),
        {"u": user_id},
    ).all()
    running = 0
    broken_by_id: list[str] = []
    for row_id, direction, amount, balance_after, request_id, _ in rows:
        running += _as_int(amount) if direction == "in" else -_as_int(amount)
        if running != _as_int(balance_after):
            broken_by_id.append(f"id={row_id} request_id={request_id}")
    checks.append(
        (
            "流水链（按 id 累加）",
            not broken_by_id,
            "全部吻合" if not broken_by_id else f"断裂 {len(broken_by_id)} 处：{broken_by_id[:3]}",
        )
    )
    checks.append(
        (
            "末条 balance_after == 账户余额",
            bool(rows) and int(rows[-1][3]) == balance,
            f"末条={rows[-1][3] if rows else 'N/A'}，账户={balance}",
        )
    )

    # 2) 按 create_time 排序的链；断裂按"是不是本脚本写的行"归类：
    #    本脚本的行断裂 = FAIL；既有数据断裂 = 仅提示（红线：不改既有行）。
    by_time = conn.execute(
        text(
            "SELECT id, direction, amount, balance_after, request_id, create_time "
            "FROM user_db.t_points_log WHERE user_id = :u AND is_deleted = 0 "
            "ORDER BY create_time, id"
        ),
        {"u": user_id},
    ).all()
    running = 0
    own_breaks: list[str] = []
    legacy_breaks: list[str] = []
    for row_id, direction, amount, balance_after, request_id, moment in by_time:
        running += _as_int(amount) if direction == "in" else -_as_int(amount)
        if running != _as_int(balance_after):
            label = f"id={row_id}({moment}, request_id={request_id})"
            if str(request_id).startswith(REQUEST_PREFIX):
                own_breaks.append(label)
            else:
                legacy_breaks.append(label)
    checks.append(
        (
            "流水链（按 create_time 排序，本脚本写入行）",
            not own_breaks,
            "全部吻合" if not own_breaks else f"断裂 {len(own_breaks)} 处：{own_breaks[:3]}",
        )
    )
    checks.append(
        (
            "流水链（按 create_time 排序，既有无标记行）",
            True,
            "全部吻合"
            if not legacy_breaks
            else (
                f"既有数据有 {len(legacy_breaks)} 处时间倒挂（本次未修改）：{legacy_breaks[:3]}；"
                "按 id（=展示顺序）是吻合的，见上一项"
            ),
        )
    )

    # 3) 日用量必须等于调用明细的自然聚合（两个页面口径一致）
    mismatch = conn.execute(
        text(
            "SELECT u.stat_date, u.capability_id, u.call_count, u.total_cost, "
            "       COALESCE(c.cnt, 0), COALESCE(c.cost, 0) "
            "FROM billing_db.t_usage_daily u "
            "LEFT JOIN ( "
            "  SELECT DATE(create_time) AS d, capability_id, COUNT(*) AS cnt, "
            "         COALESCE(SUM(cost), 0) AS cost "
            "  FROM billing_db.t_call_record WHERE user_id = :u AND is_deleted = 0 "
            "  GROUP BY d, capability_id "
            ") c ON c.d = u.stat_date AND c.capability_id = u.capability_id "
            "WHERE u.user_id = :u AND u.is_deleted = 0 "
            "  AND (u.call_count <> COALESCE(c.cnt, 0) OR u.total_cost <> COALESCE(c.cost, 0))"
        ),
        {"u": user_id},
    ).all()
    checks.append(
        (
            "usage_daily == call_record 聚合",
            not mismatch,
            "完全一致" if not mismatch else f"{len(mismatch)} 行不一致：{mismatch[:3]}",
        )
    )

    # 4) 每条计费调用都要有同 requestId 的扣费流水（禁止"记账了没扣分"）
    orphans = conn.execute(
        text(
            "SELECT c.request_id, c.cost FROM billing_db.t_call_record c "
            "LEFT JOIN user_db.t_points_log p "
            "  ON p.request_id = c.request_id AND p.is_deleted = 0 "
            "WHERE c.user_id = :u AND c.is_deleted = 0 AND c.cost > 0 AND p.id IS NULL"
        ),
        {"u": user_id},
    ).all()
    checks.append(
        (
            "计费调用都有对应扣费流水",
            not orphans,
            "全部匹配" if not orphans else f"缺失 {len(orphans)} 条：{orphans[:3]}",
        )
    )

    # 5) 扣费流水金额 == 调用 cost
    amount_mismatch = conn.execute(
        text(
            "SELECT c.request_id, c.cost, p.amount "
            "FROM billing_db.t_call_record c "
            "JOIN user_db.t_points_log p "
            "  ON p.request_id = c.request_id AND p.is_deleted = 0 "
            "WHERE c.user_id = :u AND c.is_deleted = 0 AND p.amount <> c.cost"
        ),
        {"u": user_id},
    ).all()
    checks.append(
        (
            "扣费流水金额 == 调用 cost",
            not amount_mismatch,
            "全部一致" if not amount_mismatch else f"{len(amount_mismatch)} 条不一致",
        )
    )

    # 6) cost 与目录价一致（per_call 重新复算；降级/失败必须为 0）
    price_rows = conn.execute(
        text(
            "SELECT c.call_status, c.billing_mode, c.cost, "
            "       cap.price_per_call, cap.price_per_1k_input, cap.price_per_1k_output, "
            "       cap.price_per_unit, c.prompt_tokens, c.completion_tokens, c.units, "
            "       c.unit_price, c.request_id "
            "FROM billing_db.t_call_record c "
            "LEFT JOIN capability_db.t_capability cap "
            "  ON cap.id = c.capability_id AND cap.is_deleted = 0 "
            "WHERE c.user_id = :u AND c.is_deleted = 0"
        ),
        {"u": user_id},
    ).all()
    price_errors: list[str] = []
    for row in price_rows:
        (
            status,
            mode,
            cost,
            price_per_call,
            price_in,
            price_out,
            price_unit,
            prompt_tokens,
            completion_tokens,
            units,
            unit_price,
            request_id,
        ) = row
        billable = status == "success"
        prompt_count = _as_int(prompt_tokens)
        completion_count = _as_int(completion_tokens)
        registered_price = _as_int(unit_price)
        if not billable:
            expected = 0
        elif mode == "per_token":
            weighted = prompt_count * _as_int(price_in) + completion_count * _as_int(
                price_out
            )
            expected = 0 if weighted <= 0 else -(-weighted // 1000)
        elif mode == "per_unit":
            expected = _as_int(price_unit) * max(_as_int(units) or 1, 1)
        else:
            expected = _as_int(price_per_call)
        if _as_int(cost) != expected:
            price_errors.append(f"{request_id}: cost={cost} 期望={expected}")
        expected_unit_price = _as_int(price_per_call) if mode == "per_call" else None
        if mode == "per_call" and registered_price != expected_unit_price:
            price_errors.append(
                f"{request_id}: unit_price={unit_price} 期望={expected_unit_price}"
            )
    checks.append(
        (
            "cost / unit_price 与目录价一致",
            not price_errors,
            "全部一致" if not price_errors else f"{len(price_errors)} 条异常：{price_errors[:3]}",
        )
    )

    # 7) 只能写自己的数据：标记行必须都属于 user_id
    foreign = conn.execute(
        text(
            "SELECT COUNT(*) FROM user_db.t_points_log "
            "WHERE request_id LIKE :prefix AND user_id <> :u"
        ),
        {"u": user_id, "prefix": f"{REQUEST_PREFIX}%"},
    ).scalar()
    foreign_calls = conn.execute(
        text(
            "SELECT COUNT(*) FROM billing_db.t_call_record "
            "WHERE request_id LIKE :prefix AND user_id <> :u"
        ),
        {"u": user_id, "prefix": f"{REQUEST_PREFIX}%"},
    ).scalar()
    checks.append(
        (
            "标记行只属于 user_id",
            int(foreign or 0) == 0 and int(foreign_calls or 0) == 0,
            f"越界流水 {foreign} 条、越界调用 {foreign_calls} 条",
        )
    )

    # 8) 时间穿越检查：不允许出现未来时间
    future = conn.execute(
        text(
            "SELECT COUNT(*) FROM billing_db.t_call_record "
            "WHERE user_id = :u AND request_id LIKE :prefix AND create_time > NOW()"
        ),
        {"u": user_id, "prefix": f"{REQUEST_PREFIX}%"},
    ).scalar()
    checks.append(
        ("无未来时间", int(future or 0) == 0, f"未来时间 {future} 条")
    )

    print("\n一致性自检")
    print("-" * 72)
    passed = True
    for name, ok, detail in checks:
        print(f"  [{'OK  ' if ok else 'FAIL'}] {name}：{detail}")
        passed = passed and ok
    print("-" * 72)
    print(f"  结论：{'全部通过' if passed else '存在未通过项，请检查上面的 FAIL 行'}")
    return passed


# ---------------------------------------------------------------- 输出


def format_counts(counts: dict[str, int]) -> str:
    return "，".join(f"{name} {value}" for name, value in counts.items())


def print_plan(plan: SeedPlan, user_id: int) -> None:
    """把计划完整打印出来，--dry-run 时全靠这段自证。"""

    by_status: dict[str, int] = {}
    by_capability: dict[str, int] = {}
    cost_total = 0
    for call in plan.calls:
        by_status[call.call_status] = by_status.get(call.call_status, 0) + 1
        code = call.capability.code
        by_capability[code] = by_capability.get(code, 0) + 1
        cost_total += call.cost

    print("\n写入计划")
    print("-" * 72)
    residual = (
        f"（当前 {plan.baseline.balance}，其中 {plan.baseline.marked_net:+d} "
        f"/ {plan.baseline.marked_count} 条是上次播种残留，会先被清掉）"
        if plan.baseline.marked_count
        else f"（当前 {plan.baseline.balance}，没有上次播种残留）"
    )
    print(
        f"  账号            {DEMO_USERNAME}（user_id={user_id}）\n"
        f"  基线余额        {plan.baseline.pristine_balance}{residual}\n"
        f"  新写入后余额    {plan.final_balance}"
        f"（{BALANCE_MIN}~{BALANCE_MAX} 区间内）"
    )
    print(
        f"  积分流水        {len(plan.points_logs)} 条"
        f"（充值 {sum(1 for log in plan.points_logs if log.biz_type == 'recharge')} 条，"
        f"调用扣费 {sum(1 for log in plan.points_logs if log.biz_type == 'call')} 条），"
        f"净额 {plan.net_points:+d}"
    )
    print(
        f"  调用明细        {len(plan.calls)} 条"
        f"（{'，'.join(f'{k} {v}' for k, v in sorted(by_status.items()))}；"
        f"{'，'.join(f'{k} {v}' for k, v in sorted(by_capability.items()))}），"
        f"合计消耗 {cost_total} 积分"
    )
    print(
        f"  日用量聚合      {len(plan.usage_deltas)} 个 (日期, 能力) 组合，"
        "全部由调用明细派生"
    )
    print(
        f"  对话            {len(plan.chat_sessions)} 个会话、{plan.total_messages} 条消息"
        "（1 条降级、1 条失败带 error_code）"
    )
    if plan.calls:
        print(
            f"  时间范围        {plan.calls[0].create_time} → {plan.calls[-1].create_time}")
    print(
        f"  余额链校验      首条 balance_after="
        f"{plan.points_logs[0].balance_after if plan.points_logs else 'N/A'}，"
        f"末条={plan.points_logs[-1].balance_after if plan.points_logs else 'N/A'}"
    )
    print("-" * 72)


def print_ledger_tail(plan: SeedPlan, limit: int = 6) -> None:
    """打印最后几条流水，方便一眼确认金额链。"""

    print("\n流水尾部（按时间顺序，balance_after 应逐条对上）")
    print("-" * 72)
    for log in plan.points_logs[-limit:]:
        sign = "+" if log.direction == "in" else "-"
        print(
            f"  {log.create_time}  {sign}{log.amount:<6} → {log.balance_after:<8} "
            f"{log.biz_type:<9} {log.request_id}  {log.remark}"
        )
    print("-" * 72)


# ---------------------------------------------------------------- 入口


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="给 opsdemo 播种演示数据（幂等 / 可一键清理）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python scripts/devtools/seed_demo_data.py --dry-run\n"
            "  python scripts/devtools/seed_demo_data.py\n"
            "  python scripts/devtools/seed_demo_data.py --verify\n"
            "  python scripts/devtools/seed_demo_data.py --clean\n"
        ),
    )
    parser.add_argument("--clean", action="store_true", help="删除本脚本写入的全部行并还原余额")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划与行数，不写库")
    parser.add_argument("--verify", action="store_true", help="写入后执行一致性自检")
    parser.add_argument(
        "--user-id", type=int, default=DEMO_USER_ID, help=f"目标用户 ID（默认 {DEMO_USER_ID}）"
    )
    args = parser.parse_args(argv)

    user_id = int(args.user_id)
    engine, password_source = resolve_engine()
    print(f"数据库连接：127.0.0.1:3307（密码来源：{password_source}）")

    with engine.connect() as conn:
        username, role, status = read_user(conn, user_id)
        if username != DEMO_USERNAME:
            print(
                f"提示：user_id={user_id} 的账号是 {username}，不是预期的 {DEMO_USERNAME}",
                flush=True,
            )
        print(f"目标账号：{username}（user_id={user_id}，role={role}，status={status}）")
        before = table_counts(conn)
        before_user = user_row_counts(conn, user_id)

    print(f"\n执行前（全表）：{format_counts(before)}")
    print(f"执行前（{username} 自己的行数）：{format_counts(before_user)}")

    if args.clean:
        with engine.begin() as conn:
            report = clean(conn, user_id, dry_run=args.dry_run)
        verb = "将删除" if args.dry_run else "已删除"
        print(
            f"\n{verb}：积分流水 {report['points_log']} 条、调用明细 {report['call_record']} 条、"
            f"日用量聚合 {report['usage_daily']} 个组合、会话 {report['chat_session']} 个、"
            f"消息 {report['chat_message']} 条；余额回退 {report['points_net']:+d}"
        )
        if args.dry_run:
            print("dry-run：未写库")
            return 0
        with engine.connect() as conn:
            after = table_counts(conn)
            after_user = user_row_counts(conn, user_id)
            balance = _scalar(
                conn,
                "SELECT balance FROM user_db.t_points_account WHERE user_id = :u",
                {"u": user_id},
            )
        print(f"执行后（全表）：{format_counts(after)}")
        print(f"执行后（{username} 自己的行数）：{format_counts(after_user)}")
        print(f"执行后余额：{balance}")
        return 0

    now = datetime.now().replace(microsecond=0)
    with engine.connect() as conn:
        plan = build_plan(conn, user_id, now)

    print_plan(plan, user_id)
    print_ledger_tail(plan)

    if args.dry_run:
        print("\ndry-run：以上为计划，未写库。去掉 --dry-run 即真正写入。")
        return 0

    with engine.begin() as conn:
        removed = clean(conn, user_id, dry_run=False)
        session_ids = apply_plan(conn, plan, user_id)
    write_state(user_id, session_ids, plan)

    print(
        f"\n写入前先按标记清理了一遍：流水 {removed['points_log']} 条、"
        f"调用 {removed['call_record']} 条、会话 {removed['chat_session']} 个"
    )
    print(f"已写入：会话 ID {session_ids}；状态文件 {STATE_PATH.name}")

    with engine.connect() as conn:
        after = table_counts(conn)
        after_user = user_row_counts(conn, user_id)
        balance = _scalar(
            conn,
            "SELECT balance FROM user_db.t_points_account WHERE user_id = :u",
            {"u": user_id},
        )
    print(f"\n执行后（全表）：{format_counts(after)}")
    print(f"执行后（{username} 自己的行数）：{format_counts(after_user)}")
    print(f"执行后余额：{balance}（计划 {plan.final_balance}）")

    if args.verify:
        with engine.connect() as conn:
            ok = verify(conn, user_id)
        if not ok:
            print("\n自检未全部通过，请检查上面的 FAIL 行。")
            return 1

    print("\n完成。清理命令：python scripts/devtools/seed_demo_data.py --clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
