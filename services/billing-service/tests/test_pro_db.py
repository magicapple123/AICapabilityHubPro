from sqlalchemy import text

from app.db.session import engine
from app.migrate import migrate
from tests.conftest import count_records


def test_pro_price_cost_capability_and_deduction_match(qa, fake_user_service):
    rid = qa.next_request_id()
    payload = {'request_id':rid,'user_id':qa.user_id,'capability_id':2,'service_name':'ai-chat-service',
               'model':'unit-model','unit_price':3,'points':3,'status':'success','duration_ms':12}
    def record(body):
        return qa.client.post('/internal/billing/record',headers=qa.headers(rid),json=body).json()
    first = record(payload)
    assert first['code'] == 0
    assert first['data']['unit_price'] == 3
    assert first['data']['cost'] == 3
    assert first['data']['capability_id'] == 2
    assert record(payload)['data']['duplicated'] is True
    assert len(fake_user_service.deduct_paths) == 1
    listed = qa.records()['data']['list'][0]
    assert listed['unit_price'] == listed['cost'] == 3
    assert fake_user_service.calls[0][3]['json']['request_id'] == rid
    # Equal actual fee (0) still conflicts when registered price changes.
    free_rid = qa.next_request_id()
    free = dict(payload,request_id=free_rid,points=0,status='degraded')
    headers = qa.headers(free_rid)
    assert qa.client.post('/internal/billing/record',headers=headers,json=free).json()['code'] == 0
    free['unit_price'] = 4
    assert qa.client.post('/internal/billing/record',headers=headers,json=free).json()['code'] == 3002
    assert len(fake_user_service.deduct_paths) == 1


def test_overview_realtime_role_changes(qa, fake_user_service):
    assert qa.overview()['code'] == 0
    fake_user_service.roles[qa.user_id] = 'user'
    assert qa.overview()['code'] == 1006
    assert qa.usage()['code'] == 0
    assert qa.records()['code'] == 0


def test_historical_unknown_price_stays_null_and_migration_repeats(qa):
    with engine.connect() as conn:
        conn.execute(text('CREATE TEMPORARY TABLE t_call_record (id BIGINT PRIMARY KEY, cost BIGINT)'))
        try:
            conn.execute(text('INSERT INTO t_call_record VALUES (1,5)'))
            migrate(conn)
            migrate(conn)
            row = conn.execute(text('SELECT id,cost,unit_price FROM t_call_record')).one()
            assert tuple(row) == (1,5,None)
        finally:
            conn.execute(text('DROP TEMPORARY TABLE t_call_record'))
