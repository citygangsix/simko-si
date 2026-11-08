"""Offline-only desktop integration and security tests. Never contacts providers."""
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path
import pytest
import vault
import platform_paths


def legacy_blob(password, doc):
    salt, nonce = b's' * 16, b'n' * 16
    raw = json.dumps(doc).encode()
    key = vault._key(password, salt)
    stream = b''.join(hashlib.sha256(key + nonce + i.to_bytes(8, 'big')).digest() for i in range(len(raw)//32+1))
    cipher = bytes(a ^ b for a,b in zip(raw,stream))
    return salt + nonce + hmac.new(key,nonce+cipher,hashlib.sha256).digest() + cipher


def test_vault_migrate_and_tamper(tmp_path):
    path = tmp_path/'vault'/'alice.bin'
    path.parent.mkdir()
    path.write_bytes(legacy_blob('phrase', {'named': {'token': 'sensitive'}}))
    assert vault.unlock(tmp_path,'alice','phrase')['named']['token'] == 'sensitive'
    assert path.read_bytes().startswith(vault.MAGIC)
    old = path.read_bytes()
    assert not vault.put(tmp_path,'alice','wrong',{'email':'x@y.com'})['ok']
    assert path.read_bytes() == old
    with pytest.raises(ValueError):
        vault.decrypt('phrase', old[:-1]+bytes([old[-1]^1]))
    with pytest.raises(ValueError):
        vault.decrypt('wrong', old)


@pytest.mark.parametrize('platform,tail', [('win32','SimkoSI'),('darwin','Library/Application Support/SimkoSI'),('linux','SimkoSI')])
def test_data_paths(monkeypatch, tmp_path, platform, tail):
    monkeypatch.delenv('PODCODER_STATE_DIR',raising=False)
    monkeypatch.delenv('SIMKOSI_DATA_DIR',raising=False)
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'Local'))
    monkeypatch.setenv('XDG_DATA_HOME',str(tmp_path/'xdg'))
    monkeypatch.setattr(sys,'platform',platform)
    assert platform_paths.data_dir().as_posix().endswith(tail)


def test_keychain_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules,'keyring', None)
    assert vault.keychain_passphrase('alice',create=True) == ''


@pytest.mark.parametrize('port', [465, 587])
def test_smtp_tls(monkeypatch, port):
    import smtp_transport
    seen = []
    class SMTP:
        def __init__(self, host, p, **kwargs):
            assert p == port
            if port == 465:
                assert 'context' in kwargs
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def ehlo(self): seen.append('ehlo')
        def starttls(self,**kwargs): seen.append('tls')
        def login(self,*args): seen.append('login')
        def send_message(self,*args): seen.append('send')
    monkeypatch.setenv('SMTP_HOST','smtp.invalid')
    monkeypatch.setenv('SMTP_FROM','sender@example.invalid')
    monkeypatch.setenv('SMTP_USER','user')
    monkeypatch.setenv('SMTP_PORT',str(port))
    monkeypatch.setattr(smtp_transport.smtplib,'SMTP',SMTP)
    monkeypatch.setattr(smtp_transport.smtplib,'SMTP_SSL',SMTP)
    assert smtp_transport.send('recipient@example.invalid','title','body') == 'smtp'
    assert seen[-1] == 'send'
    if port == 587:
        assert seen.index('tls') < seen.index('login')


def test_oidc_provider_and_no_email_linking(monkeypatch, tmp_path):
    import desktop_oidc
    monkeypatch.delenv('GOOGLE_CLIENT_ID',raising=False)
    assert not desktop_oidc.begin(tmp_path)['ok']
    assert not desktop_oidc.providers()['apple']['enabled']
    a = desktop_oidc.auth_accounts.signin_oidc(tmp_path,'google',{'sub':'one','email':'a@b.com'})
    b = desktop_oidc.auth_accounts.signin_oidc(tmp_path,'google',{'sub':'two','email':'a@b.com'})
    assert a['email'] != b['email']


def test_sync_refuses_wrong_project(monkeypatch, tmp_path):
    import offline_sync
    monkeypatch.setenv('SIMKO_MEMORY_SYNC','1')
    monkeypatch.setenv('SUPABASE_URL','https://nexkymqahpkvzzlvivfi.supabase.co')
    assert not offline_sync.sync_memories(tmp_path,'alice',opener=lambda *a,**k:pytest.fail('network'))['ok']


def test_memory_conflict_is_lossless(tmp_path):
    import memories
    row = {'id':'same','user_id':'alice','text':'one','type':'fact','categories':[]}
    assert memories.merge_remote(tmp_path,'alice',[row]) == 1
    row['text'] = 'two'
    assert memories.merge_remote(tmp_path,'alice',[row]) == 1
    assert memories.merge_remote(tmp_path,'alice',[row]) == 0
    assert {m['text'] for m in memories.recall(tmp_path,'alice')['memories']} == {'one','two'}


@pytest.mark.parametrize('platform', ['darwin','linux','win32'])
def test_notification_platform(monkeypatch, platform):
    import notify
    import subprocess
    monkeypatch.setenv('SIMKO_NOTIFICATIONS','1')
    monkeypatch.setattr(sys,'platform',platform)
    monkeypatch.setitem(sys.modules,'plyer',None)
    seen = []
    monkeypatch.setattr(subprocess,'run',lambda args,**kwargs: seen.append(args))
    assert notify.desktop('quoted " title','body') == ('unavailable' if platform == 'win32' else 'desktop')
    if platform == 'darwin':
        assert seen[0][-2:] == ['quoted " title','body']
    elif platform == 'linux':
        assert seen[0][0] == 'notify-send'


def test_search_and_image_mocked(monkeypatch, tmp_path):
    import xai_client
    import base64
    monkeypatch.setenv('SIMKO_PAID_API_ENABLED','1')
    monkeypatch.setattr(xai_client,'api_key', lambda:'fake-test-key')
    requests = []
    class Response:
        def __init__(self,doc): self.doc = doc
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self,*args): return json.dumps(self.doc).encode()
    def open_url(req,**kwargs):
        body = json.loads(req.data)
        requests.append((req.full_url,body))
        if req.full_url.endswith('/responses'):
            return Response({'output':[{'type':'message','content':[{'type':'output_text','text':'Answer','annotations':[{'type':'url_citation','url':'https://example.com','title':'Source'}]}]}]})
        return Response({'data':[{'b64_json':base64.b64encode(b'\x89PNG\r\n\x1a\ntest').decode()}]})
    assert xai_client.web_search('question',opener=open_url)['sources'][0]['url'] == 'https://example.com'
    image = xai_client.image_from_prompt(tmp_path,'draw',opener=open_url)
    assert image['ok'] and (tmp_path/'gallery'/image['name']).exists()
    assert all('video' not in u and 'video' not in json.dumps(b) for u,b in requests)
    monkeypatch.delenv('SIMKO_PAID_API_ENABLED')
    assert not xai_client.web_search('question',opener=lambda *a,**k:pytest.fail('network'))['ok']


def test_agents_concurrent_and_bus(monkeypatch):
    import multi_agents
    import threading
    import time
    monkeypatch.setenv('SIMKO_AGENTS','1')
    monkeypatch.setenv('SIMKO_PAID_API_ENABLED','1')
    barrier = threading.Barrier(2)
    calls = []
    lock = threading.Lock()
    def complete(messages):
        with lock:
            calls.append(messages)
        if 'Peer notes' not in messages[-1]['content']:
            barrier.wait(timeout=2)
        return {'ok':True,'text':'contribution'}
    group = multi_agents.start('alice',['A','B'],'task',complete=complete)
    for _ in range(100):
        status = multi_agents.status('alice',group['id'])
        if status['status'] != 'running': break
        time.sleep(.01)
    assert status['status'] == 'done'
    assert len(calls) == 4
    assert sum('Peer notes' in m[-1]['content'] for m in calls) == 2
    assert not multi_agents.status('bob',group['id'])['ok']


def test_browser_allowlist_and_submits():
    import browser_driver
    public = lambda *a,**k:[(0,0,0,'',('93.184.216.34',443))]
    local = lambda *a,**k:[(0,0,0,'',('127.0.0.1',443))]
    assert browser_driver.allowed('https://example.com/page',{'example.com'},resolver=public)
    assert not browser_driver.allowed('https://example.com/login',{'example.com'},resolver=public)
    assert not browser_driver.allowed('https://example.com',{'example.com'},resolver=local)
    assert not browser_driver.allowed('https://evil.com',{'example.com'},resolver=public)
    assert not browser_driver.submit()['ok']


def test_platform_auth_and_default_flags(monkeypatch,tmp_path):
    import platform_api
    for flag in platform_api.FLAGS:
        monkeypatch.delenv('SIMKO_'+flag.upper(),raising=False)
    assert not any(platform_api.flags().values())
    assert platform_api.handle('POST','/api/platform/usage',{},tmp_path)[0] == 403
    monkeypatch.setenv('SIMKO_PLATFORM_UI','1')
    assert platform_api.handle('POST','/api/platform/search',{},tmp_path)[0] == 401


def test_templates_and_escaped_report(tmp_path):
    import local_exports
    export = local_exports.export_template(tmp_path,'Pair',[{'name':'A','instructions':'help'}])
    assert local_exports.import_template(tmp_path,export['content'])['ok']
    doc = json.loads(export['content'])
    doc['api_key']='must-not-import'
    with pytest.raises(ValueError): local_exports.import_template(tmp_path,json.dumps(doc))
    report = local_exports.report(tmp_path,'alice','<title>','<script>alert(1)</script>')
    assert '<script>' not in report['content']
    assert Path(report['path']).is_file()


def test_usage_atomic_paywall(monkeypatch,tmp_path):
    import usage_ledger
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setenv('SIMKO_PAYWALL','1')
    monkeypatch.setenv('SIMKO_FREE_REQUESTS','3')
    monkeypatch.delenv('SIMKO_ENTITLEMENT_JWT',raising=False)
    # Initialize schema before contention; real callers do this lazily too.
    usage_ledger.snapshot(tmp_path,'alice')
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(lambda _:usage_ledger.reserve(tmp_path,'alice','search'),range(6)))
    assert sum(r['ok'] for r in rows)==3
    assert usage_ledger.snapshot(tmp_path,'alice')['remaining']==0
    assert usage_ledger.snapshot(tmp_path,'bob')['used']==0


def test_family_team_roles(tmp_path):
    import family_team
    team = family_team.create(tmp_path,'alice','Family')['id']
    assert not family_team.set_member(tmp_path,'bob',team,'bob','adult')['ok']
    assert family_team.set_member(tmp_path,'alice',team,'bob','child')['ok']
    assert family_team.allowed(tmp_path,'bob',team,'read')
    assert not family_team.allowed(tmp_path,'bob',team,'manage')
    assert not family_team.set_member(tmp_path,'alice',team,'alice','child')['ok']


def test_connector_vault_and_read_only(monkeypatch,tmp_path):
    import connector_oauth
    monkeypatch.setenv('SIMKO_CONNECTORS','1')
    vault.put_oauth(tmp_path,'alice','pass','github',{'access_token':'not-a-real-token'})
    seen = []
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self,*args): return b'[{"id":1,"full_name":"test/repo","html_url":"https://github.com/test/repo","private":false}]'
    def opener(req,**kwargs):
        seen.append(req)
        assert req.get_method()=='GET'
        return Response()
    data=connector_oauth.read(tmp_path,'alice','pass','github',opener=opener)
    assert data['ok'] and data['data'][0]['name']=='test/repo'
    assert seen[0].full_url.startswith('https://api.github.com/')
    assert 'not-a-real-token' not in json.dumps(data)


def test_call_disabled_and_one_time_consent(monkeypatch):
    import phone_calls
    from decimal import Decimal
    monkeypatch.delenv('SIMKO_CALLS',raising=False)
    request = phone_calls.CallRequest('+15555550123',1,Decimal('1'),'Test only')
    assert not phone_calls.prepare('alice',request)['ok']
    seen = []
    class FakeProvider:
        def estimate(self,request): return Decimal('.05')
        def dial(self,request): seen.append(request); return 'fake-call'
        def hangup(self,ident): pass
    phone_calls.register('test',FakeProvider())
    monkeypatch.setenv('SIMKO_CALLS','1')
    monkeypatch.setenv('SIMKO_CALL_PROVIDER','test')
    prepared = phone_calls.prepare('alice',request)
    assert not phone_calls.confirm('bob',prepared['approval_ticket'],owner_confirmed=True)['ok']
    assert phone_calls.confirm('alice',prepared['approval_ticket'],owner_confirmed=True)['ok']
    assert not phone_calls.confirm('alice',prepared['approval_ticket'],owner_confirmed=True)['ok']
    assert len(seen)==1


def test_bundle_config_snapshots():
    root = Path(__file__).resolve().parents[2]/'desktop-wrapper'
    conf=json.loads((root/'src-tauri/tauri.conf.json').read_text())
    assert {'app','dmg','nsis','appimage'} <= set(conf['bundle']['targets'])
    assert conf['bundle']['windows']['certificateThumbprint'] is None
    package=json.loads((root/'package.json').read_text())
    assert 'universal-apple-darwin' in package['scripts']['build:mac:universal']


@pytest.mark.parametrize('backend_module', ['keyring.backends.Windows','keyring.backends.macOS','keyring.backends.SecretService'])
def test_native_keychain_remembers_fallback(monkeypatch,tmp_path,backend_module):
    import types
    backend = type('NativeBackend',(),{'__module__':backend_module})()
    values = {}
    fake = types.SimpleNamespace(get_keyring=lambda:backend,
        get_password=lambda service,user:values.get((service,user)),
        set_password=lambda service,user,value:values.__setitem__((service,user),value))
    monkeypatch.setitem(sys.modules,'keyring',fake)
    assert vault.put_named(tmp_path,'alice','original-phrase','api','test-value')['ok']
    assert vault.remember_in_keychain(tmp_path,'alice','original-phrase')['ok']
    assert vault.unlock(tmp_path,'alice')['named']['api']=='test-value'
    # Native keychain failure does not invalidate the passphrase fallback.
    monkeypatch.setitem(sys.modules,'keyring',None)
    assert vault.unlock(tmp_path,'alice','original-phrase')['named']['api']=='test-value'
    assert not vault.put_named(tmp_path,'alice','wrong','api','overwrite')['ok']


def test_oidc_pkce_loopback_and_state(monkeypatch,tmp_path):
    import desktop_oidc
    import urllib.request
    from urllib.parse import urlparse,parse_qs,urlencode
    monkeypatch.setenv('GOOGLE_CLIENT_ID','desktop-client')
    monkeypatch.setattr(desktop_oidc,'open_auth_browser',lambda url:True)
    opened = desktop_oidc.begin(tmp_path)
    query = parse_qs(urlparse(opened['url']).query)
    assert query['code_challenge_method']==['S256']
    callback = query['redirect_uri'][0]
    with pytest.raises(urllib.error.HTTPError):
        urllib.request.urlopen(callback+'?code=test&state=wrong')
    assert desktop_oidc.poll(opened['ticket'])['pending']
    observed = {}
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self,*args): return b'{"id_token":"signed-test-token"}'
        def readline(self,*args): return b''
    def token_open(req,**kwargs):
        fields=parse_qs(req.data.decode())
        challenge=__import__('base64').urlsafe_b64encode(hashlib.sha256(fields['code_verifier'][0].encode()).digest()).rstrip(b'=').decode()
        assert challenge==query['code_challenge'][0]
        observed.update(fields)
        return Response()
    monkeypatch.setattr(desktop_oidc,'urlopen',token_open)
    monkeypatch.setattr(desktop_oidc,'verify_id_token',lambda encoded,client,nonce:{'sub':'test-sub','email_verified':True})
    with urllib.request.urlopen(callback+'?'+urlencode({'code':'test','state':query['state'][0]})) as response:
        assert response.status==200
    result = desktop_oidc.poll(opened['ticket'])
    assert result['ok'] and result['token']
    assert not desktop_oidc.poll(opened['ticket'])['ok']
    assert observed['grant_type']==['authorization_code']


def test_oidc_signature_audience_nonce(monkeypatch):
    jwt = pytest.importorskip('jwt')
    import desktop_oidc
    import time
    from types import SimpleNamespace
    from cryptography.hazmat.primitives.asymmetric import rsa
    private = rsa.generate_private_key(public_exponent=65537,key_size=2048)
    class JWKS:
        def __init__(self,*args): pass
        def get_signing_key_from_jwt(self,token): return SimpleNamespace(key=private.public_key())
    monkeypatch.setattr(jwt,'PyJWKClient',JWKS)
    claims={'sub':'test','iss':'https://accounts.google.com','aud':'desktop','iat':int(time.time()),'exp':int(time.time())+60,'nonce':'nonce'}
    encoded=jwt.encode(claims,private,algorithm='RS256')
    assert desktop_oidc.verify_id_token(encoded,'desktop','nonce')['sub']=='test'
    with pytest.raises(ValueError): desktop_oidc.verify_id_token(encoded,'desktop','wrong')
    with pytest.raises(jwt.InvalidAudienceError): desktop_oidc.verify_id_token(encoded,'wrong','nonce')


def test_sync_upload_pull_and_failure_retention(monkeypatch,tmp_path):
    import offline_sync
    for key,value in {'SIMKO_MEMORY_SYNC':'1','SUPABASE_URL':'https://wxvjajecvklfjxppawdx.supabase.co',
        'SUPABASE_ANON_KEY':'fake-public-key','SUPABASE_ACCESS_TOKEN':'fake-user-jwt','SIMKO_SYNC_LOCAL_USER':'alice'}.items():
        monkeypatch.setenv(key,value)
    record={'id':'one','user_id':'alice','text':'offline fact','type':'fact','categories':[]}
    offline_sync.note(tmp_path,'podcoder_memories',record)
    seen=[]
    class Response:
        def __init__(self,doc): self.doc=doc
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self,*args): return json.dumps(self.doc).encode()
    def opener(req,**kwargs):
        assert req.full_url.startswith('https://wxvjajecvklfjxppawdx.supabase.co/')
        seen.append(req)
        if req.full_url.endswith('/auth/v1/user'):
            return Response({'id':'00000000-0000-0000-0000-000000000001'})
        if req.get_method()=='POST':
            assert json.loads(req.data)['payload']==record
            return Response(None)
        return Response([{'payload':record}])
    result=offline_sync.sync_memories(tmp_path,'alice',opener=opener)
    assert result['ok'] and result['uploaded']==1 and result['pulled']==1
    assert not offline_sync._load(tmp_path)
    offline_sync.note(tmp_path,'podcoder_memories',record)
    def failing(req,**kwargs):
        if req.full_url.endswith('/auth/v1/user'): return opener(req,**kwargs)
        raise OSError('offline')
    assert not offline_sync.sync_memories(tmp_path,'alice',opener=failing)['ok']
    assert len(offline_sync._load(tmp_path))==1


def test_platform_http_csrf_and_export(monkeypatch,tmp_path):
    import importlib.util
    import threading
    import urllib.request
    import auth_accounts
    monkeypatch.setenv('SIMKO_PLATFORM_UI','1')
    monkeypatch.setenv('PODCODER_STATE_DIR',str(tmp_path))
    spec=importlib.util.spec_from_file_location('platform_http_server',Path(__file__).resolve().parents[1]/'local/server.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    server=module.make_server(0)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    token=auth_accounts.signin_oidc(tmp_path,'google',{'sub':'http-test'})['token']
    url=f'http://127.0.0.1:{server.server_port}/api/platform/templates/export'
    data=json.dumps({'token':token,'name':'Pair','agents':[{'name':'A','instructions':'help'}]}).encode()
    try:
        for headers in ({'Origin':'https://evil.invalid'},{'Host':'evil.invalid'}):
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(urllib.request.Request(url,data=data,headers={'Content-Type':'application/json',**headers}))
            assert error.value.code==403
        with urllib.request.urlopen(urllib.request.Request(url,data=data,headers={'Content-Type':'application/json'})) as response:
            assert json.load(response)['ok']
    finally:
        server.shutdown()
        server.server_close()


def test_per_account_lab_setting(tmp_path):
    import user_settings
    import auth_accounts
    import platform_api
    assert not user_settings.get_feature_flags(tmp_path,'alice')['desktop_lab']
    assert user_settings.set_feature_flag(tmp_path,'alice','desktop_lab',True)['ok']
    assert not user_settings.get_feature_flags(tmp_path,'bob')['desktop_lab']


def test_vault_account_paths_do_not_collide(tmp_path):
    assert vault._file(tmp_path,'a+b@example.com') != vault._file(tmp_path,'ab@example.com')
    assert vault._file(tmp_path,'../../outside').parent == tmp_path/'vault'
    folder=tmp_path/'vault'
    folder.mkdir()
    legacy=folder/'abexample.com.bin'
    legacy.write_bytes(legacy_blob('pass',{'named':{'api':'legacy-value'}}))
    assert vault.reveal_named(tmp_path,'a+b@example.com','pass','api')['value']=='legacy-value'
    assert vault._file(tmp_path,'a+b@example.com').exists()
    assert not legacy.exists()
    assert not vault.reveal_named(tmp_path,'ab@example.com','pass','api')['ok']


def test_vault_preserves_existing_fields_and_windows_names(tmp_path):
    assert vault.put(tmp_path,'alice','pass',{'ssn':'test-only'})['ok']
    assert vault.put(tmp_path,'alice','pass',{'email':'test@example.invalid'})['ok']
    assert vault.reveal(tmp_path,'alice','pass')['secrets']['ssn']=='test-only'
    for user in ['CON','con','con.txt','nul','lpt1','Alice','name.']:
        assert vault._file(tmp_path,user).name.startswith('account-')
    assert vault._file(tmp_path,'Alice') != vault._file(tmp_path,'alice')


def test_apple_supabase_pkce_roundtrip(monkeypatch,tmp_path):
    import desktop_oidc
    import urllib.request
    from urllib.parse import urlparse,parse_qs
    for key,value in {'SIMKO_APPLE_SUPABASE':'1','SUPABASE_URL':'https://wxvjajecvklfjxppawdx.supabase.co',
        'SUPABASE_ANON_KEY':'test-anon','APPLE_CLIENT_ID':'test-services-id'}.items():
        monkeypatch.setenv(key,value)
    monkeypatch.setattr(desktop_oidc,'open_auth_browser',lambda url:True)
    opened=desktop_oidc.begin(tmp_path,'apple')
    assert opened['ok']
    query=parse_qs(urlparse(opened['url']).query)
    callback=query['redirect_to'][0]
    assert query['provider']==['apple'] and query['code_challenge_method']==['s256']
    class Response:
        def __init__(self,doc): self.doc=doc
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self,*args): return json.dumps(self.doc).encode()
    def opener(req,**kwargs):
        assert req.full_url.startswith('https://wxvjajecvklfjxppawdx.supabase.co/auth/v1/')
        if req.get_method()=='POST':
            body=json.loads(req.data)
            challenge=__import__('base64').urlsafe_b64encode(hashlib.sha256(body['code_verifier'].encode()).digest()).rstrip(b'=').decode()
            assert challenge==query['code_challenge'][0]
            return Response({'access_token':'fake-session-never-persisted'})
        return Response({'id':'00000000-0000-0000-0000-000000000001','identities':[{'provider':'apple'}]})
    monkeypatch.setattr(desktop_oidc,'urlopen',opener)
    with urllib.request.urlopen(callback+'?code=fake-code') as response: assert response.status==200
    result=desktop_oidc.poll(opened['ticket'])
    assert result['ok'] and result['email'].startswith('apple:')
    assert 'fake-session-never-persisted' not in (tmp_path/'auth/accounts.json').read_text()
    monkeypatch.setenv('SUPABASE_URL','https://nexkymqahpkvzzlvivfi.supabase.co')
    assert not desktop_oidc.providers()['apple']['enabled']
