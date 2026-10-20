"""Additive MySQL migration. Run offline with python -m app.migrate."""
from sqlalchemy import inspect, text
from app.db.session import engine


def migrate(connection):
    columns = {column['name'] for column in inspect(connection).get_columns('t_user')}
    if 'role' not in columns:
        connection.execute(text("ALTER TABLE t_user ADD COLUMN role VARCHAR(16) NOT NULL DEFAULT 'user'"))
    column = next(c for c in inspect(connection).get_columns('t_user') if c['name'] == 'role')
    if column['nullable'] or column['type'].length != 16:
        raise RuntimeError('Existing role column needs manual review; no data rewritten')


if __name__ == '__main__':
    with engine.begin() as connection:
        migrate(connection)
    print('User role migration verified; existing data retained')
