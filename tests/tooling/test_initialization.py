"""Protect local configuration from overwrite and mismatched credentials."""

from pathlib import Path

import pytest

from devtools.environment import SERVICES, read_env
from devtools.initialization import initialize


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    paths = [tmp_path / "web", tmp_path / "deploy"]
    paths.extend(tmp_path / "services" / name for name in SERVICES)
    for directory in paths:
        directory.mkdir(parents=True)
        (directory / ".env.example").write_text("# template\nUSE_MOCK=true\n", encoding="utf-8")
    return tmp_path


def test_generated_credentials_match_and_repeat_does_not_overwrite(project: Path) -> None:
    results = initialize(project)
    assert len(results) == 7
    assert all(created for _, created in results)
    initial = {path: path.read_bytes() for path, _ in results}
    shared = read_env(project / ".env")
    assert len(shared["JWT_SECRET"].encode()) >= 32
    user = read_env(project / "services" / "user-service" / ".env")
    assert user["JWT_SECRET"] == shared["JWT_SECRET"]
    deploy = read_env(project / "deploy" / ".env")
    assert deploy["MYSQL_ROOT_PASSWORD"] == shared["MYSQL_ROOT_PASSWORD"]
    assert read_env(project / "web" / ".env")["VITE_USE_MOCK_LOGIN"] == "false"
    assert all(not created for _, created in initialize(project))
    assert all(path.read_bytes() == content for path, content in initial.items())


def test_explicit_local_web_preference_is_preserved(project: Path) -> None:
    path = project / "web" / ".env"
    path.write_text("VITE_USE_MOCK_LOGIN=true\n", encoding="utf-8")
    initialize(project)
    assert path.read_text(encoding="utf-8") == "VITE_USE_MOCK_LOGIN=true\n"


def test_incomplete_shared_config_does_not_create_any_other_config(project: Path) -> None:
    path = project / ".env"
    path.write_text("JWT_SECRET=" + "a" * 64 + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="incomplete"):
        initialize(project)
    assert not (project / "deploy" / ".env").exists()


def test_existing_credential_mismatch_stops_before_writing(project: Path) -> None:
    (project / ".env").write_text(
        "JWT_SECRET=" + "a" * 64 + "\nMYSQL_ROOT_PASSWORD=local\nJWT_ISSUER=ai-capability-hub\n",
        encoding="utf-8",
    )
    (project / "services" / "user-service" / ".env").write_text(
        "JWT_SECRET=" + "b" * 64, encoding="utf-8",
    )
    with pytest.raises(ValueError, match="differs"):
        initialize(project)
    assert not (project / "deploy" / ".env").exists()


def test_database_password_special_characters_are_url_encoded(project: Path) -> None:
    (project / ".env").write_text(
        "JWT_SECRET=" + "a" * 64 + "\nMYSQL_ROOT_PASSWORD=p@ss/#%\nJWT_ISSUER=ai-capability-hub\n",
        encoding="utf-8",
    )
    initialize(project)
    values = read_env(project / "services" / "user-service" / ".env")
    assert "p%40ss%2F%23%25@127.0.0.1" in values["DB_URL"]
