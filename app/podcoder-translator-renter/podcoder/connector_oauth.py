"""Allowlisted OAuth registry with ephemeral loopback PKCE and vaulted tokens.

No arbitrary REST proxy; initial adapters only read Drive file metadata and public
GitHub repository metadata. Private GitHub repos need a read-only GitHub App later.
"""
import base64
import hashlib
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
import vault

REGISTRY = {
 'drive': {'id':'DRIVE_CLIENT_ID','secret':'DRIVE_CLIENT_SECRET','auth':'https://accounts.google.com/o/oauth2/v2/auth','token':'https://oauth2.googleapis.com/token','scope':'https://www.googleapis.com/auth/drive.readonly','read':'https://www.googleapis.com/drive/v3/files?pageSize=100&fields=files(id,name,mimeType,modifiedTime,webViewLink)'},
 'github': {'id':'GITHUB_CLIENT_ID','secret':'GITHUB_CLIENT_SECRET','auth':'https://github.com/login/oauth/authorize','token':'https://github.com/login/oauth/access_token','scope':'read:user','read':'https://api.github.com/user/repos?visibility=public&per_page=100'},
}
_FLOWS = {}
_LOCK = threading.Lock()


def listing():
    return {'ok':True,'connectors':[{'name':name,'configured':bool(os.environ.get(spec['id'])),
        'read_only':True,'scope':spec['scope']} for name,spec in REGISTRY.items()]}


def _json_request(url, data=None, headers=None, opener=None):
    req = Request(url,data=data,headers=headers or {})
    with (opener or urlopen)(req,timeout=20) as response:
        return json.loads(response.read(4*1024*1024))


def begin(state_dir,owner,passphrase,name):
    if os.environ.get('SIMKO_CONNECTORS') != '1' or name not in REGISTRY:
        return {'ok':False,'error':'connector disabled or unknown'}
    spec = REGISTRY[name]
    if not os.environ.get(spec['id']):
        return {'ok':False,'error':'register an OAuth client first'}
    password = passphrase or vault.keychain_passphrase(owner)
    if not password:
        return {'ok':False,'error':'unlock vault first'}
    try:
        vault.unlock(state_dir,owner,password)
    except Exception:
        return {'ok':False,'error':'vault could not be opened'}
    ticket,state,verifier = secrets.token_urlsafe(32),secrets.token_urlsafe(32),secrets.token_urlsafe(48)
    with _LOCK:
        for key in list(_FLOWS):
            if _FLOWS[key]['expires'] < time.time(): del _FLOWS[key]
        if len(_FLOWS)>=8: return {'ok':False,'error':'too many authorization attempts'}
        _FLOWS[ticket] = {'owner':owner,'expires':time.time()+180,'result':None}
    class Callback(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self):
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if parsed.path != '/callback' or not secrets.compare_digest(query.get('state',[''])[0],state):
                self.send_error(400,'Invalid authorization state')
                return
            result = {'ok':False,'error':'connector authorization failed'}
            try:
                form = {'client_id':os.environ[spec['id']],'code':query.get('code',[''])[0],
                        'redirect_uri':redirect,'code_verifier':verifier,'grant_type':'authorization_code'}
                if os.environ.get(spec['secret']): form['client_secret'] = os.environ[spec['secret']]
                token = _json_request(spec['token'],urlencode(form).encode(),{'Accept':'application/json','Content-Type':'application/x-www-form-urlencoded'})
                if not token.get('access_token'): raise ValueError()
                token['expires_at'] = str(time.time()+int(token.get('expires_in',3600))) if name == 'drive' else ''
                result = vault.put_oauth(state_dir,owner,password,name,token)
            except Exception:
                pass
            with _LOCK:
                if ticket in _FLOWS: _FLOWS[ticket]['result'] = {'ok':bool(result.get('ok')),'provider':name}
            self.send_response(200)
            self.send_header('Content-Type','text/plain')
            self.end_headers()
            self.wfile.write(b'Return to Simko SI to check connector status.')
            threading.Thread(target=server.shutdown,daemon=True).start()
    server = HTTPServer(('127.0.0.1',0),Callback)
    redirect = f'http://127.0.0.1:{server.server_port}/callback'
    def serve():
        timer = threading.Timer(180,server.shutdown)
        timer.daemon=True
        timer.start()
        try: server.serve_forever(poll_interval=.2)
        finally:
            timer.cancel()
            server.server_close()
    threading.Thread(target=serve,daemon=True).start()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    params = {'client_id':os.environ[spec['id']],'redirect_uri':redirect,'response_type':'code','scope':spec['scope'],
              'state':state,'code_challenge':challenge,'code_challenge_method':'S256'}
    if name == 'drive': params.update(access_type='offline',prompt='consent')
    if name == 'github': params['allow_signup'] = 'false'
    url = spec['auth']+'?'+urlencode(params)
    from desktop_oidc import open_auth_browser
    return {'ok':True,'ticket':ticket,'url':url,'browser_opened':open_auth_browser(url)}


def poll(owner,ticket):
    with _LOCK:
        row = _FLOWS.get(ticket)
        if not row or row['owner']!=owner or row['expires']<time.time():
            return {'ok':False,'error':'authorization expired or not found'}
        if row['result'] is None: return {'ok':True,'pending':True}
        return _FLOWS.pop(ticket)['result']


def read(state,owner,passphrase,name,*,opener=None):
    if os.environ.get('SIMKO_CONNECTORS') != '1' or name not in REGISTRY:
        return {'ok':False,'error':'connector disabled or unknown'}
    try:
        password = passphrase or vault.keychain_passphrase(owner)
        token = vault.unlock(state,owner,password).get('oauth',{}).get(name,{})
        spec = REGISTRY[name]
        if not token.get('access_token'):
            return {'ok':False,'error':'authorize the connector first'}
        if name == 'drive' and float(token.get('expires_at') or 0) < time.time()+30:
            if not token.get('refresh_token'): return {'ok':False,'error':'authorization expired; reconnect'}
            form = {'client_id':os.environ[spec['id']],'refresh_token':token['refresh_token'],'grant_type':'refresh_token'}
            if os.environ.get(spec['secret']): form['client_secret']=os.environ[spec['secret']]
            refreshed = _json_request(spec['token'],urlencode(form).encode(),{'Content-Type':'application/x-www-form-urlencoded'},opener)
            if not refreshed.get('access_token'): raise ValueError()
            token.update(refreshed)
            token['expires_at']=str(time.time()+int(refreshed.get('expires_in',3600)))
            vault.put_oauth(state,owner,password,name,token)
        data = _json_request(spec['read'],headers={'Authorization':'Bearer '+token['access_token'],'Accept':'application/json','User-Agent':'SimkoSI-Desktop'},opener=opener)
        if name == 'github':
            data = [{'id':r['id'],'name':r['full_name'],'url':r['html_url']} for r in data if not r.get('private')]
        return {'ok':True,'provider':name,'data':data,'read_only':True}
    except Exception:
        return {'ok':False,'error':'connector unavailable or vault locked'}
