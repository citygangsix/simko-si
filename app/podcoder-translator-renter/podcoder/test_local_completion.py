"""Resumed local 8: offline regressions. All authority keys are generated fixtures."""
import copy
import importlib.util
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def keys():
    from cryptography.hazmat.primitives.asymmetric import rsa
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private, private.public_key()


@pytest.fixture
def browser(monkeypatch):
    import browser_driver as b
    monkeypatch.setenv('SIMKO_BROWSER', '1')
    monkeypatch.setenv('SIMKO_BROWSER_DOMAINS', 'forms.example')
    original = b.allowed
    public = lambda *a, **k: [(0, 0, 0, '', ('93.184.216.34', 443))]
    monkeypatch.setattr(b, 'allowed', lambda url, domains: original(url, domains, resolver=public))
    with b._LOCK:
        b._PENDING.clear()
    return b


def prepare(b, **kwargs):
    return b.prepare('alice', 'https://forms.example/form', {'message': 'approved body'}, **kwargs)


def test_browser_confirmation_owner_replay_and_bound_content(browser, monkeypatch):
    seen = []
    monkeypatch.setattr(browser, '_interactive', lambda action: seen.append(action) or {'ok': True})
    fields = {'message': 'approved body'}
    p = browser.prepare('alice', 'https://forms.example/form', fields)
    fields['message'] = 'changed'
    p['confirmation']['fields']['message'] = 'also changed'
    ticket = p['approval_ticket']
    assert not browser.submit('bob', ticket, owner_confirmed=True)['ok']
    assert seen == []
    assert browser.submit('alice', ticket, owner_confirmed=True)['ok']
    assert seen[0]['fields']['message'] == 'approved body'
    assert not browser.submit('alice', ticket, owner_confirmed=True)['ok']
    assert len(seen) == 1


@pytest.mark.parametrize('confirm', [False, None, 'true', 1])
def test_browser_requires_literal_confirmation(browser, monkeypatch, confirm):
    monkeypatch.setattr(browser, '_interactive', lambda _: pytest.fail('unapproved action'))
    assert not browser.submit('alice', prepare(browser)['approval_ticket'], owner_confirmed=confirm)['ok']


def test_browser_expiry_disabled_and_failure_consumed(browser, monkeypatch):
    ticket = prepare(browser)['approval_ticket']
    browser._PENDING[ticket]['expires'] = 0
    assert not browser.submit('alice', ticket, owner_confirmed=True)['ok']
    monkeypatch.setenv('SIMKO_BROWSER', '0')
    assert not prepare(browser)['ok']
    assert not browser.submit('alice', ticket, owner_confirmed=True)['ok']
    monkeypatch.setenv('SIMKO_BROWSER', '1')
    ticket = prepare(browser)['approval_ticket']
    monkeypatch.setattr(browser, '_interactive', lambda _: (_ for _ in ()).throw(RuntimeError('private detail')))
    result = browser.submit('alice', ticket, owner_confirmed=True)
    assert not result['ok'] and 'private detail' not in str(result)
    assert not browser.submit('alice', ticket, owner_confirmed=True)['ok']


@pytest.mark.parametrize('fields', [{'password': 'no'}, {'email': 'no'}, {'message': 1}, {}, {'message': 'x'*4001}])
def test_browser_rejects_sensitive_and_invalid_fields(browser, fields):
    assert not browser.prepare('alice', 'https://forms.example/form', fields)['ok']


def test_browser_single_use_concurrent(browser, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    seen = []
    monkeypatch.setattr(browser, '_interactive', lambda action: seen.append(action) or {'ok': True})
    ticket = prepare(browser)['approval_ticket']
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: browser.submit('alice', ticket, owner_confirmed=True), range(8)))
    assert sum(r['ok'] for r in results) == 1 and len(seen) == 1


@pytest.mark.parametrize('html,operation,expected', [
    ('<form method=post><input name=message><button>Send</button></form>', 'submit', True),
    ('<form method=post><textarea name=message></textarea></form>', 'fill', True),
    ('<form method=post action="https://other.example/form"><input name=message></form>', 'submit', False),
    ('<form method=post action="/other"><input name=message></form>', 'submit', False),
    ('<form method=get><input name=message></form>', 'submit', False),
    ('<form method=post><input name=message><input type=hidden name=extra value=bad></form>', 'submit', False),
    ('<form method=post><input name=message><input type=password name=pw></form>', 'submit', False),
    ('<form method=post><input name=message><input name=message></form>', 'submit', False),
])
def test_browser_real_dom_offline(browser, monkeypatch, html, operation, expected):
    """Real Chromium DOM/typing, with every allowed request fulfilled locally.

    The route adapter below replaces continue_ with fulfill, so there is no DNS,
    external form submission or live network even when the policy permits POST.
    """
    import playwright.sync_api as api
    real_factory = api.sync_playwright
    requests = []

    class Route:
        def __init__(self, route):
            self.inner = route
            self.request = route.request
        def abort(self):
            return self.inner.abort()
        def continue_(self):
            requests.append((self.request.method, self.request.post_data))
            return self.inner.fulfill(status=200, content_type='text/html', body=html if self.request.method == 'GET' else '<p>mock accepted</p>')

    class Context:
        def __init__(self, context): self.inner = context
        def route(self, pattern, handler): self.inner.route(pattern, lambda route: handler(Route(route)))
        def new_page(self): return self.inner.new_page()

    class Browser:
        def __init__(self, actual): self.inner = actual
        def new_context(self, **kwargs): return Context(self.inner.new_context(**kwargs))
        def close(self): self.inner.close()

    class Factory:
        def __enter__(self):
            self.manager = real_factory()
            self.real = self.manager.__enter__()
            return SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kw: Browser(self.real.chromium.launch(channel='chrome', headless=True, args=['--no-sandbox', '--disable-dev-shm-usage']))))
        def __exit__(self, *args): return self.manager.__exit__(*args)

    monkeypatch.setattr(api, 'sync_playwright', Factory)
    ticket = prepare(browser, operation=operation)['approval_ticket']
    result = browser.submit('alice', ticket, owner_confirmed=True)
    assert result['ok'] == expected
    posts = [r for r in requests if r[0] == 'POST']
    assert len(posts) == (1 if expected and operation == 'submit' else 0)
    if posts:
        assert posts[0][1] == 'message=approved+body'


def template():
    return json.dumps({'format': 'simko-agent-template', 'version': 1, 'name': 'Pair',
                      'agents': [{'name': 'A', 'instructions': 'User applied fixture instructions'}]})


def test_apply_template_scoping_validation_and_history(tmp_path):
    import local_exports as e
    assert not e.apply_template(tmp_path, 'alice', template())['ok']
    imported = e.import_template(tmp_path, template())
    assert e.apply_template(tmp_path, 'alice', imported['content'], owner_confirmed=True)['ok']
    assert e.active_template(tmp_path, 'alice')['template']['name'] == 'Pair'
    assert not e.active_template(tmp_path, 'bob')['ok']
    doc = json.loads(template())
    doc['agents'][0]['tools'] = ['danger']
    with pytest.raises(ValueError):
        e.apply_template(tmp_path, 'alice', json.dumps(doc), owner_confirmed=True)
    assert e.apply_template(tmp_path, 'alice', template(), owner_confirmed=True)['started'] is False
    import sqlite3
    with sqlite3.connect(tmp_path/'agent_templates.sqlite') as conn:
        assert conn.execute('select count(*) from applied').fetchone()[0] == 2


def test_applied_instructions_reach_agents(monkeypatch):
    import multi_agents as agents
    monkeypatch.setenv('SIMKO_AGENTS', '1')
    monkeypatch.setenv('SIMKO_PAID_API_ENABLED', '1')
    seen = []
    group = agents.start('alice', [], 'fixture task', configurations=json.loads(template())['agents'],
                         complete=lambda messages: seen.append(messages) or {'ok': True, 'text': 'done'})
    for _ in range(100):
        status = agents.status('alice', group['id'])
        if status['status'] != 'running': break
        time.sleep(.01)
    assert status['status'] == 'done' and len(seen) == 2
    assert all('User applied fixture instructions' in msg[0]['content'] for msg in seen)


def snapshot(private, **overrides):
    import jwt
    claims = {'iss': 'https://simkosi.com', 'aud': 'simko-team', 'iat': int(time.time()), 'exp': int(time.time())+300,
              'team': 'remote:family', 'revision': 1, 'members': {'alice': 'owner', 'bob': 'child', 'carol': 'adult'},
              'resources': {'notes': {'read': ['owner', 'adult', 'child'], 'use': ['owner', 'adult']},
                            'private': {'read': ['owner'], 'use': ['owner']}}}
    claims.update(overrides)
    return jwt.encode(claims, private, algorithm='RS256')


@pytest.fixture
def remote(monkeypatch, keys):
    import family_team as team
    monkeypatch.setenv('SIMKO_TEAM_PUBLIC_KEY', keys[1].public_bytes(
        __import__('cryptography.hazmat.primitives.serialization', fromlist=['Encoding']).Encoding.PEM,
        __import__('cryptography.hazmat.primitives.serialization', fromlist=['PublicFormat']).PublicFormat.SubjectPublicKeyInfo).decode())
    return team


def test_remote_resource_acl_and_revision(remote, tmp_path, keys):
    token = snapshot(keys[0])
    assert not remote.import_permissions(tmp_path, 'outsider', token)['ok']
    assert remote.import_permissions(tmp_path, 'alice', token)['ok']
    assert remote.resource(tmp_path, 'alice', 'remote:family', 'notes', content='local fixture')['ok']
    assert remote.resource(tmp_path, 'bob', 'remote:family', 'notes')['content'] == 'local fixture'
    assert not remote.resource(tmp_path, 'bob', 'remote:family', 'notes', content='change')['ok']
    assert not remote.resource(tmp_path, 'carol', 'remote:family', 'private')['ok']
    assert not remote.resource(tmp_path, 'outsider', 'remote:family', 'notes')['ok']
    assert not remote.set_member(tmp_path, 'alice', 'remote:family', 'bob', 'adult')['ok']
    assert not remote.import_permissions(tmp_path, 'alice', token)['ok']
    assert remote.import_permissions(tmp_path, 'alice', snapshot(keys[0], revision=2, members={'alice': 'owner'}))['ok']
    assert not remote.resource(tmp_path, 'bob', 'remote:family', 'notes')['ok']
    assert not remote.import_permissions(tmp_path, 'alice', token)['ok']


@pytest.mark.parametrize('overrides', [
    {'exp': 1}, {'aud': 'other'}, {'iss': 'other'}, {'revision': 0},
    {'members': {'alice': 'owner', 'bob': 'owner'}},
    {'resources': {'notes': {'read': ['superadmin']}}},
])
def test_remote_rejects_bad_claims(remote, tmp_path, keys, overrides):
    assert not remote.import_permissions(tmp_path, 'alice', snapshot(keys[0], **overrides))['ok']


def test_remote_signature_and_expiry_rechecked(remote, tmp_path, keys, monkeypatch):
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    wrong = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert not remote.import_permissions(tmp_path, 'alice', snapshot(wrong))['ok']
    assert remote.import_permissions(tmp_path, 'alice', snapshot(keys[0]))['ok']
    monkeypatch.setattr(jwt, 'decode', lambda *a, **kw: (_ for _ in ()).throw(ValueError('expired')))
    assert not remote.resource(tmp_path, 'alice', 'remote:family', 'notes')['ok']


def test_checkout_disabled_idempotent_and_entitlement(monkeypatch, tmp_path, keys):
    import sandbox_checkout as c
    import usage_ledger
    provider = c.MockSquareSandbox()
    monkeypatch.setenv('SIMKO_PAYWALL', '0')
    assert not c.create(tmp_path, 'alice', 'request-1', owner_confirmed=True, provider=provider)['ok']
    monkeypatch.setenv('SIMKO_PAYWALL', '1')
    assert not c.create(tmp_path, 'alice', 'request-1', provider=provider)['ok']
    order = c.create(tmp_path, 'alice', 'request-1', owner_confirmed=True, provider=provider)
    assert order['ok'] and not order['charged'] and order['checkout_url'] is None
    assert c.create(tmp_path, 'alice', 'request-1', owner_confirmed=True, provider=provider)['id'] == order['id']
    assert not c.reconcile(tmp_path, 'bob', order['id'], provider=provider)['ok']
    assert not c.issue_test_entitlement(tmp_path, 'alice', order['id'], keys[0], provider=provider)['ok']
    provider.complete_for_test(order['id'])
    issued = c.issue_test_entitlement(tmp_path, 'alice', order['id'], keys[0], provider=provider)
    assert issued['ok'] and not issued['production_access']
    assert c.verify_test_entitlement('alice', issued['token'], keys[1])
    assert not c.verify_test_entitlement('bob', issued['token'], keys[1])
    monkeypatch.setenv('SIMKO_ENTITLEMENT_JWT', issued['token'])
    from cryptography.hazmat.primitives import serialization
    monkeypatch.setenv('SIMKO_ENTITLEMENT_PUBLIC_KEY', keys[1].public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode())
    assert not usage_ledger.paid('alice')
    monkeypatch.setenv('SIMKO_PAYWALL', '0')
    assert not c.verify_test_entitlement('alice', issued['token'], keys[1])


@pytest.mark.parametrize('field,value', [('status', 'APPROVED'), ('amount_money', {'amount': 1, 'currency': 'USD'}), ('owner', 'bob'), ('environment', 'production')])
def test_checkout_rejects_unverified_receipts(monkeypatch, tmp_path, field, value):
    import sandbox_checkout as c
    monkeypatch.setenv('SIMKO_PAYWALL', '1')
    provider = c.MockSquareSandbox()
    order = c.create(tmp_path, 'alice', 'request-1', owner_confirmed=True, provider=provider)
    provider._payments[order['id']][field] = value
    assert not c.reconcile(tmp_path, 'alice', order['id'], provider=provider)['ok']


def test_release_preflight(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location('release_preflight', root/'tools/release_preflight.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for flag in module.FLAGS: monkeypatch.delenv('SIMKO_'+flag, raising=False)
    result = module.audit()
    assert result['ok'] and not result['release_ready'] and not result['signed']
    monkeypatch.setenv('SIMKO_BROWSER', '1')
    assert not module.audit()['ok']


def test_new_api_auth_defaults_and_owner_scoping(monkeypatch, tmp_path):
    import platform_api as api
    import auth_accounts
    for flag in api.FLAGS:
        monkeypatch.delenv('SIMKO_'+flag.upper(), raising=False)
    assert not any(api.flags().values())
    routes = ['templates/apply', 'templates/active', 'browser/prepare', 'browser/confirm',
              'team/permissions/import', 'team/resource/read', 'team/resource/write', 'checkout/create', 'checkout/status']
    for route in routes:
        assert api.handle('POST', '/api/platform/'+route, {}, tmp_path)[0] == 403
    monkeypatch.setenv('SIMKO_PLATFORM_UI', '1')
    for route in routes:
        assert api.handle('POST', '/api/platform/'+route, {}, tmp_path)[0] == 401
    alice = auth_accounts.signin_oidc(tmp_path, 'google', {'sub': 'api-alice'})['token']
    bob = auth_accounts.signin_oidc(tmp_path, 'google', {'sub': 'api-bob'})['token']
    code, result = api.handle('POST', '/api/platform/templates/apply',
                            {'token': alice, 'content': template(), 'owner_confirmed': True}, tmp_path)
    assert code == 200 and result['ok'] and not result['started']
    assert not api.handle('POST', '/api/platform/templates/active', {'token': bob}, tmp_path)[1]['ok']
    assert not api.handle('POST', '/api/platform/browser/prepare',
                          {'token': alice, 'url': 'https://forms.example/form', 'fields': {'message': 'test'}}, tmp_path)[1]['ok']
    assert not api.handle('POST', '/api/platform/checkout/create',
                          {'token': alice, 'request_id': 'request-1', 'owner_confirmed': True}, tmp_path)[1]['ok']


def test_production_entitlement_rejects_sandbox_flag(monkeypatch, keys):
    import jwt
    import usage_ledger
    from cryptography.hazmat.primitives import serialization
    monkeypatch.setenv('SIMKO_ENTITLEMENT_PUBLIC_KEY', keys[1].public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode())
    claims = {'iss': 'https://simkosi.com', 'aud': 'simko-desktop', 'sub': 'alice', 'exp': int(time.time())+60, 'plan': 'paid', 'sandbox': True}
    monkeypatch.setenv('SIMKO_ENTITLEMENT_JWT', jwt.encode(claims, keys[0], algorithm='RS256'))
    assert not usage_ledger.paid('alice')
    claims['sandbox'] = False
    monkeypatch.setenv('SIMKO_ENTITLEMENT_JWT', jwt.encode(claims, keys[0], algorithm='RS256'))
    assert usage_ledger.paid('alice') and not usage_ledger.paid('bob')
    claims['exp'] = 1
    monkeypatch.setenv('SIMKO_ENTITLEMENT_JWT', jwt.encode(claims, keys[0], algorithm='RS256'))
    assert not usage_ledger.paid('alice')


def test_browser_api_binds_ticket_not_confirm_body(browser, monkeypatch, tmp_path):
    import platform_api
    import auth_accounts
    monkeypatch.setenv('SIMKO_PLATFORM_UI', '1')
    token = auth_accounts.signin_oidc(tmp_path, 'google', {'sub': 'browser-api'})['token']
    seen = []
    monkeypatch.setattr(browser, '_interactive', lambda action: seen.append(action) or {'ok': True})
    _, prepared = platform_api.handle('POST', '/api/platform/browser/prepare',
        {'token': token, 'url': 'https://forms.example/form', 'fields': {'message': 'original'}}, tmp_path)
    assert prepared['ok'] and seen == []
    _, confirmed = platform_api.handle('POST', '/api/platform/browser/confirm',
        {'token': token, 'approval_ticket': prepared['approval_ticket'], 'owner_confirmed': True,
         'url': 'https://evil.example', 'fields': {'message': 'not approved'}}, tmp_path)
    assert confirmed['ok'] and seen[0]['fields'] == {'message': 'original'}


def test_template_api_start_uses_applied_count(monkeypatch, tmp_path):
    import platform_api
    import auth_accounts
    import multi_agents
    import usage_ledger
    monkeypatch.setenv('SIMKO_PLATFORM_UI', '1')
    monkeypatch.setenv('SIMKO_PAID_API_ENABLED', '1')
    token = auth_accounts.signin_oidc(tmp_path, 'google', {'sub': 'template-api'})['token']
    platform_api.handle('POST', '/api/platform/templates/apply',
        {'token': token, 'content': template(), 'owner_confirmed': True}, tmp_path)
    counts, configs = [], []
    monkeypatch.setattr(usage_ledger, 'reserve', lambda state, owner, capability, count: counts.append(count) or {'ok': True})
    monkeypatch.setattr(multi_agents, 'start', lambda owner, names, task, **kw: configs.append(kw['configurations']) or {'ok': True})
    code, result = platform_api.handle('POST', '/api/platform/agents/start',
        {'token': token, 'use_applied_template': True, 'task': 'mock only', 'approve_paid': True, 'names': []}, tmp_path)
    assert code == 200 and result['ok'] and counts == [2]
    assert configs[0] == json.loads(template())['agents']
