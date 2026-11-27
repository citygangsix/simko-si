"""Provider-agnostic call contract. No provider SDK/account or transport installed.

Call adapters must be separately configured after account, number, consent,
emergency-calling limitations and per-minute budget are approved by the owner.
"""
from dataclasses import dataclass
from decimal import Decimal
import os
import re
import secrets
import threading
import time
from typing import Protocol


@dataclass(frozen=True)
class CallRequest:
    destination: str
    max_minutes: int
    max_cost_usd: Decimal
    purpose: str


class Provider(Protocol):
    def estimate(self, request: CallRequest) -> Decimal: ...
    def dial(self, request: CallRequest) -> str: ...
    def hangup(self, call_id: str) -> None: ...


_PROVIDERS = {}
_APPROVALS = {}
_LOCK = threading.Lock()


def status():
    name = os.environ.get('SIMKO_CALL_PROVIDER','')
    return {'ok':True,'enabled':os.environ.get('SIMKO_CALLS')=='1' and name in _PROVIDERS,
            'provider_configured':name in _PROVIDERS,'calls_placed':0,
            'reason':'No built-in calling transport. Account, consent and per-minute budget require owner approval.'}


def register(name: str, provider: Provider):
    """Only application code can register adapters; no arbitrary URL or module import."""
    _PROVIDERS[name] = provider


def _valid(request):
    return (isinstance(request,CallRequest) and re.fullmatch(r'\+[1-9][0-9]{7,14}',request.destination)
            and 1 <= request.max_minutes <= 60 and Decimal('0') < request.max_cost_usd <= Decimal('100') and bool(request.purpose.strip()))


def prepare(owner, request):
    if not status()['enabled']:
        return {'ok':False,'error':'phone calls disabled or provider unavailable'}
    if not _valid(request):
        return {'ok':False,'error':'valid E.164 number, duration, purpose and budget required'}
    provider = _PROVIDERS[os.environ['SIMKO_CALL_PROVIDER']]
    estimate = provider.estimate(request)
    if estimate < 0 or estimate > request.max_cost_usd:
        return {'ok':False,'error':'estimated cost exceeds approved budget'}
    ticket = secrets.token_urlsafe(32)
    with _LOCK:
        for key in list(_APPROVALS):
            if _APPROVALS[key]['expires'] < time.time(): del _APPROVALS[key]
        _APPROVALS[ticket] = {'owner':owner,'request':request,'provider':provider,'expires':time.time()+120}
    return {'ok':True,'approval_ticket':ticket,'destination':request.destination,'max_minutes':request.max_minutes,
            'estimated_usd':str(estimate),'max_cost_usd':str(request.max_cost_usd),'requires_owner_confirmation':True}


def confirm(owner,ticket,*,owner_confirmed=False):
    if not owner_confirmed or not status()['enabled']:
        return {'ok':False,'error':'owner confirmation and enabled provider required'}
    with _LOCK:
        row = _APPROVALS.get(ticket)
        if not row or row['owner']!=owner or row['expires']<time.time():
            return {'ok':False,'error':'approval expired or not found'}
        del _APPROVALS[ticket]
    # Adapters MUST enforce provider-side max duration and budget; never retry a dial.
    try:
        ident = row['provider'].dial(row['request'])
        return {'ok':True,'call_id':ident}
    except Exception:
        return {'ok':False,'error':'call provider unavailable; not retried'}
