"""Additive MySQL migration; unknown historical prices remain NULL."""
from sqlalchemy import inspect, text
from app.db.session import engine


def migrate(connection):
    columns = {column['name'] for column in inspect(connection).get_columns('t_call_record')}
    if 'unit_price' not in columns:
        connection.execute(text('ALTER TABLE t_call_record ADD COLUMN unit_price BIGINT NULL'))
    column = next(c for c in inspect(connection).get_columns('t_call_record') if c['name'] == 'unit_price')
    if not column['nullable']:
        raise RuntimeError('Existing price column needs manual review; no data rewritten')


if __name__ == '__main__':
    with engine.begin() as connection:
        migrate(connection)
    print('Billing price migration verified; historical unknown prices retained as NULL')
