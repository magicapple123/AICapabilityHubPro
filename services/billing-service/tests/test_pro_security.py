import asyncio
import importlib
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.exceptions import BizException
from app.schemas.internal import BillingRecordRequest
from app.service.billing_service import BillingService
from app.service.user_status import UserStatusService


@pytest.mark.parametrize('response', [None, {}, [], {'authorized':True},
    {'user_id':1,'status':'normal','role':'user','authorized':True},
    {'user_id':2,'status':'normal','role':'admin','authorized':True},
    {'user_id':1,'status':'disabled','role':'admin','authorized':True},
    {'user_id':1,'status':'normal','role':'admin','authorized':1},
    {'user_id':True,'status':'normal','role':'admin','authorized':True}])
def test_admin_fails_closed_on_ambiguous_response(monkeypatch, response):
    module = importlib.import_module('app.service.user_status')
    async def call(*args, **kwargs): return response
    monkeypatch.setattr(module, 'call_internal', call)
    with pytest.raises(BizException) as caught:
        asyncio.run(UserStatusService().ensure_admin(1))
    assert caught.value.code == 4002


@pytest.mark.parametrize('error', [BizException(1006,'权限不足'), BizException(1005,'禁用'),
    BizException(4002,'不可用'), TimeoutError(), ValueError()])
def test_authorization_failure_never_grants_access(monkeypatch, error):
    module = importlib.import_module('app.service.user_status')
    async def call(*args, **kwargs): raise error
    monkeypatch.setattr(module, 'call_internal', call)
    with pytest.raises(BizException) as caught:
        asyncio.run(UserStatusService().ensure_admin(1))
    assert caught.value.code == (error.code if isinstance(error, BizException) else 4002)


def test_admin_uses_frozen_contract_and_rechecks_downgrade(monkeypatch):
    module = importlib.import_module('app.service.user_status')
    data = {'user_id':1,'status':'normal','role':'admin','authorized':True}
    async def call(service, method, path, **kwargs):
        assert method == 'GET'
        assert path == '/internal/user/authorization'
        assert kwargs['params'] == {'user_id':1, 'required_role':'admin'}
        return data
    monkeypatch.setattr(module, 'call_internal', call)
    service = UserStatusService()
    asyncio.run(service.ensure_admin(1))
    data['role'] = 'user'
    with pytest.raises(BizException): asyncio.run(service.ensure_admin(1))


@pytest.mark.parametrize('status,points,price', [('success',5,5),('degraded',0,5),('failed',0,5),('success',0,0)])
def test_pro_prices_preserve_registered_and_actual_cost(status, points, price):
    payload = BillingRecordRequest(request_id='unit', user_id=1, capability_id=2,
                                   points=points, unit_price=price, status=status)
    assert payload.unit_price == price
    assert payload.points == points


@pytest.mark.parametrize('status,points,price', [('success',3,5),('degraded',5,5),('failed',1,5),('success',1,True)])
def test_conflicting_charge_and_price_is_rejected(status, points, price):
    with pytest.raises(ValidationError):
        BillingRecordRequest(request_id='unit',user_id=1,points=points,unit_price=price,status=status)


@pytest.mark.parametrize('field,value', [('user_id',2),('capability_id',2),('service_name','other'),
    ('points',4),('unit_price',4),('model','other'),('duration_ms',90),('status','degraded')])
def test_replay_rejects_critical_field_conflicts(field, value):
    base = dict(request_id='unit', user_id=1, capability_id=1, service_name='ai-chat-service',
                points=5, unit_price=5, model='unit-model', status='success')
    existing = SimpleNamespace(user_id=1, capability_id=1, service_name='ai-chat-service',
                               cost=5, unit_price=5, model_name='unit-model', duration_ms=12, call_status='success')
    # model_copy isolates replay matching from independent schema validation.
    payload = BillingRecordRequest(**base).model_copy(update={field:value})
    if field == 'status':
        from app.core.constants import CallStatus
        payload.status = CallStatus(value)
    assert BillingService._is_same_call(existing, payload) is False


def test_overview_ignores_forged_jwt_role_header(api, monkeypatch):
    module = importlib.import_module('app.service.user_status')
    async def denied(*args, **kwargs): raise BizException(1006, '权限不足')
    monkeypatch.setattr(module, 'call_internal', denied)
    body = api.get('/api/billing/stat/overview', headers={
        'X-User-Id':'1', 'X-User-Role':'admin', 'X-Request-Id':'unit'}).json()
    assert body['code'] == 1006
    assert body['data'] is None
