"""Atomic per-account local quota ledger. Not a billing authority.

Paid entitlement must be signed by the web backend; local files cannot grant paid
access. A device owner can modify their own app, so server-side enforcement is
still required before a commercial launch.
"""
import os
import sqlite3
from datetime import datetime, timezone


def _connect(state):
    state.mkdir(parents=True,exist_ok=True)
    conn = sqlite3.connect(state/'usage.sqlite',timeout=10)
    conn.execute('create table if not exists usage (owner text, day text, capability text, units integer, primary key(owner,day,capability))')
    return conn


def paid(owner):
    key = os.environ.get('SIMKO_ENTITLEMENT_PUBLIC_KEY')
    token = os.environ.get('SIMKO_ENTITLEMENT_JWT')
    if not key or not token:
        return False
    try:
        import jwt
        doc = jwt.decode(token,key,algorithms=['RS256'],audience='simko-desktop',issuer='https://simkosi.com',options={'require':['exp','sub','aud','iss']})
        return doc['sub'] == owner and doc.get('plan') == 'paid' and doc.get('sandbox', False) is False
    except Exception:
        return False


def snapshot(state,owner):
    day = datetime.now(timezone.utc).date().isoformat()
    with _connect(state) as conn:
        rows = conn.execute('select capability,units from usage where owner=? and day=?',(owner,day)).fetchall()
    limit = max(0,int(os.environ.get('SIMKO_FREE_REQUESTS','50')))
    used = sum(row[1] for row in rows)
    return {'ok':True,'day_utc':day,'used':used,'remaining':max(0,limit-used),'limit':limit,
            'paid':paid(owner),'enforced':os.environ.get('SIMKO_PAYWALL')=='1','capabilities':dict(rows),
            'checkout':'https://simkosi.com/checkout','billing_authority':'website; not this local counter'}


def reserve(state,owner,capability,units=1):
    if not 1 <= units <= 20:
        return {'ok':False,'error':'invalid request units'}
    day = datetime.now(timezone.utc).date().isoformat()
    limit = max(0,int(os.environ.get('SIMKO_FREE_REQUESTS','50')))
    with _connect(state) as conn:
        conn.execute('begin immediate')
        used = conn.execute('select coalesce(sum(units),0) from usage where owner=? and day=?',(owner,day)).fetchone()[0]
        if os.environ.get('SIMKO_PAYWALL') == '1' and used+units > limit and not paid(owner):
            return {'ok':False,'error':'free quota reached','checkout':'https://simkosi.com/checkout'}
        conn.execute('insert into usage values (?,?,?,?) on conflict(owner,day,capability) do update set units=units+excluded.units',
                     (owner,day,capability,units))
    return {'ok':True,'reserved':units}
