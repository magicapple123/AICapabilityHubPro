"""Prove the data migration changes only known legacy catalog schemas."""

import json
import re
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.db.session import engine
from tests.conftest import DB_REASON, DB_READY

SERVICE_MIGRATION = Path(__file__).resolve().parents[1] / "sql/03_align_executor_schema.sql"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEPLOY_MIGRATION = REPOSITORY_ROOT / "deploy/mysql/init/03_capability_service.sql"


def _migration_updates(path: Path) -> tuple[str, ...]:
    sql = "\n".join(
        line for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("--")
    )
    return tuple(
        statement.strip()
        for statement in sql.split(";")
        if re.match(r"UPDATE\s+T_CAPABILITY\s+SET\b", statement.strip(), re.IGNORECASE)
    )


def test_deploy_init_contains_the_service_migration() -> None:
    service_updates = _migration_updates(SERVICE_MIGRATION)
    assert len(service_updates) == 2
    assert _migration_updates(DEPLOY_MIGRATION) == service_updates


def _decode_schema(value: object) -> dict | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return json.loads(value) if isinstance(value, str) else value


def test_migration_upgrades_legacy_defaults_without_overwriting_custom_schemas() -> None:
    if not DB_READY:
        pytest.skip(f"需要隔离 MySQL capability_db：{DB_REASON}")

    legacy_chat = {
        "type": "object",
        "properties": {"messages": {"type": "array"}},
        "required": ["messages"],
    }
    legacy_summary = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }
    custom_chat = {
        "type": "object",
        "description": "business-specific role and length limits",
        "properties": {
            "messages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "role": {"type": "string", "enum": ["user"]},
                        "content": {"type": "string", "maxLength": 100},
                    },
                    "required": ["role", "content"],
                },
            }
        },
        "required": ["messages"],
    }
    custom_summary = {
        "type": "object",
        "description": "short business summary only",
        "properties": {"text": {"type": "string", "maxLength": 64}},
        "required": ["text"],
    }
    existing_schema = {
        "type": "object",
        "properties": {
            "messages": {"type": "array", "maxItems": 9}
        },
    }
    rows = [
        ("legacy-online", "chat-completions", "online", 0, 5, legacy_chat),
        ("legacy-draft", "chat-completions", "draft", 0, 6, legacy_chat),
        ("custom-chat", "chat-completions", "online", 0, 7, custom_chat),
        ("current-chat", "chat-completions", "online", 0, 8, existing_schema),
        ("null-online-chat", "chat-completions", "online", 0, 9, None),
        ("null-draft-chat", "chat-completions", "draft", 0, 10, None),
        ("deleted-chat", "chat-completions", "online", 1, 11, legacy_chat),
        ("legacy-summary", "long-summary", "online", 0, 3, legacy_summary),
        ("legacy-offline-summary", "long-summary", "offline", 0, 15, legacy_summary),
        ("custom-summary", "long-summary", "online", 0, 12, custom_summary),
        ("null-online-summary", "long-summary", "online", 0, 13, None),
        ("null-offline-summary", "long-summary", "offline", 0, 14, None),
        ("other-adapter", "qa-custom-adapter", "online", 0, 16, legacy_chat),
    ]
    table = "qa_schema_migration_" + uuid4().hex
    connection = engine.connect()
    try:
        connection.exec_driver_sql(
            f"CREATE TEMPORARY TABLE `{table}` ("
            "case_name VARCHAR(64) NOT NULL, code VARCHAR(64) NOT NULL, "
            "status VARCHAR(16) NOT NULL, is_deleted TINYINT NOT NULL, "
            "price_per_call INT NOT NULL, param_schema JSON NULL)"
        )
        connection.execute(
            text(
                f"INSERT INTO `{table}` "
                "(case_name, code, status, is_deleted, price_per_call, param_schema) "
                "VALUES (:case_name, :code, :status, :is_deleted, :price, :schema)"
            ),
            [
                {
                    "case_name": name,
                    "code": code,
                    "status": status,
                    "is_deleted": deleted,
                    "price": price,
                    "schema": json.dumps(schema) if schema is not None else None,
                }
                for name, code, status, deleted, price, schema in rows
            ],
        )
        updates = _migration_updates(SERVICE_MIGRATION)
        assert len(updates) == 2
        for statement in updates:
            isolated_statement = re.sub(
                r"\bt_capability\b", f"`{table}`", statement, flags=re.IGNORECASE
            )
            connection.exec_driver_sql(isolated_statement)

        def snapshot() -> dict[str, tuple[str, int, int, dict | None]]:
            result = connection.execute(
                text(
                    f"SELECT case_name, status, is_deleted, price_per_call, param_schema "
                    f"FROM `{table}`"
                )
            )
            return {
                name: (status, deleted, price, _decode_schema(schema))
                for name, status, deleted, price, schema in result
            }

        migrated = snapshot()
        assert migrated["legacy-online"][3]["properties"]["messages"]["maxItems"] == 40
        assert migrated["legacy-draft"][3]["properties"]["messages"]["maxItems"] == 40
        assert migrated["legacy-summary"][3]["properties"]["max_length"]["default"] == 200
        assert migrated["legacy-offline-summary"][3]["properties"]["max_length"]["default"] == 200
        assert migrated["null-online-chat"][3] is not None
        assert migrated["null-online-summary"][3] is not None
        assert migrated["custom-chat"][3] == custom_chat
        assert migrated["custom-summary"][3] == custom_summary
        assert migrated["current-chat"][3] == existing_schema
        assert migrated["null-draft-chat"][3] is None
        assert migrated["null-offline-summary"][3] is None
        assert migrated["deleted-chat"][3] == legacy_chat
        assert migrated["other-adapter"][3] == legacy_chat
        for name, _, status, deleted, price, _ in rows:
            assert migrated[name][:3] == (status, deleted, price)

        for statement in updates:
            isolated_statement = re.sub(
                r"\bt_capability\b", f"`{table}`", statement, flags=re.IGNORECASE
            )
            connection.exec_driver_sql(isolated_statement)
        assert snapshot() == migrated
    finally:
        if connection.in_transaction():
            connection.rollback()
        connection.exec_driver_sql(f"DROP TEMPORARY TABLE IF EXISTS `{table}`")
        connection.commit()
        connection.close()
