"""Pure unit/HTTP security checks; database behavior has a separate suite."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
import importlib

import jwt
import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.core.exceptions import BizException
from app.core.jwt_util import create_token
from app.schemas.apikey import ApiKeyExchangeRequest
from app.service.apikey_service import ApiKeyService, _hash_secret
from app.db.session import get_db
from app.main import app


def credential_case():
    # Generated in memory; do not print credentials in test evidence.
    import secrets
    secret = secrets.token_hex(24)
    key = SimpleNamespace(user_id=1, secret_hash=_hash_secret(secret), status='enabled', expire_time=None)
    owner = SimpleNamespace(id=1, username='unit-user', status='normal', role='user')
    keys, users = Mock(), Mock()
    keys.find_by_access_key.return_value = key
    users.find_by_id.return_value = owner
    return ApiKeyService(keys, users), key, owner, ApiKeyExchangeRequest(access_key='unit-access', secret_key=secret)


def test_exchange_uses_owner_role_and_bounded_server_ttl(monkeypatch):
    service, key, owner, payload = credential_case()
    owner.role = 'admin'
    monkeypatch.setattr(settings, 'api_key_jwt_ttl_seconds', 100_000)
    result = service.exchange(None, payload)
    claims = jwt.decode(result['token'], settings.jwt_secret, algorithms=['HS256'], issuer=settings.jwt_issuer)
    # Boolean assertions prevent a failed test from rendering JWT/credentials.
    assert claims['sub'] == '1'
    assert claims['role'] == 'admin'
    assert claims['exp'] - claims['iat'] <= 3600
    assert result['expires_in'] == 3600


def test_exchange_cannot_outlive_key():
    service, key, owner, payload = credential_case()
    key.expire_time = datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None) + timedelta(seconds=60)
    result = service.exchange(None, payload)
    assert 1 <= result['expires_in'] <= 60
    claims = jwt.decode(result['token'], settings.jwt_secret, algorithms=['HS256'], issuer=settings.jwt_issuer)
    assert claims['exp'] <= int(key.expire_time.replace(tzinfo=timezone(timedelta(hours=8))).timestamp())


@pytest.mark.parametrize('failure', ['missing', 'wrong', 'disabled', 'expired', 'owner_missing', 'owner_disabled', 'unknown_role'])
def test_invalid_keys_have_identical_error(failure):
    service, key, owner, payload = credential_case()
    if failure == 'missing': service.api_keys.find_by_access_key.return_value = None
    if failure == 'wrong': key.secret_hash = '0' * 64
    if failure == 'disabled': key.status = 'disabled'
    if failure == 'expired': key.expire_time = datetime(2000, 1, 1)
    if failure == 'owner_missing': service.users.find_by_id.return_value = None
    if failure == 'owner_disabled': owner.status = 'disabled'
    if failure == 'unknown_role': owner.role = 'superuser'
    with pytest.raises(BizException) as caught:
        service.exchange(None, payload)
    assert caught.value.code == 1003
    assert str(caught.value) == 'API Key 凭证无效'


@pytest.mark.parametrize('ttl', [0, -1, 3601])
def test_signer_rejects_unsafe_exchange_ttl(ttl):
    with pytest.raises(BizException):
        create_token(1, 'unit', ttl_seconds=ttl)


def test_config_rejects_ttl_above_hard_limit():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, api_key_jwt_ttl_seconds=3601)


@pytest.mark.parametrize('path,payload', [
    ('/api/user/register', {'username':'unit-user', 'password':'unit-password-123', 'role':'admin'}),
    ('/api/user/profile', {'nickname':'new', 'role':'admin'}),
    ('/api/user/apikeys/exchange', {'access_key':'x', 'secret_key':'x', 'role':'admin'}),
    ('/api/user/apikeys/exchange', {'access_key':'x', 'secret_key':'x', 'ttl_seconds':999999}),
])
def test_public_requests_reject_privilege_and_ttl_injection(api, path, payload):
    method = api.put if path.endswith('profile') else api.post
    body = method(path, json=payload, headers={'X-User-Id':'1'}).json()
    assert body['code'] == 2001
    assert body['data'] is None


@pytest.mark.parametrize('headers', [{}, {'X-User-Id':'1'}, {'X-User-Id':'2','X-Request-Id':'unit-auth'}])
def test_authorization_rejects_missing_or_mismatched_identity(api, headers):
    body = api.get('/internal/user/authorization', params={'user_id':1,'required_role':'admin'}, headers=headers).json()
    assert body['code'] == 1001


def test_authorization_queries_current_role_and_state(api, monkeypatch):
    module = importlib.import_module('app.service.user_service')
    user = SimpleNamespace(id=1, role='admin', status='normal')
    monkeypatch.setattr(module.user_repository, 'find_by_id', lambda db, uid: user)
    app.dependency_overrides[get_db] = lambda: None
    try:
        def authorize():
            return api.get('/internal/user/authorization', params={'user_id':1,'required_role':'admin'},
                           headers={'X-User-Id':'1','X-Request-Id':'unit-auth'}).json()
        body = authorize()
        assert body['code'] == 0
        assert body['requestId'] == 'unit-auth'
        assert body['data'] == {'user_id':1, 'role':'admin', 'status':'normal','authorized':True}
        user.role = 'user'
        assert authorize()['code'] == 1006
        user.status = 'disabled'
        assert authorize()['code'] == 1005
    finally:
        app.dependency_overrides.clear()


def test_anonymous_post_exchange_no_store(api, monkeypatch):
    service, key, owner, payload = credential_case()
    module = importlib.import_module('app.api.v1.apikeys')
    monkeypatch.setattr(module, 'api_key_service', service)
    app.dependency_overrides[get_db] = lambda: None
    try:
        response = api.post('/api/user/apikeys/exchange', json={
            'access_key':payload.access_key, 'secret_key':payload.secret_key.get_secret_value()})
        assert response.json()['code'] == 0
        assert response.headers['cache-control'] == 'no-store'
        assert response.json()['data']['user_id'] == 1
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize('caller_id,target_id,expected_code', [('7', 8, 1001), ('7', 7, 0)])
def test_internal_points_check_enforces_current_identity(api, monkeypatch, caller_id, target_id, expected_code):
    module = importlib.import_module('app.api.v1.internal')
    calls = []

    def check_points(db, user_id, points_cost):
        calls.append((user_id, points_cost))
        return {'user_id': user_id, 'status': 'normal', 'balance': 50,
                'points_cost': points_cost, 'available': True}

    monkeypatch.setattr(module.points_service, 'check', check_points)
    app.dependency_overrides[get_db] = lambda: None
    try:
        body = api.get('/internal/user/check', params={'user_id': target_id, 'points_cost': 5},
                       headers={'X-User-Id': caller_id, 'X-Request-Id': 'identity-check'}).json()
        assert body['code'] == expected_code
        assert calls == ([(target_id, 5)] if expected_code == 0 else [])
        if expected_code:
            assert body['data'] is None
    finally:
        app.dependency_overrides.clear()
