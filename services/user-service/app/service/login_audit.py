"""Append login-failure metadata without credentials or raw account input."""

from sqlalchemy.orm import Session

from app.core.logging import get_request_id
from app.core.security import UserContext
from app.service.audit_service import stage
from app.service.login_protection import fingerprint


def record_failure(
    db: Session, *, username: str, peer_ip: str,
    reason: str, user_id: int | None = None,
) -> None:
    account_fingerprint = fingerprint(username.strip().casefold())
    stage(
        db,
        actor=UserContext(user_id="anonymous", user_name="", request_id=get_request_id()),
        resource_type="user", resource_id=user_id or account_fingerprint,
        action="login_failed", before=None,
        after={
            "reason": reason, "account_fingerprint": account_fingerprint,
            "peer_fingerprint": fingerprint(peer_ip or "unknown"),
        },
    )
    # Failed authentication still needs a durable audit row. It changes no user,
    # balance or credential state, and runs before raising the business error.
    db.commit()
