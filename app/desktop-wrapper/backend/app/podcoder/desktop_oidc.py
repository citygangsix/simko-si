"""Google desktop OIDC/PKCE with ephemeral loopback callback.

Apple uses the approved Supabase project as its HTTPS OAuth broker, followed
by a local PKCE callback. No provider registrations or configuration are automatic.
"""
import base64
import hashlib
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import Request, urlopen
import auth_accounts

_GOOGLE = 'https://accounts.google.com/o/oauth2/v2/auth'
_TOKEN = 'https://oauth2.googleapis.com/token'
_JWKS = 'https://www.googleapis.com/oauth2/v3/certs'
_PENDING = {}
_LOCK = threading.Lock()


def providers():
    return {
        'google': {'enabled': bool(os.environ.get('GOOGLE_CLIENT_ID')), 'client_id_set': bool(os.environ.get('GOOGLE_CLIENT_ID'))},
        'apple': {'enabled': _apple_configured(), 'client_id_set': bool(os.environ.get('APPLE_CLIENT_ID')),
                  'reason': 'Uses the approved Supabase HTTPS callback; enable only after Apple provider and desktop redirect allowlist are configured.'},
    }


def verify_id_token(encoded, client_id, nonce):
    import jwt
    key = jwt.PyJWKClient(_JWKS).get_signing_key_from_jwt(encoded)
    claims = jwt.decode(encoded, key.key, algorithms=['RS256'], audience=client_id,
                        issuer='https://accounts.google.com', options={'require': ['exp','iat','sub','iss','aud','nonce']})
    if not secrets.compare_digest(str(claims.get('nonce', '')), nonce):
        raise ValueError('nonce mismatch')
    return claims


def begin(state_dir, provider='google'):
    if provider == 'apple':
        return _begin_apple(state_dir)
    if provider != 'google' or not providers()['google']['enabled']:
        return {'ok': False, 'error': 'provider not configured or unsupported'}
    client = os.environ['GOOGLE_CLIENT_ID']
    verifier, nonce, state = secrets.token_urlsafe(48), secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    ticket = secrets.token_urlsafe(32)
    with _LOCK:
        # Bounded ephemeral state, never persisted or logged.
        for key in list(_PENDING):
            if _PENDING[key]['expires'] < time.time():
                del _PENDING[key]
        if len(_PENDING) >= 8:
            return {'ok': False, 'error': 'too many sign-in attempts'}
        _PENDING[ticket] = {'expires': time.time()+180, 'result': None}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # callback URL contains an authorization code

        def do_GET(self):
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if parsed.path != '/callback' or not secrets.compare_digest(query.get('state',[''])[0], state):
                self.send_error(400, 'Invalid sign-in state')
                return
            result = {'ok': False, 'error': 'sign-in failed'}
            try:
                code = query.get('code', [''])[0]
                if not code:
                    raise ValueError('missing code')
                form = {'client_id': client, 'grant_type': 'authorization_code', 'code': code,
                        'code_verifier': verifier, 'redirect_uri': redirect}
                # Google's installed-app secret is not confidential; keep any supplied value out of source.
                if os.environ.get('GOOGLE_CLIENT_SECRET'):
                    form['client_secret'] = os.environ['GOOGLE_CLIENT_SECRET']
                req = Request(_TOKEN, data=urlencode(form).encode(), headers={'Content-Type':'application/x-www-form-urlencoded'})
                with urlopen(req, timeout=20) as response:
                    token = json.load(response)
                result = auth_accounts.signin_oidc(state_dir, 'google', verify_id_token(token['id_token'], client, nonce))
            except Exception:
                pass
            with _LOCK:
                if ticket in _PENDING:
                    _PENDING[ticket]['result'] = result
            self.send_response(200)
            self.send_header('Content-Type','text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(b'Sign-in complete. Return to Simko SI.' if result['ok'] else b'Sign-in failed. Return to Simko SI.')
            threading.Thread(target=server.shutdown, daemon=True).start()

    server = HTTPServer(('127.0.0.1', 0), Callback)
    redirect = f'http://127.0.0.1:{server.server_port}/callback'
    def run():
        timer = threading.Timer(180, server.shutdown)
        timer.daemon = True
        timer.start()
        try:
            server.serve_forever(poll_interval=0.2)
        finally:
            timer.cancel()
            server.server_close()
    threading.Thread(target=run, daemon=True).start()
    url = _GOOGLE + '?' + urlencode({'client_id':client,'redirect_uri':redirect,'response_type':'code',
         'scope':'openid email profile','state':state,'nonce':nonce,'code_challenge':challenge,'code_challenge_method':'S256'})
    return {'ok':True,'ticket':ticket,'url':url,'browser_opened':open_auth_browser(url)}


def poll(ticket):
    with _LOCK:
        row = _PENDING.get(ticket)
        if not row or row['expires'] < time.time():
            _PENDING.pop(ticket, None)
            return {'ok':False,'error':'sign-in expired'}
        if row['result'] is None:
            return {'ok':True,'pending':True}
        return _PENDING.pop(ticket)['result']


def open_auth_browser(url):
    """Use the OS default browser, not an embedded WebView carrying a user profile."""
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in {'accounts.google.com','github.com','wxvjajecvklfjxppawdx.supabase.co'}:
        return False
    try:
        import webbrowser
        return bool(webbrowser.open(url,new=1))
    except Exception:
        return False


_APPROVED_SUPABASE = 'https://wxvjajecvklfjxppawdx.supabase.co'

def _apple_configured():
    return (os.environ.get('SIMKO_APPLE_SUPABASE') == '1'
            and os.environ.get('SUPABASE_URL','').rstrip('/') == _APPROVED_SUPABASE
            and bool(os.environ.get('SUPABASE_ANON_KEY'))
            and bool(os.environ.get('APPLE_CLIENT_ID')))


def _begin_apple(state_dir):
    """Apple -> registered Supabase HTTPS callback -> random loopback PKCE callback.

    Apple's signing key stays in Supabase configuration, never the desktop app.
    The secret callback path binds this local flow; the auth code is single-use.
    """
    if not _apple_configured():
        return {'ok':False,'error':'configure Apple provider on the approved Supabase project first'}
    verifier, binding, ticket = secrets.token_urlsafe(48), secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    with _LOCK:
        for key in list(_PENDING):
            if _PENDING[key]['expires'] < time.time(): del _PENDING[key]
        if len(_PENDING) >= 8: return {'ok':False,'error':'too many sign-in attempts'}
        _PENDING[ticket]={'expires':time.time()+180,'result':None}
    public_key = os.environ['SUPABASE_ANON_KEY']
    class Callback(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self):
            parsed=urlparse(self.path)
            if not secrets.compare_digest(parsed.path,'/callback/'+binding):
                self.send_error(400,'Invalid sign-in state')
                return
            result={'ok':False,'error':'Apple sign-in failed'}
            try:
                code=parse_qs(parsed.query).get('code',[''])[0]
                if not code: raise ValueError()
                req=Request(_APPROVED_SUPABASE+'/auth/v1/token?grant_type=pkce',
                    data=json.dumps({'auth_code':code,'code_verifier':verifier}).encode(),
                    headers={'apikey':public_key,'Content-Type':'application/json'})
                with urlopen(req,timeout=20) as response: session=json.load(response)
                access=session['access_token']
                req=Request(_APPROVED_SUPABASE+'/auth/v1/user',headers={'apikey':public_key,'Authorization':'Bearer '+access})
                with urlopen(req,timeout=20) as response: user=json.load(response)
                import uuid
                uuid.UUID(user['id'])
                # Provider is server-controlled; never authorize from user_metadata.
                if not any(i.get('provider')=='apple' for i in user.get('identities',[])):
                    raise ValueError('Apple identity missing')
                result=auth_accounts.signin_oidc(state_dir,'apple',{'sub':user['id'],'email':user.get('email',''),
                    'email_verified':bool(user.get('email_confirmed_at'))})
                # Provider session is not persisted in plaintext or sent to the UI.
            except Exception:
                pass
            with _LOCK:
                if ticket in _PENDING: _PENDING[ticket]['result']=result
            self.send_response(200)
            self.send_header('Content-Type','text/plain')
            self.end_headers()
            self.wfile.write(b'Return to Simko SI to finish Apple sign-in.')
            threading.Thread(target=server.shutdown,daemon=True).start()
    server=HTTPServer(('127.0.0.1',0),Callback)
    redirect=f'http://127.0.0.1:{server.server_port}/callback/{binding}'
    def run():
        timer=threading.Timer(180,server.shutdown)
        timer.daemon=True
        timer.start()
        try: server.serve_forever(poll_interval=.2)
        finally:
            timer.cancel()
            server.server_close()
    threading.Thread(target=run,daemon=True).start()
    url=_APPROVED_SUPABASE+'/auth/v1/authorize?'+urlencode({'provider':'apple','redirect_to':redirect,
        'code_challenge':challenge,'code_challenge_method':'s256'})
    return {'ok':True,'ticket':ticket,'url':url,'browser_opened':open_auth_browser(url)}
