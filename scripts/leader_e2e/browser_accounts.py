"""Prepare a real administrator only inside the runtime-owned QA database."""
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from subprocess import CompletedProcess
from urllib.parse import urlsplit

from leader_e2e.checks import Api


@dataclass(frozen=True, repr=False)
class BrowserAccount:
    username: str
    password: str
    user_id: int


def prepare_browser_admin(
    gateway: str, sql: Callable[[str], CompletedProcess[str]], *,
    container_name: str, owned: bool,
) -> BrowserAccount:
    """Register normally, promote exactly that QA row, then obtain a real JWT.

    No developer DSN, pre-existing account, production endpoint or stored
    credential file is accepted. The SQL callable belongs to Runtime.sql.
    """
    address = urlsplit(gateway)
    if (not owned or not container_name.startswith("aihub-pro-leader-qa-") or
            address.scheme != "http" or address.hostname != "127.0.0.1" or
            not address.port or address.port in {8080, 8081, 8082, 8083, 8090} or
            address.path or address.query or address.fragment or address.username):
        raise RuntimeError("Browser fixtures require an owned isolated QA runtime")
    username, password = "qabr" + secrets.token_hex(6), secrets.token_urlsafe(24)
    public = Api(gateway)
    body, _ = public.ok("POST", "/api/user/register", {
        "username": username, "password": password,
    })
    data = body.get("data")
    if (not isinstance(data, dict) or type(data.get("user_id")) is not int or
            data["user_id"] <= 0 or data.get("role") != "user"):
        raise RuntimeError("QA registration did not return a normal user identity")
    user_id = data["user_id"]
    result = sql(
        "UPDATE user_db.t_user SET role='admin' "
        f"WHERE id={user_id} AND username='{username}' "
        "AND role='user' AND status='normal'; SELECT ROW_COUNT();"
    )
    if result.returncode or result.stdout.strip().splitlines()[-1:] != ["1"]:
        raise RuntimeError("QA promotion must affect exactly one newly registered user")
    login, _ = public.ok("POST", "/api/user/login", {
        "username": username, "password": password,
    })
    identity = login.get("data")
    if (not isinstance(identity, dict) or identity.get("user_id") != user_id or
            identity.get("role") != "admin" or not isinstance(identity.get("token"), str) or
            not identity["token"]):
        raise RuntimeError("QA administrator login did not return a signed identity")
    profile, _ = Api(gateway, identity["token"]).ok("GET", "/api/user/profile")
    current = profile.get("data")
    if (not isinstance(current, dict) or current.get("user_id") != user_id or
            current.get("role") != "admin" or current.get("status") != "normal"):
        raise RuntimeError("QA administrator profile does not match the current account")
    return BrowserAccount(username, password, user_id)
