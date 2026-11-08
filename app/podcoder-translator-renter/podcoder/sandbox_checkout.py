"""Offline Square-shaped checkout contract. No SDK, keys, sockets or live adapter.

Sandbox receipts/entitlements NEVER grant production access. A separately deployed
payment authority, verified Square events, keys and owner approval are launch gates.
This module deliberately cannot contact even Square's real sandbox service.
"""
import os
import secrets
import sqlite3
import threading
import time

# Demonstration price only, not an approved commercial price.
PRICE = {'amount': 1000, 'currency': 'USD'}


class MockSquareSandbox:
    environment = 'mock-sandbox'

    def __init__(self):
        self._lock = threading.Lock()
        self._payments = {}

    def create(self, order_id, owner):
        with self._lock:
            self._payments.setdefault(order_id, {'id': order_id, 'owner': owner,
                'status': 'PENDING', 'amount_money': dict(PRICE), 'environment': self.environment})
            return dict(self._payments[order_id])

    def retrieve(self, order_id):
        with self._lock:
            return dict(self._payments[order_id])

    def complete_for_test(self, order_id):
        """Fixture hook only; intentionally not exposed through the HTTP API."""
        with self._lock:
            self._payments[order_id]['status'] = 'COMPLETED'


MOCK = MockSquareSandbox()


def _db(state):
    state.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(state/'sandbox_checkout.sqlite', timeout=10)
    conn.execute('create table if not exists orders (id text primary key, owner text, request text, status text, unique(owner,request))')
    return conn


def _enabled():
    return os.environ.get('SIMKO_PAYWALL') == '1'


def create(state, owner, request_id, *, owner_confirmed=False, provider=MOCK):
    if not _enabled():
        return {'ok': False, 'error': 'paywall disabled'}
    if (owner_confirmed is not True or not owner or not isinstance(request_id, str)
            or not 8 <= len(request_id) <= 100 or type(provider) is not MockSquareSandbox):
        return {'ok': False, 'error': 'explicit mock checkout confirmation and idempotency key required'}
    with _db(state) as conn:
        conn.execute('begin immediate')
        row = conn.execute('select id from orders where owner=? and request=?', (owner, request_id)).fetchone()
        ident = row[0] if row else secrets.token_hex(16)
        # Mock provider supports stable idempotency, including a local retry.
        payment = provider.create(ident, owner)
        if not row:
            conn.execute('insert into orders values (?,?,?,?)', (ident, owner, request_id, 'PENDING'))
    return {'ok': True, 'id': ident, 'status': payment['status'], 'amount_money': dict(PRICE),
            'environment': 'mock-sandbox', 'charged': False, 'checkout_url': None,
            'note': 'Offline simulation only. No payment link or actual charge.'}


def reconcile(state, owner, ident, *, provider=MOCK):
    if not _enabled() or type(provider) is not MockSquareSandbox:
        return {'ok': False, 'error': 'mock checkout disabled'}
    with _db(state) as conn:
        row = conn.execute('select owner from orders where id=?', (ident,)).fetchone()
        if not row or row[0] != owner:
            return {'ok': False, 'error': 'checkout unavailable'}
        try:
            payment = provider.retrieve(ident)
        except KeyError:
            return {'ok': False, 'error': 'mock session lost; no entitlement granted'}
        if (payment.get('owner') != owner or payment.get('id') != ident
                or payment.get('environment') != 'mock-sandbox' or payment.get('amount_money') != PRICE
                or payment.get('status') not in ('PENDING', 'COMPLETED', 'CANCELED', 'FAILED')):
            return {'ok': False, 'error': 'payment verification rejected'}
        conn.execute('update orders set status=? where id=?', (payment['status'], ident))
    return {'ok': True, 'id': ident, 'status': payment['status'], 'sandbox_paid': payment['status'] == 'COMPLETED',
            'paid': False, 'charged': False}


def issue_test_entitlement(state, owner, ident, private_key, *, provider=MOCK):
    """Authority-side fixture helper. Key is injected by tests, never provisioned.

    No HTTP route exposes this issuer. Sandbox claims are audience/issuer isolated.
    """
    result = reconcile(state, owner, ident, provider=provider)
    if not result.get('sandbox_paid'):
        return {'ok': False, 'error': 'completed verified mock receipt required'}
    import jwt
    now = int(time.time())
    token = jwt.encode({'iss': 'simko-square-mock', 'aud': 'simko-desktop-sandbox', 'sub': owner,
                        'iat': now, 'exp': now + 300, 'plan': 'sandbox_paid', 'sandbox': True,
                        'order': ident}, private_key, algorithm='RS256')
    return {'ok': True, 'token': token, 'production_access': False}


def verify_test_entitlement(owner, encoded, public_key):
    if not _enabled():
        return False
    try:
        import jwt
        doc = jwt.decode(encoded, public_key, algorithms=['RS256'], audience='simko-desktop-sandbox',
                         issuer='simko-square-mock', options={'require': ['sub', 'exp', 'iat', 'plan', 'sandbox', 'order']})
        return doc['sub'] == owner and doc['plan'] == 'sandbox_paid' and doc['sandbox'] is True
    except Exception:
        return False
