"""把本地演示库恢复到“刚初始化”的干净状态，供答辩或彩排前重置。

只删除三类数据：调用记录、会话消息、API Key 与积分流水；保留账号与能力目录。
演示账号的积分统一回到 100，便于现场完整演示一次扣费。

用法（项目根目录，需先启动 MySQL 容器）：
    python scripts/reset_demo_data.py --yes

安全边界：
- 仅连接 127.0.0.1 上 Pro 的 MySQL（默认 3307），不会动 3306 上的其它项目；
- 只清理下方列出的演示账号，不重导 seed、不改能力目录与价格；
- 必须显式加 --yes 才会执行，默认只打印将要删除的行数。
"""

from __future__ import annotations

import argparse
import sys

from devtools.environment import PROJECT_ROOT, read_env

DEMO_USERS = ("demo", "demopoor", "demodisabled")
DEMO_BALANCE = {"demo": 100, "demopoor": 0, "demodisabled": 50}


def connect(password: str):
    """返回指向 Pro MySQL 的连接；缺依赖时给出清晰提示。"""

    try:
        import pymysql
    except ImportError:
        raise SystemExit("需要 pymysql：使用任一服务的 .venv 运行本脚本") from None
    return pymysql.connect(
        host="127.0.0.1", port=3307, user="root", password=password,
        charset="utf8mb4", autocommit=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="真正执行删除；缺省只统计")
    args = parser.parse_args()

    shared = read_env(PROJECT_ROOT / ".env")
    password = shared.get("MYSQL_ROOT_PASSWORD", "")
    if not password:
        print("未找到 MYSQL_ROOT_PASSWORD，请先运行 python scripts/init_dev.py", flush=True)
        return 1

    connection = connect(password)
    plans = [
        ("ai_chat_db", "DELETE FROM t_chat_message"),
        ("ai_chat_db", "DELETE FROM t_chat_session"),
        ("billing_db", "DELETE FROM t_call_record"),
        ("billing_db", "DELETE FROM t_usage_daily"),
        ("user_db", "DELETE FROM t_points_log"),
        ("user_db", "DELETE FROM t_api_key"),
    ]
    try:
        with connection.cursor() as cursor:
            for database, statement in plans:
                cursor.execute(f"USE {database}")
                if args.yes:
                    affected = cursor.execute(statement)
                    print(f"{database}: {statement.split('FROM ')[1]} 删除 {affected} 行")
                else:
                    table = statement.split("FROM ")[1]
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    print(f"{database}.{table}: 待删除 {cursor.fetchone()[0]} 行")

            cursor.execute(
                f"SELECT id, username FROM t_user WHERE username IN "
                f"({','.join(['%s'] * len(DEMO_USERS))})",
                DEMO_USERS,
            )
            users = cursor.fetchall()
            for user_id, username in users:
                balance = DEMO_BALANCE.get(username, 0)
                if args.yes:
                    cursor.execute(
                        "UPDATE t_points_account SET balance=%s, frozen=0 WHERE user_id=%s",
                        (balance, user_id),
                    )
                print(f"user_db: {username} 积分重置为 {balance}")

        if args.yes:
            connection.commit()
            print("已重置。重新登录即可看到干净的演示数据。")
        else:
            connection.rollback()
            print("仅统计，未修改。确认后加 --yes 执行。")
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
