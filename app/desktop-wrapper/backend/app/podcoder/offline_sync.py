#!/usr/bin/env python3
"""Offline-first sync stub. Local JSON is the cache. No network and no live DDL."""
from __future__ import annotations

import json
import os
from pathlib import Path

FORBIDDEN_PROJECT_REF = "nexkymqahpkvzzlvivfi"
PODCODER_PROJECT_REF = "wxvjajecvklfjxppawdx"


def _queue_path(state: Path) -> Path:
    return state / "sync-queue.json"


def _load(state: Path) -> list:
    """Read the queue. A corrupt file is quarantined (never overwritten) before reuse."""
    path = _queue_path(state)
    if not path.is_file():
        return []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc, list):
            raise ValueError("queue must be a list")
    except Exception:
        _quarantine(path)
        return []
    import hashlib
    for index, row in enumerate(doc):
        if isinstance(row, dict) and not row.get("qid"):
            # Stable id for legacy rows so acknowledgement can remove exactly them.
            row["qid"] = "legacy-" + hashlib.sha256((str(index) + json.dumps(row, sort_keys=True)).encode()).hexdigest()[:24]
    return [row for row in doc if isinstance(row, dict)]


def _quarantine(path: Path) -> None:
    import time
    target = path.with_name(f"{path.stem}.corrupt-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{os.getpid()}.json")
    try:
        path.replace(target)
    except OSError:
        pass


def cloud_url() -> str:
    return (os.environ.get("SUPABASE_URL") or "").strip()


def cloud_configured() -> bool:
    url = cloud_url()
    key = (os.environ.get("SUPABASE_ANON_KEY") or "").strip()
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return bool(key and parsed.scheme == "https" and parsed.netloc == PODCODER_PROJECT_REF + ".supabase.co" and parsed.path in ("", "/"))


def refused_project() -> bool:
    return FORBIDDEN_PROJECT_REF in cloud_url()


def note(state: Path, table: str, record: dict) -> dict:
    """Remember a local change. Does not call Supabase."""
    with _QUEUE_LOCK:
        rows = _load(state)
        import secrets
        rows.append({"qid": secrets.token_hex(12), "table": table, "record": record})
        _save_queue(state, rows)
    return status(state)


def status(state: Path) -> dict:
    """Report the local cache. Blank env stays fully offline."""
    if refused_project():
        return {
            "ok": False,
            "mode": "offline",
            "cloud": False,
            "configured": False,
            "refused": FORBIDDEN_PROJECT_REF,
            "error": "This pack does not sync to the Artemis/Omega project.",
            "queued": len(_load(state)),
            "cache": "local-json",
            "vast_calls": 0,
            "destroyed": False,
        }
    configured = cloud_configured()
    url = cloud_url()
    project_ref = PODCODER_PROJECT_REF if PODCODER_PROJECT_REF in url else ""
    return {
        "ok": True,
        "mode": "queued" if configured else "offline",
        "cloud": False,
        "configured": configured,
        "project_ref": project_ref,
        "anon_key_set": bool((os.environ.get("SUPABASE_ANON_KEY") or "").strip()) and not refused_project(),
        "queued": len(_load(state)),
        "cache": "local-json",
        "health": sync_health(state),
        "vast_calls": 0,
        "destroyed": False,
    }

# Sync is explicitly opt-in. Never try a different project or use a service-role key.
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlparse, urlencode, quote
from urllib.request import Request, urlopen
_QUEUE_LOCK = threading.RLock()
_SYNC_LOCK = threading.Lock()
_TOKENS_LOCK = threading.Lock()
_TOKENS: dict = {}
PAGE_SIZE = 500
MAX_BACKOFF_SECONDS = 3600


def _save_queue(state, rows):
    state.mkdir(parents=True, exist_ok=True)
    path = _queue_path(state)
    tmp = path.with_suffix('.tmp')
    with open(tmp, 'w', encoding='utf-8') as handle:
        handle.write(json.dumps(rows, indent=2) + '\n')
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)


def _health_path(state: Path) -> Path:
    return state / 'sync-status.json'


def sync_health(state: Path) -> dict:
    try:
        doc = json.loads(_health_path(state).read_text(encoding='utf-8'))
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


def _record(state: Path, ok: bool, error: str = '', *, kind: str = 'memory') -> dict:
    doc = sync_health(state)
    row = doc.get(kind) if isinstance(doc.get(kind), dict) else {}
    now = time.time()
    row['last_attempt'] = now
    if ok:
        row.update(last_success=now, failures=0, last_error='', next_attempt=0)
    else:
        failures = int(row.get('failures') or 0) + 1
        row.update(failures=failures, last_error=error[:120],
                   next_attempt=now + min(MAX_BACKOFF_SECONDS, 30 * 2 ** min(failures, 7)))
    doc[kind] = row
    state.mkdir(parents=True, exist_ok=True)
    tmp = _health_path(state).with_suffix('.tmp')
    tmp.write_text(json.dumps(doc, indent=2) + '\n', encoding='utf-8')
    tmp.replace(_health_path(state))
    return row


class SupabaseSession:
    """Authenticated user session on the approved project only.

    Uses the public anon key plus a signed-in user's JWT. If the access token
    expires (HTTP 401) and a refresh token is configured, it refreshes once and
    retries; refreshed tokens stay in process memory, never on disk or in logs.
    """

    def __init__(self, opener=None):
        url = cloud_url().rstrip('/')
        parsed = urlparse(url)
        if refused_project() or parsed.scheme != 'https' or parsed.netloc != PODCODER_PROJECT_REF + '.supabase.co' or parsed.path not in ('', '/'):
            raise PermissionError('only the approved Supabase project is allowed')
        self.url = url
        self.key = os.environ.get('SUPABASE_ANON_KEY', '')
        with _TOKENS_LOCK:
            env_access = os.environ.get('SUPABASE_ACCESS_TOKEN', '')
            if _TOKENS.get('env_access') != env_access:
                _TOKENS.clear()
                _TOKENS.update(env_access=env_access, access=env_access,
                               refresh=os.environ.get('SUPABASE_REFRESH_TOKEN', ''))
        if not self.key or not _TOKENS.get('access'):
            raise PermissionError('public key and signed-in user token required')
        self.open = opener or urlopen
        self.refreshed = False

    def _refresh(self) -> bool:
        with _TOKENS_LOCK:
            refresh = _TOKENS.get('refresh')
        if not refresh or self.refreshed:
            return False
        self.refreshed = True
        req = Request(self.url + '/auth/v1/token?grant_type=refresh_token', method='POST',
                      headers={'apikey': self.key, 'Content-Type': 'application/json'},
                      data=json.dumps({'refresh_token': refresh}).encode())
        try:
            with self.open(req, timeout=20) as response:
                doc = json.loads(response.read() or b'{}')
        except Exception:
            return False
        if not isinstance(doc, dict) or not doc.get('access_token'):
            return False
        with _TOKENS_LOCK:
            _TOKENS['access'] = str(doc['access_token'])
            if doc.get('refresh_token'):
                _TOKENS['refresh'] = str(doc['refresh_token'])
        return True

    def raw(self, path, method='GET', data=None, extra=None, timeout=20):
        for attempt in (0, 1):
            with _TOKENS_LOCK:
                access = _TOKENS.get('access', '')
            headers = {'apikey': self.key, 'Authorization': 'Bearer ' + access, **(extra or {})}
            req = Request(self.url + path, method=method, headers=headers, data=data)
            try:
                with self.open(req, timeout=timeout) as response:
                    return response.read()
            except HTTPError as exc:
                if exc.code == 401 and attempt == 0 and self._refresh():
                    continue
                raise

    def json(self, path, method='GET', data=None, extra=None):
        body = json.dumps(data).encode() if data is not None else None
        raw = self.raw(path, method, body, {'Content-Type': 'application/json', **(extra or {})})
        return json.loads(raw) if raw else None

    def user_id(self) -> str:
        import uuid
        identity = self.json('/auth/v1/user')
        owner = str((identity or {}).get('id') or '')
        uuid.UUID(owner)
        return owner


def _memory_identity(local_user, record):
    import hashlib
    return hashlib.sha256((local_user + ':' + record['id'] + ':' + json.dumps(record, sort_keys=True)).encode()).hexdigest()


def sync_memories(state: Path, local_user: str, *, opener=None) -> dict:
    """Append-only, lossless synchronization; keep both versions on a collision.

    Requires an authenticated user's JWT, not just the public anon key. Local
    account mapping is configured explicitly; RLS independently enforces ownership.
    Queue entries are removed only after an acknowledged upload, and the network
    is never touched while holding the queue lock (new notes keep landing).
    One sync runs at a time; a corrupt queue is quarantined, not discarded.
    """
    if os.environ.get('SIMKO_MEMORY_SYNC') != '1':
        return {'ok': False, 'error': 'sync disabled', 'queued': len(_load(state))}
    url = cloud_url().rstrip('/')
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.netloc != PODCODER_PROJECT_REF + '.supabase.co' or parsed.path not in ('','/'):
        return {'ok': False, 'error': 'only the approved Supabase project is allowed'}
    if not local_user or local_user != os.environ.get('SIMKO_SYNC_LOCAL_USER'):
        return {'ok': False, 'error': 'local identity mapping required'}
    try:
        session = SupabaseSession(opener)
    except PermissionError as exc:
        return {'ok': False, 'error': str(exc)}
    if not _SYNC_LOCK.acquire(blocking=False):
        return {'ok': False, 'error': 'sync already running', 'queued': len(_load(state))}
    uploaded = 0
    try:
        try:
            owner = session.user_id()
        except Exception:
            _record(state, False, 'identity unavailable')
            return {'ok':False,'error':'sync unavailable; local data retained','uploaded':0,'queued':len(_load(state))}
        with _QUEUE_LOCK:
            pending = [row for row in _load(state)
                       if row.get('table') == 'podcoder_memories' and (row.get('record') or {}).get('user_id') == local_user]
        acked, failed = set(), False
        for row in pending:
            record = row.get('record', {})
            try:
                if not record.get('id'):
                    raise ValueError('record id required')
                # Ignore duplicate IDs instead of silently overwriting a second device's edit.
                session.json('/rest/v1/simko_memory_sync?on_conflict=owner_id,id', 'POST',
                    {'owner_id':owner,'id':_memory_identity(local_user, record),'local_user':local_user,'payload':record},
                    {'Prefer':'resolution=ignore-duplicates,return=minimal'})
                acked.add(row['qid'])
                uploaded += 1
            except Exception:
                failed = True
                break  # keep order; remaining rows retry later
        with _QUEUE_LOCK:
            retained = [row for row in _load(state) if row.get('qid') not in acked]
            _save_queue(state, retained)
        if failed:
            _record(state, False, 'upload failed')
            return {'ok':False,'error':'sync unavailable; changes retained','uploaded':uploaded,'queued':len(retained)}
        payloads, offset = [], 0
        while True:
            page = session.json('/rest/v1/simko_memory_sync?' + urlencode({
                'owner_id':'eq.'+owner,'local_user':'eq.'+local_user,'select':'payload',
                'order':'id.asc','limit':str(PAGE_SIZE),'offset':str(offset)}))
            page = page if isinstance(page, list) else []
            payloads.extend(row.get('payload') for row in page if isinstance(row, dict) and isinstance(row.get('payload'), dict))
            if len(page) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
        import memories
        pulled = memories.merge_remote(state, local_user, payloads)
        _record(state, True)
        return {'ok':True,'uploaded':uploaded,'pulled':pulled,'queued':len(_load(state))}
    except Exception:
        _record(state, False, 'sync failed')
        return {'ok':False,'error':'sync unavailable; local data retained','uploaded':uploaded,'queued':len(_load(state))}
    finally:
        _SYNC_LOCK.release()


def maybe_sync(state: Path, *, now: float | None = None, opener=None) -> dict:
    """Background tick: honours exponential backoff after failures. Opt-in only."""
    if os.environ.get('SIMKO_MEMORY_SYNC') != '1' or os.environ.get('SIMKO_MEMORY_SYNC_AUTO') != '1':
        return {'ok': True, 'skipped': 'disabled'}
    local_user = os.environ.get('SIMKO_SYNC_LOCAL_USER', '')
    row = sync_health(state).get('memory') or {}
    moment = time.time() if now is None else now
    if moment < float(row.get('next_attempt') or 0):
        return {'ok': True, 'skipped': 'backoff', 'next_attempt': row.get('next_attempt')}
    if not any(r.get('table') == 'podcoder_memories' for r in _load(state)) and row.get('last_success') and moment - float(row['last_success']) < 300:
        return {'ok': True, 'skipped': 'idle'}
    return sync_memories(state, local_user, opener=opener)
