"""Offline local administrator provisioning; no HTTP endpoint or embedded password."""
import argparse
from getpass import getpass

from sqlalchemy import select
from app.core.password import hash_password
from app.db.session import SessionLocal
from app.models import User, PointsAccount


def main():
    parser = argparse.ArgumentParser(description='Offline local administrator provisioning')
    parser.add_argument('username')
    args = parser.parse_args()
    from app.schemas.user import RegisterRequest
    password = getpass('New local admin password (hidden): ')
    if password != getpass('Repeat password: '):
        raise SystemExit('Passwords differ')
    payload = RegisterRequest(username=args.username, password=password)
    with SessionLocal.begin() as db:
        if db.scalar(select(User.id).where(User.username == payload.username, User.is_deleted == 0)):
            raise SystemExit('Account already exists; refusing to change its password or role')
        user = User(username=payload.username, nickname=payload.username,
                    password_hash=hash_password(payload.password), role='admin', status='normal')
        db.add(user)
        db.flush()
        db.add(PointsAccount(user_id=user.id, balance=0, frozen=0, version=0))
    print('Local admin created with zero points; no public registration was used')


if __name__ == '__main__':
    main()
