"""Local family roles plus signed remote ACL snapshots; no external sharing."""
import json
import secrets
import sqlite3

PERMISSIONS = {'owner':{'read','use','manage'},'adult':{'read','use'},'child':{'read'}}


def _db(state):
    state.mkdir(parents=True,exist_ok=True)
    conn = sqlite3.connect(state/'teams.sqlite')
    conn.execute('create table if not exists teams (id text primary key, name text)')
    conn.execute('create table if not exists members (team text, member text, role text, primary key(team,member))')
    return conn


def create(state,owner,name):
    ident = secrets.token_hex(16)
    with _db(state) as conn:
        conn.execute('insert into teams values (?,?)',(ident,name[:100]))
        conn.execute('insert into members values (?,?,?)',(ident,owner,'owner'))
    return {'ok':True,'id':ident}


def allowed(state,actor,team,permission):
    with _db(state) as conn:
        row = conn.execute('select role from members where team=? and member=?',(team,actor)).fetchone()
    return bool(row and permission in PERMISSIONS.get(row[0],set()))


def set_member(state,actor,team,member,role):
    if role not in {'adult','child'} or not member or not allowed(state,actor,team,'manage'):
        return {'ok':False,'error':'only owners can add adults or children'}
    with _db(state) as conn:
        existing = conn.execute('select role from members where team=? and member=?',(team,member)).fetchone()
        if existing and existing[0] == 'owner':
            return {'ok':False,'error':'cannot demote owner'}
        conn.execute('insert into members values (?,?,?) on conflict(team,member) do update set role=excluded.role',(team,member,role))
    return {'ok':True}


def members(state,actor,team):
    if not allowed(state,actor,team,'read'):
        return {'ok':False,'error':'team access denied'}
    with _db(state) as conn:
        rows = conn.execute('select member,role from members where team=?',(team,)).fetchall()
    return {'ok':True,'members':[{'member':m,'role':r} for m,r in rows]}


# Remote authority is separate from local membership: importing JSON alone can
# never grant permissions. No invitations/messages/network requests are sent.
def _remote_db(state):
    state.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(state/'teams.sqlite', timeout=10)
    conn.execute('create table if not exists remote_acl (team text primary key, revision integer, token text)')
    conn.execute('create table if not exists team_resources (seq integer primary key autoincrement, team text, resource text, actor text, content text)')
    return conn


def _verify_remote(encoded):
    import os
    import jwt
    key = os.environ.get('SIMKO_TEAM_PUBLIC_KEY', '')
    if not key or not isinstance(encoded, str) or len(encoded) > 100000:
        raise ValueError('signed permission snapshot required')
    doc = jwt.decode(encoded, key, algorithms=['RS256'], audience='simko-team', issuer='https://simkosi.com',
                     options={'require': ['exp', 'iat', 'iss', 'aud', 'team', 'revision', 'members', 'resources']})
    if (not isinstance(doc['team'], str) or not doc['team'].startswith('remote:') or len(doc['team']) > 100
            or type(doc['revision']) is not int or doc['revision'] < 1
            or not isinstance(doc['members'], dict) or not 1 <= len(doc['members']) <= 100
            or not isinstance(doc['resources'], dict) or len(doc['resources']) > 100):
        raise ValueError('invalid permission snapshot')
    if not all(isinstance(m, str) and m and r in PERMISSIONS for m, r in doc['members'].items()):
        raise ValueError('invalid membership')
    if list(doc['members'].values()).count('owner') != 1:
        raise ValueError('one remote owner required')
    for resource, acl in doc['resources'].items():
        if (not isinstance(resource, str) or not resource or len(resource) > 100 or not isinstance(acl, dict)
                or set(acl) - {'read', 'use'}):
            raise ValueError('invalid resource ACL')
        for roles in acl.values():
            if not isinstance(roles, list) or any(role not in PERMISSIONS for role in roles):
                raise ValueError('invalid resource role')
    return doc


def import_permissions(state, actor, encoded):
    try:
        doc = _verify_remote(encoded)
        if actor not in doc['members']:
            raise ValueError('not a member')
        with _remote_db(state) as conn:
            conn.execute('begin immediate')
            old = conn.execute('select revision from remote_acl where team=?', (doc['team'],)).fetchone()
            if old and doc['revision'] <= old[0]:
                raise ValueError('stale revision')
            conn.execute('insert into remote_acl values (?,?,?) on conflict(team) do update set revision=excluded.revision,token=excluded.token',
                         (doc['team'], doc['revision'], encoded))
        return {'ok': True, 'team': doc['team'], 'revision': doc['revision']}
    except Exception:
        return {'ok': False, 'error': 'permission signature, membership, expiry or revision rejected'}


def _snapshot_allows(doc, actor, resource, permission):
    role = doc.get('members', {}).get(actor)
    return (permission in ('read', 'use') and permission in PERMISSIONS.get(role, set())
            and role in doc.get('resources', {}).get(resource, {}).get(permission, []))


def remote_allowed(state, actor, team, resource, permission):
    with _remote_db(state) as conn:
        row = conn.execute('select token from remote_acl where team=?', (team,)).fetchone()
    try:
        return bool(row and _snapshot_allows(_verify_remote(row[0]), actor, resource, permission))
    except Exception:
        return False


def resource(state, actor, team, name, *, content=None):
    """Local ACL enforcement; append-only content, no remote transport.

    Check and access share one transaction so an ACL update cannot race a write.
    Offline revocation remains bounded by the signed snapshot's expiry.
    """
    permission = 'read' if content is None else 'use'
    if content is not None and (not isinstance(content, str) or len(content) > 100000):
        return {'ok': False, 'error': 'invalid resource content'}
    with _remote_db(state) as conn:
        conn.execute('begin immediate')
        acl = conn.execute('select token from remote_acl where team=?', (team,)).fetchone()
        try:
            permitted = acl and _snapshot_allows(_verify_remote(acl[0]), actor, name, permission)
        except Exception:
            permitted = False
        if not permitted:
            return {'ok': False, 'error': 'team resource access denied'}
        if content is not None:
            conn.execute('insert into team_resources(team,resource,actor,content) values (?,?,?,?)', (team, name, actor, content))
            return {'ok': True, 'saved_locally': True}
        row = conn.execute('select content from team_resources where team=? and resource=? order by seq desc limit 1', (team, name)).fetchone()
    return {'ok': True, 'content': row[0] if row else None, 'local_cache_only': True}
