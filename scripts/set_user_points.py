"""调整本地演示账号的积分余额，并同步写一条调整流水。

为什么不用裸 SQL 改余额：`t_points_account.balance` 与 `t_points_log` 是
对账关系，页面会同时展示余额和流水。只改余额不写流水，两处金额对不上，
演示"可追溯"时会被自己的数据打脸。

用法（项目根目录，用任一服务的虚拟环境执行）：
    python scripts/set_user_points.py demo 100          # 设置成 100
    python scripts/set_user_points.py demo --add 50     # 在当前余额上加 50

安全边界：
- 只连 127.0.0.1:3307 上的 Pro MySQL，不碰 3306 的其它项目；
- 只改指定账号，不重导 seed、不动能力目录；
- 目标余额不能为负数；账号不存在会直接报错退出。
"""

from __future__ import annotations

import argparse
import sys
from uuid import uuid4

from devtools.environment import PROJECT_ROOT, read_env

BIZ_TYPE = "adjust"
REMARK = "管理员调整积分"


def connect(password: str):
    try:
        import pymysql
    except ImportError:
        raise SystemExit("需要 pymysql：请用 services/<服务>/.venv 里的 Python 运行") from None
    return pymysql.connect(
        host="127.0.0.1", port=3307, user="root", password=password,
        database="user_db", charset="utf8mb4", autocommit=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username", help="账号名，例如 demo")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("balance", nargs="?", type=int, help="目标余额")
    group.add_argument("--add", type=int, help="在当前余额上增减的数量")
    group.add_argument(
        "--sync-log", action="store_true",
        help="余额不变，只按流水净额补一条差额流水（用于在图形界面直接改过余额之后补账）",
    )
    args = parser.parse_args()

    password = read_env(PROJECT_ROOT / ".env").get("MYSQL_ROOT_PASSWORD", "")
    if not password:
        print("未找到 MYSQL_ROOT_PASSWORD，请先运行 python scripts/init_dev.py")
        return 1

    connection = connect(password)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT u.id, u.status, a.balance FROM t_user u "
                "JOIN t_points_account a ON a.user_id = u.id "
                "WHERE u.username = %s AND u.is_deleted = 0 AND a.is_deleted = 0",
                (args.username,),
            )
            row = cursor.fetchone()
            if row is None:
                print(f"账号 {args.username} 不存在，或没有积分账户")
                return 1
            user_id, status, balance = row

            if args.sync_log:
                # 按“流水净额”倒推应补的差额：适用于已在图形界面直接改过 balance 的场景。
                cursor.execute(
                    "SELECT COALESCE(SUM(CASE WHEN direction = 'in' THEN amount ELSE -amount END), 0) "
                    "FROM t_points_log WHERE user_id = %s AND is_deleted = 0",
                    (user_id,),
                )
                net = int(cursor.fetchone()[0])
                delta = balance - net
                if delta == 0:
                    print(f"{args.username} 余额 {balance} 与流水净额 {net} 已一致，无需补录")
                    return 0
                cursor.execute(
                    "INSERT INTO t_points_log "
                    "(user_id, direction, amount, balance_after, biz_type, request_id, remark) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (
                        user_id,
                        "in" if delta > 0 else "out",
                        abs(delta),
                        balance,
                        BIZ_TYPE,
                        f"adjust-{uuid4().hex}",
                        "管理员调整积分（补录差额）",
                    ),
                )
                connection.commit()
                print(f"{args.username}：流水净额 {net}，余额 {balance}，已补录 {abs(delta)} 积分")
                return 0

            target = balance + args.add if args.add is not None else args.balance
            if target < 0:
                print(f"目标余额不能为负数（当前 {balance}，计算结果 {target}）")
                return 1
            delta = target - balance
            if delta == 0:
                print(f"{args.username} 余额已经是 {balance}，无需调整")
                return 0

            cursor.execute(
                "UPDATE t_points_account SET balance = %s, version = version + 1 WHERE user_id = %s",
                (target, user_id),
            )
            cursor.execute(
                "INSERT INTO t_points_log "
                "(user_id, direction, amount, balance_after, biz_type, request_id, remark) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    user_id,
                    "in" if delta > 0 else "out",
                    abs(delta),
                    target,
                    BIZ_TYPE,
                    f"adjust-{uuid4().hex}",
                    REMARK,
                ),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    print(f"{args.username}（用户 {user_id}，状态 {status}）：{balance} -> {target}")
    print(f"已同步写入一条 {abs(delta)} 积分的调整流水，刷新页面即可看到")
    return 0


if __name__ == "__main__":
    sys.exit(main())
