"""Real MySQL assertions; qa fixture requires an isolated instance."""
from datetime import datetime

from sqlalchemy import text
from app.db.session import engine
from app.migrate import migrate
from tests.conftest import set_user_status


def test_registration_role_and_realtime_downgrade(qa):
    qa.register()
    assert qa.profile()['data']['role'] == 'user'
    def authorize():
        return qa.client.get('/internal/user/authorization', headers=qa.headers,
                             params={'user_id':qa.user_id,'required_role':'admin'}).json()
    assert authorize()['code'] == 1006
    with engine.begin() as conn:
        conn.execute(text("UPDATE t_user SET role='admin' WHERE id=:id"), {'id':qa.user_id})
    assert authorize()['data']['authorized'] is True
    with engine.begin() as conn:
        conn.execute(text("UPDATE t_user SET role='user' WHERE id=:id"), {'id':qa.user_id})
    assert authorize()['code'] == 1006
    set_user_status(qa.user_id, 'disabled')
    assert authorize()['code'] == 1005


def test_created_key_exchanges_but_disabled_and_expired_keys_fail(qa):
    qa.register()
    created = qa.create_key()['data']
    def exchange():
        return qa.client.post('/api/user/apikeys/exchange', json={
            'access_key':created['access_key'], 'secret_key':created['secret_key']}).json()
    assert exchange()['code'] == 0
    listed = qa.list_keys()['data']['list'][0]
    assert 'secret_key' not in listed and 'secret_hash' not in listed
    with engine.begin() as conn:
        conn.execute(text('UPDATE t_api_key SET expire_time=:expired WHERE id=:id'),
                     {'expired':datetime(2000,1,1),'id':created['id']})
    assert exchange()['code'] == 1003
    with engine.begin() as conn:
        conn.execute(text('UPDATE t_api_key SET expire_time=NULL WHERE id=:id'), {'id':created['id']})
    qa.disable_key(created['id'])
    assert exchange()['code'] == 1003


def test_deduction_conflict_cannot_change_amount_or_user(qa):
    qa.register()
    rid = qa.next_request_id()
    assert qa.deduct(amount=5,request_id=rid)['code'] == 0
    assert qa.deduct(amount=6,request_id=rid)['code'] == 3002
    assert qa.points()['data']['balance'] == 95


def test_legacy_role_migration_preserves_rows_and_is_repeatable(qa):
    with engine.connect() as conn:
        conn.execute(text('CREATE TEMPORARY TABLE t_user (id BIGINT PRIMARY KEY, nickname VARCHAR(32))'))
        try:
            conn.execute(text("INSERT INTO t_user VALUES (1,'legacy')"))
            migrate(conn)
            migrate(conn)
            row = conn.execute(text('SELECT id,nickname,role FROM t_user')).one()
            assert tuple(row) == (1,'legacy','user')
            conn.execute(text("UPDATE t_user SET role='admin' WHERE id=1"))
            migrate(conn)
            assert conn.execute(text('SELECT role FROM t_user')).scalar_one() == 'admin'
        finally:
            conn.execute(text('DROP TEMPORARY TABLE t_user'))
