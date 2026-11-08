"""Optional ephemeral Playwright reader. No user profile, credentials, or login.

Reads never write. Interactive actions use owner-bound, expiring, single-use
approvals. Only simple non-sensitive HTML forms are supported; no login or payment.
"""
import ipaddress
import os
import socket
from urllib.parse import urlparse


def allowed(url, domains, *, resolver=socket.getaddrinfo):
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or '').lower()
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None,443):
            return False
        if host not in domains or any(word in parsed.path.lower() for word in ('login','signin','sign-in','oauth','checkout','logout','delete')):
            return False
        addresses = resolver(host,443,type=socket.SOCK_STREAM)
        return bool(addresses) and all(ipaddress.ip_address(info[4][0]).is_global for info in addresses)
    except (ValueError,OSError):
        return False


def read(url):
    if os.environ.get('SIMKO_BROWSER') != '1':
        return {'ok':False,'error':'browser driving disabled'}
    domains = {d.strip().lower() for d in os.environ.get('SIMKO_BROWSER_DOMAINS','').split(',') if d.strip()}
    if not allowed(url, domains):
        return {'ok':False,'error':'URL not allowlisted or unsafe'}
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {'ok':False,'error':'install optional playwright and Chromium first'}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            # No scripts: prevents hidden forms, JS writes, and page-driven login workflows.
            context = browser.new_context(java_script_enabled=False, service_workers='block',accept_downloads=False)
            def route_request(route):
                req = route.request
                if req.method not in ('GET','HEAD') or not allowed(req.url,domains):
                    route.abort()
                else:
                    route.continue_()
            context.route('**/*',route_request)
            page = context.new_page()
            page.goto(url,wait_until='domcontentloaded',timeout=20000)
            if page.locator('input[type=password]').count():
                return {'ok':False,'error':'login page blocked'}
            return {'ok':True,'url':page.url,'title':page.title(),'text':page.locator('body').inner_text()[:30000],
                    'read_only':True,'forms':'blocked in read mode; use prepare/confirm for an explicit per-action approval'}
    except Exception:
        return {'ok':False,'error':'browser unavailable or navigation blocked'}
    finally:
        try:
            browser.close()
        except Exception:
            pass

# Process-local tickets: restart cancels every pending approval.
import copy
import secrets
import threading
import time
from urllib.parse import urljoin, parse_qsl

_PENDING = {}
_LOCK = threading.Lock()
_PRIVATE = ('password', 'passwd', 'token', 'secret', 'card', 'credit', 'cvc', 'cvv',
            'ssn', 'otp', 'phone', 'email', 'address', 'payment', 'auth')


def _domains():
    return {d.strip().lower() for d in os.environ.get('SIMKO_BROWSER_DOMAINS', '').split(',') if d.strip()}


def prepare(owner='', url='', fields=None, *, form_index=0, operation='submit'):
    """Return a confirmation preview only. No navigation or writes before consent."""
    if os.environ.get('SIMKO_BROWSER') != '1':
        return {'ok': False, 'error': 'browser driving disabled'}
    fields = fields or {}
    if (not owner or operation not in ('fill', 'submit') or type(form_index) is not int
            or not 0 <= form_index <= 20 or not allowed(url, _domains())
            or not isinstance(fields, dict) or not 1 <= len(fields) <= 30):
        return {'ok': False, 'error': 'invalid or unsafe browser action'}
    for name, value in fields.items():
        if (not isinstance(name, str) or not name or len(name) > 100
                or any(word in name.lower() for word in _PRIVATE)
                or not isinstance(value, str) or len(value) > 4000):
            return {'ok': False, 'error': 'sensitive or invalid field; use a dedicated secure workflow'}
    action = {'url': url, 'fields': copy.deepcopy(fields), 'form_index': form_index, 'operation': operation}
    with _LOCK:
        now = time.monotonic()
        for ticket in list(_PENDING):
            if _PENDING[ticket]['expires'] <= now:
                del _PENDING[ticket]
        if len(_PENDING) >= 100:
            return {'ok': False, 'error': 'too many pending approvals'}
        ticket = secrets.token_urlsafe(32)
        _PENDING[ticket] = {'owner': owner, 'expires': now + 120, 'action': action}
    return {'ok': True, 'approval_ticket': ticket, 'expires_in': 120,
            'confirmation': copy.deepcopy(action),
            'warning': 'Confirm this exact action and field values. Submission may publish externally. No private values.'}


def submit(owner='', ticket='', *, owner_confirmed=False):
    """Confirmation accepts only a ticket, never replacement action fields."""
    if os.environ.get('SIMKO_BROWSER') != '1':
        return {'ok': False, 'error': 'browser driving disabled'}
    with _LOCK:
        pending = _PENDING.get(ticket)
        if not pending or pending['owner'] != owner:
            return {'ok': False, 'error': 'approval unavailable'}
        if owner_confirmed is not True or pending['expires'] <= time.monotonic():
            _PENDING.pop(ticket, None)
            return {'ok': False, 'error': 'explicit unexpired confirmation required'}
        action = _PENDING.pop(ticket)['action']
    try:
        return _interactive(action)
    except Exception:
        return {'ok': False, 'error': 'browser action blocked or unavailable; approval consumed'}


def _interactive(action):
    from playwright.sync_api import sync_playwright
    domains = _domains()
    url = action['url']
    if not allowed(url, domains):
        raise ValueError('unsafe target')
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(java_script_enabled=False, service_workers='block', accept_downloads=False)
            target, payload, sent = None, None, False
            def route_request(route):
                nonlocal sent
                req = route.request
                if not allowed(req.url, domains):
                    return route.abort()
                if req.method in ('GET', 'HEAD'):
                    return route.abort() if sent else route.continue_()
                if (not sent and target and req.method == 'POST' and req.url == target
                        and req.is_navigation_request() and req.frame == page.main_frame
                        and req.headers.get('content-type', '').startswith('application/x-www-form-urlencoded')
                        and sorted(parse_qsl(req.post_data or '', keep_blank_values=True)) == sorted(payload)):
                    sent = True
                    return route.continue_()
                return route.abort()
            context.route('**/*', route_request)
            page = context.new_page()
            page.goto(url, wait_until='domcontentloaded', timeout=20000)
            if page.url != url or page.locator('input[type=password],input[autocomplete="one-time-code"]').count():
                raise ValueError('redirect or login')
            form = page.locator('form').nth(action['form_index'])
            meta = form.evaluate("""f => ({action:f.action,method:f.method,enctype:f.enctype,
                controls:Array.from(f.elements).map(e=>({name:e.name,type:e.type,disabled:e.disabled,
                tag:e.tagName,autocomplete:e.autocomplete}))})""")
            target = urljoin(url, meta['action'])
            # This URL alone was approved; no hidden cross-path/domain recipient.
            if target != url or not allowed(target, domains) or meta['method'].lower() != 'post' or meta['enctype'] != 'application/x-www-form-urlencoded':
                raise ValueError('unapproved recipient or method')
            editable = [c for c in meta['controls'] if c['name']]
            if not editable or len({c['name'] for c in editable}) != len(editable):
                raise ValueError('duplicate or missing controls')
            for c in editable:
                if (c['disabled'] or c['type'] not in ('text', 'search', 'textarea')
                        or any(word in (c['name'] + ' ' + (c['autocomplete'] or '')).lower() for word in _PRIVATE)):
                    raise ValueError('unsupported or sensitive control')
            if set(action['fields']) != {c['name'] for c in editable}:
                raise ValueError('all fields must be approved')
            for c in editable:
                elements = form.locator('input,textarea')
                for i in range(elements.count()):
                    candidate = elements.nth(i)
                    if candidate.get_attribute('name') == c['name']:
                        candidate.fill(action['fields'][c['name']])
                        break
            if not form.evaluate('f => f.checkValidity()'):
                raise ValueError('invalid form')
            if action['operation'] == 'fill':
                return {'ok': True, 'filled': True, 'submitted': False, 'ephemeral': True}
            payload = [(c['name'], action['fields'][c['name']]) for c in editable]
            form.evaluate('f => HTMLFormElement.prototype.submit.call(f)')
            try:
                page.wait_for_load_state('networkidle', timeout=10000)
            except Exception:
                pass  # Block redirects; never retry an uncertain submission.
            return {'ok': sent, 'submitted': sent, 'retried': False,
                    'note': 'Request sent once; remote acceptance is not verified.'}
        finally:
            browser.close()
