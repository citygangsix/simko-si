"""Finish items 2, 3, 5, 6, 9 offline. Fake SMTP/Supabase/Storage transports only."""
import base64
import io
import json
import threading
import time
from urllib.error import HTTPError

import pytest

UID = '00000000-0000-0000-0000-00000000000a'
PASS = 'correct horse battery staple'


@pytest.fixture(autouse=True)
def offline_env(monkeypatch):
    for name in ('SMTP_HOST', 'SMTP_FROM', 'SMTP_USER', 'SMTP_PASSWORD', 'SMTP_PORT', 'SIMKO_DEV_INBOX_ECHO',
                 'SIMKO_CLOUD_BACKUP', 'SIMKO_MEMORY_SYNC', 'SIMKO_MEMORY_SYNC_AUTO', 'SUPABASE_REFRESH_TOKEN'):
        monkeypatch.delenv(name, raising=False)


# ------------------------------------------------------------------ item 2

def test_confirm_and_reset_end_to_end_offline_dev_inbox(tmp_path):
    import auth_accounts as a
    code, made = a.signup(tmp_path, 'ada@example.com', 'first-password')
    assert code == 200 and made['delivered'] == 'file' and made['dev_token']
    raw = (tmp_path/'auth'/'accounts.json').read_text()
    assert made['dev_token'] not in raw, 'mail tokens are stored only as digests'
    inbox = a.dev_inbox(tmp_path, 'ADA@example.com')
    assert inbox[-1]['kind'] == 'confirm' and inbox[-1]['token'] == made['dev_token']
    # Resend supersedes the first code.
    code, again = a.resend_confirmation(tmp_path, made['token'])
    assert code == 200 and again['dev_token'] != made['dev_token']
    assert a.confirm_email(tmp_path, made['dev_token'])[0] == 400
    assert a.confirm_email(tmp_path, again['dev_token'])[1]['email_confirmed']
    assert a.me(tmp_path, made['token'])[1]['email_confirmed']
    assert a.resend_confirmation(tmp_path, made['token'])[1]['delivered'] == 'none'
    # Reset: unknown and known emails return the same response shape.
    unknown = a.request_reset(tmp_path, 'nobody@example.com')[1]
    first = a.request_reset(tmp_path, 'ada@example.com')[1]
    second = a.request_reset(tmp_path, 'ada@example.com')[1]
    assert set(unknown) == set(first) and 'email' not in first
    assert a.reset_password(tmp_path, first['dev_token'], 'brand-new-pass')[0] == 400  # superseded
    assert a.reset_password(tmp_path, second['dev_token'], 'brand-new-pass')[1]['reset']
    assert a.reset_password(tmp_path, second['dev_token'], 'another-pass-1')[0] == 400  # single use
    assert a.email_for_token(tmp_path, made['token']) == ''  # sessions revoked
    assert a.signin(tmp_path, 'ada@example.com', 'brand-new-pass')[1]['ok']
    assert not a.signin(tmp_path, 'ada@example.com', 'first-password')[1]['ok']


def test_mail_tokens_expire_and_digest_cannot_be_replayed(tmp_path, monkeypatch):
    import auth_accounts as a
    a.signup(tmp_path, 'bo@example.com', 'first-password')
    reset = a.request_reset(tmp_path, 'bo@example.com')[1]['dev_token']
    doc = json.loads((tmp_path/'auth'/'accounts.json').read_text())
    digest = next(iter(doc['reset_tokens']))
    assert a.reset_password(tmp_path, digest, 'brand-new-pass')[0] == 400
    real = time.time
    monkeypatch.setattr(a.time, 'time', lambda: real() + a.RESET_TTL_SECONDS + 5)
    assert a.reset_password(tmp_path, reset, 'brand-new-pass')[0] == 400


def test_legacy_plaintext_token_still_works_until_expiry(tmp_path):
    import auth_accounts as a
    a.signup(tmp_path, 'cy@example.com', 'first-password')
    path = tmp_path/'auth'/'accounts.json'
    doc = json.loads(path.read_text())
    doc['reset_tokens']['legacy-token'] = {'email': 'cy@example.com', 'created_at': a._now()}
    doc['reset_tokens']['old-token'] = {'email': 'cy@example.com', 'created_at': '2020-01-01T00:00:00Z'}
    path.write_text(json.dumps(doc))
    assert a.reset_password(tmp_path, 'old-token', 'brand-new-pass')[0] == 400
    assert a.reset_password(tmp_path, 'legacy-token', 'brand-new-pass')[0] == 200


def test_mail_throttle_and_echo_off(tmp_path, monkeypatch):
    import auth_accounts as a
    a.signup(tmp_path, 'di@example.com', 'first-password')
    tokens = [a.request_reset(tmp_path, 'di@example.com')[1]['dev_token'] for _ in range(6)]
    assert all(tokens[:4]) and tokens[-1] == ''  # signup counted; 5 per hour
    monkeypatch.setenv('SIMKO_DEV_INBOX_ECHO', '0')
    a.signup(tmp_path, 'ed@example.com', 'first-password')
    got = a.request_reset(tmp_path, 'ed@example.com')[1]
    assert got['dev_token'] == '' and a.dev_inbox(tmp_path, 'ed@example.com')[-1]['kind'] == 'reset'


class FakeSMTP:
    sent = []
    def __init__(self, host, port, **kwargs): self.port = port
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def ehlo(self): pass
    def starttls(self, **kw): pass
    def login(self, *a): pass
    def send_message(self, message): FakeSMTP.sent.append(message); return {}


def test_smtp_code_path_delivers_without_dev_inbox(tmp_path, monkeypatch):
    import auth_accounts as a
    import smtp_transport
    FakeSMTP.sent = []
    monkeypatch.setenv('SMTP_HOST', 'smtp.example.invalid')
    monkeypatch.setenv('SMTP_FROM', 'Simko SI <noreply@example.invalid>')
    monkeypatch.setattr(smtp_transport.smtplib, 'SMTP', FakeSMTP)
    code, made = a.signup(tmp_path, 'fi@example.com', 'first-password')
    assert made['delivered'] == 'smtp' and made['dev_token'] == ''
    assert not (tmp_path/'auth'/'dev-inbox.json').exists()
    body = FakeSMTP.sent[-1].get_content()
    token = body.split('\n\n')[1].strip()
    assert FakeSMTP.sent[-1]['To'] == 'fi@example.com' and FakeSMTP.sent[-1]['Message-ID']
    assert a.confirm_email(tmp_path, token)[1]['email_confirmed']
    a.request_reset(tmp_path, 'fi@example.com')
    reset = FakeSMTP.sent[-1].get_content().split('\n\n')[1].strip()
    assert 'password reset' in FakeSMTP.sent[-1]['Subject']
    assert a.reset_password(tmp_path, reset, 'brand-new-pass')[1]['reset']


def test_smtp_failure_and_header_injection(monkeypatch):
    import smtp_transport
    monkeypatch.setenv('SMTP_HOST', 'smtp.example.invalid')
    monkeypatch.setenv('SMTP_FROM', 'noreply@example.invalid')
    class Down(FakeSMTP):
        def __init__(self, *a, **k): raise OSError('connection refused by secret-host')
    monkeypatch.setattr(smtp_transport.smtplib, 'SMTP', Down)
    assert smtp_transport.send('a@example.com', 'hi', 'x') == 'error'
    assert smtp_transport.LAST_ERROR['kind'] == 'OSError'
    monkeypatch.setattr(smtp_transport.smtplib, 'SMTP', FakeSMTP)
    assert smtp_transport.send('a@example.com\r\nBcc: x@evil.invalid', 'hi', 'x') == 'error'
    assert smtp_transport.send('a@example.com', 'hi\r\nBcc: x@evil.invalid', 'x') == 'error'


def test_resend_confirmation_http_route(tmp_path):
    import auth_accounts as a
    import product_api
    token = a.signup(tmp_path, 'gi@example.com', 'first-password')[1]['token']
    code, out = product_api.try_handle('POST', '/api/auth', {'op': 'resend-confirmation', 'token': token}, tmp_path)
    assert code == 200 and out['dev_kind'] == 'confirm'
    assert product_api.try_handle('POST', '/api/auth', {'op': 'resend-confirmation', 'token': 'x'}, tmp_path)[0] == 401


# ------------------------------------------------------------------ item 3

class Resp:
    def __init__(self, doc): self.doc = doc
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def read(self, *a): return self.doc if isinstance(self.doc, bytes) else json.dumps(self.doc).encode()


def _sync_env(monkeypatch):
    for k, v in {'SIMKO_MEMORY_SYNC': '1', 'SUPABASE_URL': 'https://wxvjajecvklfjxppawdx.supabase.co',
                 'SUPABASE_ANON_KEY': 'fake-public-key', 'SUPABASE_ACCESS_TOKEN': 'expired-jwt',
                 'SIMKO_SYNC_LOCAL_USER': 'alice'}.items():
        monkeypatch.setenv(k, v)


def _http_error(url, code):
    return HTTPError(url, code, 'error', {}, io.BytesIO(b'{}'))


def test_corrupt_queue_is_quarantined_not_lost(tmp_path):
    import offline_sync
    (tmp_path/'sync-queue.json').write_text('{not json')
    offline_sync.note(tmp_path, 'podcoder_memories', {'id': 'x'})
    kept = list(tmp_path.glob('sync-queue.corrupt-*.json'))
    assert kept and kept[0].read_text() == '{not json'
    assert len(offline_sync._load(tmp_path)) == 1


def test_sync_refreshes_token_paginates_and_keeps_concurrent_notes(tmp_path, monkeypatch):
    import offline_sync
    _sync_env(monkeypatch)
    monkeypatch.setenv('SUPABASE_REFRESH_TOKEN', 'fake-refresh')
    monkeypatch.setattr(offline_sync, 'PAGE_SIZE', 2)
    for i in range(3):
        offline_sync.note(tmp_path, 'podcoder_memories', {'id': f'm{i}', 'user_id': 'alice', 'text': f'fact {i}', 'type': 'fact', 'categories': []})
    remote = [{'payload': {'id': f'r{i}', 'user_id': 'alice', 'text': f'remote {i}', 'type': 'fact', 'categories': []}} for i in range(5)]
    seen = {'refresh': 0, 'posts': 0, 'auth': []}
    def opener(req, timeout=None):
        url = req.full_url
        assert url.startswith('https://wxvjajecvklfjxppawdx.supabase.co/')
        auth = dict(req.header_items()).get('Authorization', '')
        if 'grant_type=refresh_token' in url:
            seen['refresh'] += 1
            return Resp({'access_token': 'fresh-jwt', 'refresh_token': 'fresh-refresh'})
        seen['auth'].append(auth)
        if auth != 'Bearer fresh-jwt':
            raise _http_error(url, 401)
        if url.endswith('/auth/v1/user'):
            return Resp({'id': UID})
        if req.get_method() == 'POST':
            seen['posts'] += 1
            if seen['posts'] == 1:  # a new note lands while the upload is in flight
                offline_sync.note(tmp_path, 'podcoder_memories', {'id': 'late', 'user_id': 'alice', 'text': 'late', 'type': 'fact', 'categories': []})
            return Resp(None)
        offset = int(url.split('offset=')[1].split('&')[0])
        return Resp(remote[offset:offset + 2])
    out = offline_sync.sync_memories(tmp_path, 'alice', opener=opener)
    assert out['ok'] and out['uploaded'] == 3 and out['pulled'] == 5, out
    assert seen['refresh'] == 1
    left = offline_sync._load(tmp_path)
    assert [r['record']['id'] for r in left] == ['late']
    assert 'fresh-jwt' not in json.dumps(offline_sync.status(tmp_path))
    assert offline_sync.sync_health(tmp_path)['memory']['failures'] == 0


def test_sync_partial_failure_backoff_and_single_flight(tmp_path, monkeypatch):
    import offline_sync
    _sync_env(monkeypatch)
    monkeypatch.setenv('SUPABASE_ACCESS_TOKEN', 'good-jwt')
    monkeypatch.setenv('SIMKO_MEMORY_SYNC_AUTO', '1')
    for i in range(3):
        offline_sync.note(tmp_path, 'podcoder_memories', {'id': f'm{i}', 'user_id': 'alice', 'text': f'f{i}', 'type': 'fact', 'categories': []})
    posts = []
    def flaky(req, timeout=None):
        if req.full_url.endswith('/auth/v1/user'):
            return Resp({'id': UID})
        if req.get_method() == 'POST':
            posts.append(1)
            if len(posts) == 2:
                raise OSError('offline')
            return Resp(None)
        return Resp([])
    out = offline_sync.sync_memories(tmp_path, 'alice', opener=flaky)
    assert not out['ok'] and out['uploaded'] == 1 and out['queued'] == 2
    health = offline_sync.sync_health(tmp_path)['memory']
    assert health['failures'] == 1 and health['next_attempt'] > time.time()
    assert offline_sync.maybe_sync(tmp_path, opener=flaky)['skipped'] == 'backoff'
    assert offline_sync._SYNC_LOCK.acquire(blocking=False)
    try:
        assert offline_sync.sync_memories(tmp_path, 'alice', opener=flaky)['error'] == 'sync already running'
    finally:
        offline_sync._SYNC_LOCK.release()
    out = offline_sync.maybe_sync(tmp_path, now=time.time() + 4000, opener=flaky)
    assert out['ok'] and not offline_sync._load(tmp_path)


def test_sync_refuses_other_project_even_with_session(tmp_path, monkeypatch):
    import offline_sync
    _sync_env(monkeypatch)
    monkeypatch.setenv('SUPABASE_URL', 'https://nexkymqahpkvzzlvivfi.supabase.co')
    with pytest.raises(PermissionError):
        offline_sync.SupabaseSession(lambda *a, **k: pytest.fail('network'))
    assert not offline_sync.sync_memories(tmp_path, 'alice', opener=lambda *a, **k: pytest.fail('network'))['ok']


# ------------------------------------------------------------------ item 5

def test_agents_owner_message_cancel_and_transcript(monkeypatch):
    import multi_agents
    monkeypatch.setenv('SIMKO_AGENTS', '1')
    monkeypatch.setenv('SIMKO_PAID_API_ENABLED', '1')
    gate = threading.Event()
    prompts = []
    def complete(messages):
        prompts.append(messages[1]['content'])
        gate.wait(5)
        return {'ok': True, 'text': 'note from ' + messages[0]['content'].split(',')[0][8:]}
    assert not multi_agents.start('alice', ['Owner'], 'x', complete=complete)['ok']
    started = multi_agents.start('alice', ['Ann', 'Ben'], 'plan the week', complete=complete)
    gid = started['id']
    assert not multi_agents.message('bob', gid, 'hi')['ok']
    assert not multi_agents.message('alice', gid, 'hi', 'Zed')['ok']
    assert multi_agents.message('alice', gid, 'prefer mornings', 'Ann')['ok']
    gate.set()
    for _ in range(100):
        st = multi_agents.status('alice', gid)
        if st['status'] == 'done':
            break
        time.sleep(0.05)
    assert st['status'] == 'done'
    assert any(m['sender'] == 'owner' and m['to'] == 'Ann' for m in st['messages'])
    assert any('prefer mornings' in p for p in prompts)  # Ann's review saw it
    assert not multi_agents.message('alice', gid, 'late')['ok']
    gate.clear()
    second = multi_agents.start('alice', ['Cy'], 'task', complete=complete)['id']
    assert not multi_agents.cancel('bob', second)['ok']
    assert multi_agents.cancel('alice', second)['ok']
    gate.set()
    for _ in range(100):
        st = multi_agents.status('alice', second)
        if st['status'] in ('cancelled', 'done'):
            break
        time.sleep(0.05)
    assert st['status'] == 'cancelled' and st['panes']['Cy']['status'] == 'cancelled'


# ------------------------------------------------------------------ item 6

def test_template_history_and_append_only_rollback(tmp_path):
    import local_exports
    def doc(name, text):
        return json.dumps({'format': 'simko-agent-template', 'version': 1, 'name': name,
                           'agents': [{'name': 'Ann', 'instructions': text}]})
    first = local_exports.apply_template(tmp_path, 'alice', doc('One', 'first'), owner_confirmed=True)
    local_exports.apply_template(tmp_path, 'alice', doc('Two', 'second'), owner_confirmed=True)
    local_exports.apply_template(tmp_path, 'bob', doc('Bob', 'bob'), owner_confirmed=True)
    history = local_exports.template_history(tmp_path, 'alice')['revisions']
    assert [r['name'] for r in history] == ['Two', 'One'] and history[0]['active']
    assert not local_exports.rollback_template(tmp_path, 'alice', first['id'])['ok']
    bob_id = local_exports.template_history(tmp_path, 'bob')['revisions'][0]['id']
    assert not local_exports.rollback_template(tmp_path, 'alice', bob_id, owner_confirmed=True)['ok']
    back = local_exports.rollback_template(tmp_path, 'alice', first['id'], owner_confirmed=True)
    assert back['ok'] and back['restored_from'] == first['id']
    assert local_exports.active_template(tmp_path, 'alice')['template']['name'] == 'One'
    assert len(local_exports.template_history(tmp_path, 'alice')['revisions']) == 3


# ------------------------------------------------------------------ item 9

@pytest.fixture
def backup_env(monkeypatch):
    monkeypatch.setenv('SIMKO_CLOUD_BACKUP', '1')
    monkeypatch.setenv('SIMKO_SYNC_LOCAL_USER', 'alice@example.com')


def _seed(state, owner='alice@example.com'):
    import memories
    import scheduler
    import sessions
    import user_settings
    import vault
    chat = sessions.create_session(state, owner, 'Plans')['session']
    sessions.append_message(state, owner, chat['id'], 'remember the dentist')
    memories.add_memory(state, owner, 'Likes espresso', 'preference')
    scheduler.create_routine(state, owner, 'Morning', 'cron', {'expr': '0 8 * * *'})
    user_settings.set_theme(state, owner, 'plain')
    vault.put_named(state, owner, 'vault-pass-123', 'note', 'opaque')
    return chat['id']


def test_backup_flag_off_does_nothing(tmp_path):
    import cloud_backup
    store = cloud_backup.FakeStorage()
    assert cloud_backup.create(tmp_path, 'alice@example.com', PASS, transport=store) == cloud_backup._disabled()
    assert not store.objects and not (tmp_path/'cloud-backup').exists()


def test_backup_round_trip_fresh_profile_restore(tmp_path, backup_env):
    import cloud_backup
    import memories
    import sessions
    import vault
    store = cloud_backup.FakeStorage(UID)
    src, dst = tmp_path/'pc1', tmp_path/'pc2'
    chat_id = _seed(src)
    made = cloud_backup.create(src, 'alice@example.com', PASS, transport=store, chunk_size=64)
    assert made['ok'] and made['uploaded'] and made['chunks'] > 1
    assert all(k.startswith(UID + '/') for k in store.objects)
    blob = b''.join(store.objects.values())
    for plain in (b'espresso', b'dentist', b'Morning', b'opaque', PASS.encode()):
        assert plain not in blob, 'only ciphertext is uploaded'
    listed = cloud_backup.list_backups(dst, 'alice@example.com', transport=store)
    assert listed['backups'][0]['backup_id'] == made['backup_id'] and listed['backups'][0]['complete']
    assert not cloud_backup.restore(dst, 'alice@example.com', made['backup_id'], PASS, transport=store)['ok']  # needs confirm
    out = cloud_backup.restore(dst, 'alice@example.com', made['backup_id'], PASS, transport=store, owner_confirmed=True)
    assert out['ok'] and out['applied'] and out['merge']['chats_added'] == 1 and out['merge']['vault'] == 'restored'
    assert sessions.get_session(dst, 'alice@example.com', chat_id)['session']['messages'][0]['text'] == 'remember the dentist'
    assert memories.recall(dst, 'alice@example.com')['memories'][0]['text'] == 'Likes espresso'
    assert vault.reveal_named(dst, 'alice@example.com', 'vault-pass-123', 'note')['value'] == 'opaque'
    again = cloud_backup.restore(dst, 'alice@example.com', made['backup_id'], PASS, transport=store, owner_confirmed=True)
    assert again['merge']['chats_added'] == 0 and again['merge']['memories_added'] == 0 and again['merge']['vault'] == 'unchanged'


def test_backup_wrong_passphrase_and_tamper_fail_closed(tmp_path, backup_env):
    import cloud_backup
    store = cloud_backup.FakeStorage(UID)
    _seed(tmp_path)
    made = cloud_backup.create(tmp_path, 'alice@example.com', PASS, transport=store, chunk_size=64)
    bid = made['backup_id']
    fresh = tmp_path/'fresh'
    bad = cloud_backup.restore(fresh, 'alice@example.com', bid, 'wrong passphrase!!', transport=store, owner_confirmed=True)
    assert not bad['ok'] and not bad['applied'] and not fresh.exists()
    chunk = f'{UID}/{bid}/chunk-00001.bin'
    original = store.objects[chunk]
    store.objects[chunk] = original[:-1] + bytes([original[-1] ^ 1])
    out = cloud_backup.verify(fresh, 'alice@example.com', bid, PASS, transport=store)
    assert not out['ok'] and 'integrity' in out['error']
    store.objects[chunk] = original
    manifest_key = f'{UID}/{bid}/manifest.json'
    manifest = json.loads(store.objects[manifest_key])
    manifest['chunk_count'] -= 1
    store.objects[manifest_key] = json.dumps(manifest).encode()
    assert not cloud_backup.verify(fresh, 'alice@example.com', bid, PASS, transport=store)['ok']
    assert not cloud_backup.verify(fresh, 'alice@example.com', '../etc', PASS, transport=store)['ok']
    assert cloud_backup.create(tmp_path, 'alice@example.com', 'short', transport=store)['error'].startswith('backup passphrase')


def test_backup_offline_queue_is_lossless_and_resumes(tmp_path, backup_env):
    import cloud_backup
    store = cloud_backup.FakeStorage(UID)
    _seed(tmp_path)
    store.offline = True
    first = cloud_backup.create(tmp_path, 'alice@example.com', PASS, transport=store, chunk_size=64)
    assert first['ok'] and first['queued'] and not first['uploaded']
    assert cloud_backup.pending(tmp_path, 'alice@example.com') == [first['backup_id']]
    # Offline restore can still use this device's queued copy.
    assert cloud_backup.verify(tmp_path, 'alice@example.com', first['backup_id'], PASS, transport=store)['ok']
    store.offline = False
    store.fail_uploads_after = 2
    partial = cloud_backup.flush(tmp_path, 'alice@example.com', transport=store)
    assert not partial['ok'] and partial['pending'] == [first['backup_id']]
    listed = cloud_backup.list_backups(tmp_path, 'alice@example.com', transport=store)
    assert listed['backups'] == [] or not listed['backups'][0]['complete']
    store.fail_uploads_after = None
    assert cloud_backup.maybe_flush(tmp_path, transport=store)['skipped'] == 'backoff'
    done = cloud_backup.maybe_flush(tmp_path, now=time.time() + 4000, transport=store)
    assert done['ok'] and done['completed'] == [first['backup_id']] and not done['pending']
    assert cloud_backup.list_backups(tmp_path, 'alice@example.com', transport=store)['backups'][0]['complete']
    assert cloud_backup.verify(tmp_path/'other', 'alice@example.com', first['backup_id'], PASS, transport=store)['ok']


def test_backup_restore_conflicts_keep_both_copies(tmp_path, backup_env):
    import cloud_backup
    import sessions
    import vault
    store = cloud_backup.FakeStorage(UID)
    chat_id = _seed(tmp_path)
    made = cloud_backup.create(tmp_path, 'alice@example.com', PASS, transport=store)
    time.sleep(1.1)
    sessions.append_message(tmp_path, 'alice@example.com', chat_id, 'newer local edit')
    vault.put_named(tmp_path, 'alice@example.com', 'vault-pass-123', 'note', 'changed')
    out = cloud_backup.restore(tmp_path, 'alice@example.com', made['backup_id'], PASS, transport=store, owner_confirmed=True)
    assert out['ok'] and out['pre_restore_snapshot']
    listing = sessions.list_sessions(tmp_path, 'alice@example.com')['sessions']
    assert len(listing) == 2 and any(s['id'].startswith(chat_id + '-restored-') for s in listing)
    current = sessions.get_session(tmp_path, 'alice@example.com', chat_id)['session']
    assert current['messages'][-1]['text'] == 'newer local edit'  # newer copy wins in place
    assert vault.reveal_named(tmp_path, 'alice@example.com', 'vault-pass-123', 'note')['value'] == 'changed'
    assert list((tmp_path/'vault').glob('*.restored-*')), 'backup vault copy kept beside local'


def test_backup_isolation_and_identity_mapping(tmp_path, backup_env, monkeypatch):
    import cloud_backup
    store = cloud_backup.FakeStorage(UID)
    _seed(tmp_path)
    _seed(tmp_path, 'bob@example.com')
    assert cloud_backup.flush(tmp_path, 'bob@example.com', transport=store)['error'] == 'local identity mapping required'
    made = cloud_backup.create(tmp_path, 'alice@example.com', PASS, transport=store)
    other = cloud_backup.FakeStorage('00000000-0000-0000-0000-00000000000b')
    other.objects = store.objects
    assert other.list(other.uid + '/') == []
    with pytest.raises(cloud_backup.StorageError):
        other.download(f'{UID}/{made["backup_id"]}/manifest.json')
    bundle = cloud_backup.collect(tmp_path, 'alice@example.com')
    assert all(c['user'] != 'bob@example.com' for c in bundle['sections']['chats'])


def test_supabase_storage_transport_shape_and_project_lock(tmp_path, backup_env, monkeypatch):
    import cloud_backup
    for k, v in {'SUPABASE_URL': 'https://wxvjajecvklfjxppawdx.supabase.co', 'SUPABASE_ANON_KEY': 'fake-public-key',
                 'SUPABASE_ACCESS_TOKEN': 'fake-user-jwt'}.items():
        monkeypatch.setenv(k, v)
    objects, calls = {}, []
    def opener(req, timeout=None):
        url, method = req.full_url, req.get_method()
        assert url.startswith('https://wxvjajecvklfjxppawdx.supabase.co/')
        headers = dict(req.header_items())
        assert headers['Authorization'] == 'Bearer fake-user-jwt' and 'service_role' not in json.dumps(headers)
        calls.append((method, url.split('.co', 1)[1]))
        if url.endswith('/auth/v1/user'):
            return Resp({'id': UID})
        if '/storage/v1/object/list/simko-backups' in url:
            prefix = json.loads(req.data)['prefix']
            names = sorted({k[len(prefix):].split('/')[0] for k in objects if k.startswith(prefix)}, reverse=True)
            return Resp([{'name': n, 'id': None} for n in names])
        if '/storage/v1/object/authenticated/simko-backups/' in url:
            return Resp(objects[url.split('/simko-backups/', 1)[1]])
        assert method == 'POST' and headers.get('X-upsert') == 'false'
        name = url.split('/storage/v1/object/simko-backups/', 1)[1]
        if name in objects:
            raise _http_error(url, 409)
        objects[name] = req.data
        return Resp({'Key': name})
    _seed(tmp_path)
    made = cloud_backup.create(tmp_path, 'alice@example.com', PASS, upload=False, chunk_size=64)
    store = cloud_backup.SupabaseStorage(opener)
    # Simulate a crash after the first chunk was accepted but before progress was saved.
    first = sorted((tmp_path/'cloud-backup'/'outbox').rglob('chunk-00000.bin'))[0]
    objects[f'{UID}/{made["backup_id"]}/chunk-00000.bin'] = first.read_bytes()
    assert cloud_backup.flush(tmp_path, 'alice@example.com', transport=store)['completed'] == [made['backup_id']]
    assert calls[-1][1].endswith('/manifest.json')  # manifest is the commit marker
    listed = cloud_backup.list_backups(tmp_path, 'alice@example.com', transport=store)
    assert listed['backups'][0]['complete']
    assert cloud_backup.verify(tmp_path/'new', 'alice@example.com', made['backup_id'], PASS, transport=store)['ok']
    monkeypatch.setenv('SUPABASE_URL', 'https://nexkymqahpkvzzlvivfi.supabase.co')
    with pytest.raises(PermissionError):
        cloud_backup.SupabaseStorage(opener)


def test_backup_api_routes_gated(tmp_path, monkeypatch):
    import auth_accounts
    import platform_api as api
    monkeypatch.setenv('SIMKO_PLATFORM_UI', '1')
    token = auth_accounts.signin_oidc(tmp_path, 'google', {'sub': 'backup-api'})['token']
    code, out = api.handle('POST', '/api/platform/backup/create', {'token': token, 'passphrase': PASS}, tmp_path)
    assert code == 200 and out['error'] == 'cloud backup disabled'
    assert api.handle('POST', '/api/platform/backup/status', {}, tmp_path)[0] == 401
    monkeypatch.setenv('SIMKO_CLOUD_BACKUP', '1')
    code, out = api.handle('POST', '/api/platform/backup/create', {'token': token, 'passphrase': PASS, 'upload': False}, tmp_path)
    assert out['ok'] and out['queued'] and PASS not in json.dumps(out)
    status = api.handle('POST', '/api/platform/backup/status', {'token': token}, tmp_path)[1]
    assert status['enabled'] and status['queued'] == [out['backup_id']] and status['project_ref'] == 'wxvjajecvklfjxppawdx'
    code, verified = api.handle('POST', '/api/platform/backup/verify', {'token': token, 'passphrase': PASS, 'backup_id': out['backup_id']}, tmp_path)
    assert verified['ok'] and verified['verified']
    assert not api.handle('POST', '/api/platform/backup/restore', {'token': token, 'passphrase': PASS, 'backup_id': out['backup_id']}, tmp_path)[1]['ok']


def test_sql_targets_private_bucket_with_owner_folder_policies():
    from pathlib import Path
    sql = (Path(__file__).resolve().parents[2]/'supabase'/'item9_backup_bucket.sql').read_text()
    assert "'simko-backups', 'simko-backups', false" in sql and 'set public = false' in sql
    assert sql.count('(storage.foldername(name))[1] = (select auth.uid())::text') == 3
    assert 'for update' not in sql and 'nexkymqahpkvzzlvivfi' in sql.split('\n')[1]


# ------------------------------------------------------------------ approved default-on features (2026-11-08)

def test_feature_defaults_turn_on_only_approved_and_respect_explicit_off():
    import feature_defaults
    env = {'SIMKO_AGENTS': '0'}
    on = feature_defaults.apply(env)
    assert not on['AGENTS'] and env['SIMKO_AGENTS'] == '0'
    for name in ('MEMORY_SYNC', 'PAID_API_ENABLED', 'ROUTINES', 'NOTIFICATIONS', 'MEMORY_SYNC_AUTO'):
        assert env['SIMKO_' + name] == '1'
    for name in feature_defaults.MUST_STAY_OFF:
        assert 'SIMKO_' + name not in env
    assert not set(feature_defaults.APPROVED_ON) & set(feature_defaults.MUST_STAY_OFF)


@pytest.fixture
def approved_on(monkeypatch):
    import feature_defaults
    import platform_api
    for flag in platform_api.FLAGS:
        monkeypatch.delenv('SIMKO_' + flag.upper(), raising=False)
    for name in feature_defaults.APPROVED_ON:
        monkeypatch.setenv('SIMKO_' + name, '1')


def test_enabled_features_work_by_api_without_lab_ui(tmp_path, monkeypatch, approved_on):
    import auth_accounts
    import platform_api as api
    import xai_client
    token = auth_accounts.signin_oidc(tmp_path, 'google', {'sub': 'enabled'})['token']
    assert not api.flags()['platform_ui']
    # Unapproved features stay unreachable.
    for route in ('browser/read', 'connectors', 'calls/status', 'checkout/create', 'backup/status', 'templates/apply'):
        assert api.handle('POST', '/api/platform/' + route, {'token': token}, tmp_path)[0] == 403
    # Paid calls still need per-action approval.
    assert api.handle('POST', '/api/platform/search', {'token': token, 'query': 'q'}, tmp_path)[0] == 403
    calls = []
    def fake_request(endpoint, payload, *, opener=None):
        calls.append((endpoint, payload))
        if endpoint == '/responses':
            assert payload['tools'] == [{'type': 'web_search'}]  # web only, never x_search
            return {'ok': True, 'payload': {'output': [{'content': [{'type': 'output_text', 'text': 'Answer',
                    'annotations': [{'url': 'https://example.com/a', 'title': 'A'}]}]}]}}
        return {'ok': True, 'payload': {'data': [{'b64_json': base64.b64encode(b'\x89PNG\r\n\x1a\n' + b'0' * 64).decode()}]}}
    monkeypatch.setattr(xai_client, '_desktop_request', fake_request)
    monkeypatch.setenv('PODCODER_STATE_DIR', str(tmp_path))
    code, found = api.handle('POST', '/api/platform/search', {'token': token, 'query': 'weather', 'approve_paid': True}, tmp_path)
    assert code == 200 and found['ok'] and found['sources'][0]['url'] == 'https://example.com/a'
    code, image = api.handle('POST', '/api/platform/image', {'token': token, 'prompt': 'a turtle', 'approve_paid': True}, tmp_path)
    assert code == 200, image
    assert [c[0] for c in calls] == ['/responses', '/images/generations']
    code, sync = api.handle('POST', '/api/platform/sync/status', {'token': token}, tmp_path)
    assert code == 200 and sync['ok']
    code, sync = api.handle('POST', '/api/platform/sync', {'token': token}, tmp_path)
    assert code == 200 and not sync['ok']  # no Supabase session configured -> fails closed, nothing lost


def test_enabled_agents_routines_memory_and_approval_card(tmp_path, monkeypatch, approved_on):
    import approvals
    import memories
    import multi_agents
    import scheduler
    import auth_accounts
    import platform_api as api
    from datetime import datetime
    # memory across sessions
    memories.add_memory(tmp_path, 'alice', 'Prefers short answers', 'preference', session_id='s-1')
    assert memories.recall(tmp_path, 'alice')['memories'][0]['text'] == 'Prefers short answers'
    # multi-agent run through the API route
    token = auth_accounts.signin_oidc(tmp_path, 'google', {'sub': 'agents-on'})['token']
    monkeypatch.setattr(multi_agents.xai_client, 'chat', lambda messages, timeout=60: {'ok': True, 'text': 'done'})
    code, started = api.handle('POST', '/api/platform/agents/start',
                               {'token': token, 'names': ['Ann', 'Ben'], 'task': 'plan', 'approve_paid': True}, tmp_path)
    assert code == 200 and started['ok'], started
    for _ in range(100):
        status = api.handle('POST', '/api/platform/agents/status', {'token': token, 'id': started['id']}, tmp_path)[1]
        if status['status'] == 'done':
            break
        time.sleep(0.05)
    assert status['status'] == 'done' and len(status['messages']) == 2
    # routine created and fired
    made = scheduler.create_routine(tmp_path, 'alice', 'Morning', 'cron', {'expr': '* * * * *', 'message': 'hi'})
    assert made['ok']
    fired = scheduler.tick(tmp_path, datetime.now().astimezone())
    assert len(fired['enqueued']) == 1
    stop = scheduler.start_background(tmp_path)
    assert not stop.is_set()
    stop.set()
    # approval card is created and must be confirmed with the exact word
    job = fired['enqueued'][0]
    card = approvals.request(tmp_path, job, 'send', 'Send the morning note')
    assert card['ok'] and card['status'] == 'needs_approval' and not card['approved']
    assert not approvals.confirm(tmp_path, job, 'send', 'yes')['approved']
    assert approvals.confirm(tmp_path, job, 'send', 'SEND')['approved']
