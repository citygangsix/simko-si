"""Authenticated, opt-in desktop feature routes. Never proxies these routes to a pod."""
import os
import auth_accounts
import desktop_oidc

FLAGS = ('platform_ui','agents','browser','memory_sync','notifications','routines','paid_api_enabled','connectors','calls','paywall','cloud_backup')


def flags():
    return {name:os.environ.get('SIMKO_'+name.upper()) == '1' for name in FLAGS}


def _feature_route(path, active):
    """Approved features stay reachable by API without showing the unapproved lab UI."""
    if path in ('/api/platform/search','/api/platform/image','/api/platform/usage'):
        return active['paid_api_enabled']
    if path.startswith('/api/platform/agents/'):
        return active['agents'] and active['paid_api_enabled']
    if path in ('/api/platform/sync','/api/platform/sync/status'):
        return active['memory_sync']
    if path == '/api/platform/notify/test':
        return active['notifications']
    return False


def handle(method, path, body, state):
    if not path.startswith('/api/platform/'):
        return None
    body = body or {}
    owner = auth_accounts.email_for_token(state,str(body.get('token','')))
    active = flags()
    if owner:
        import user_settings
        active['platform_ui'] = active['platform_ui'] or user_settings.get_feature_flags(state,owner)['desktop_lab']
    if method == 'GET' and path == '/api/platform/config':
        return 200, {'ok':True,'flags':active,'providers':desktop_oidc.providers()}
    if not active['platform_ui'] and not _feature_route(path, active):
        return 403, {'ok':False,'error':'desktop feature preview disabled'}
    if method != 'POST':
        return 405, {'ok':False,'error':'POST required'}
    if path == '/api/platform/oauth/begin':
        return 200, desktop_oidc.begin(state,str(body.get('provider','google')))
    if path == '/api/platform/oauth/poll':
        return 200, desktop_oidc.poll(str(body.get('ticket','')))
    owner = auth_accounts.email_for_token(state,str(body.get('token','')))
    if not owner:
        return 401, {'ok':False,'error':'sign in required'}
    try:
        configurations = None
        if path == '/api/platform/agents/start' and body.get('use_applied_template') is True:
            import local_exports
            applied = local_exports.active_template(state,owner)
            if not applied['ok']:
                return 400, applied
            configurations = applied['template']['agents']
        if path in ('/api/platform/search','/api/platform/image','/api/platform/agents/start'):
            if body.get('approve_paid') is not True or not flags()['paid_api_enabled']:
                return 403, {'ok':False,'error':'paid API disabled or this action not approved'}
        if path in ('/api/platform/search','/api/platform/image','/api/platform/agents/start'):
            import usage_ledger
            count = 2*len(configurations if configurations is not None else body.get('names',[])) if path.endswith('/agents/start') else 1
            reservation = usage_ledger.reserve(state,owner,path.rsplit('/',1)[-1],count)
            if not reservation['ok']:
                return 402, reservation
        if path == '/api/platform/calls/status':
            import phone_calls
            return 200, phone_calls.status()
        if path == '/api/platform/vault/keychain':
            import vault
            return 200, vault.remember_in_keychain(state,owner,str(body.get('passphrase','')))
        if path == '/api/platform/usage':
            import usage_ledger
            return 200, usage_ledger.snapshot(state,owner)
        if path == '/api/platform/report':
            import local_exports
            return 200, local_exports.report(state,owner,str(body.get('title','Report')),str(body.get('text','')))
        if path == '/api/platform/templates/export':
            import local_exports
            return 200, local_exports.export_template(state,str(body.get('name','')),body.get('agents',[]))
        if path == '/api/platform/templates/import':
            import local_exports
            return 200, local_exports.import_template(state,str(body.get('content','')))
        if path == '/api/platform/templates/apply':
            import local_exports
            return 200, local_exports.apply_template(state,owner,str(body.get('content','')),owner_confirmed=body.get('owner_confirmed'))
        if path == '/api/platform/templates/active':
            import local_exports
            return 200, local_exports.active_template(state,owner)
        if path == '/api/platform/team/permissions/import':
            import family_team
            return 200, family_team.import_permissions(state,owner,str(body.get('snapshot','')))
        if path in ('/api/platform/team/resource/read','/api/platform/team/resource/write'):
            import family_team
            if path.endswith('/write') and not isinstance(body.get('content'),str):
                return 400, {'ok':False,'error':'content required'}
            return 200, family_team.resource(state,owner,str(body.get('team','')),str(body.get('resource','')),
                content=body.get('content') if path.endswith('/write') else None)
        if path == '/api/platform/checkout/create':
            import sandbox_checkout
            return 200, sandbox_checkout.create(state,owner,body.get('request_id'),owner_confirmed=body.get('owner_confirmed'))
        if path == '/api/platform/checkout/status':
            import sandbox_checkout
            return 200, sandbox_checkout.reconcile(state,owner,str(body.get('id','')))
        if path == '/api/platform/team/create':
            import family_team
            return 200, family_team.create(state,owner,str(body.get('name','Family')))
        if path == '/api/platform/team/member':
            import family_team
            return 200, family_team.set_member(state,owner,str(body.get('team','')),str(body.get('member','')),str(body.get('role','')))
        if path == '/api/platform/team/members':
            import family_team
            return 200, family_team.members(state,owner,str(body.get('team','')))
        if path == '/api/platform/connectors':
            import connector_oauth
            return 200, connector_oauth.listing()
        if path == '/api/platform/connectors/begin':
            import connector_oauth
            return 200, connector_oauth.begin(state,owner,str(body.get('passphrase','')),str(body.get('name','')))
        if path == '/api/platform/connectors/poll':
            import connector_oauth
            return 200, connector_oauth.poll(owner,str(body.get('ticket','')))
        if path == '/api/platform/connectors/read':
            import connector_oauth
            return 200, connector_oauth.read(state,owner,str(body.get('passphrase','')),str(body.get('name','')))
        if path == '/api/platform/search':
            import xai_client
            return 200, xai_client.web_search(str(body.get('query','')))
        if path == '/api/platform/image':
            import xai_client
            return 200, xai_client.image_from_prompt(state,str(body.get('prompt','')))
        if path == '/api/platform/agents/start':
            import multi_agents
            return 200, multi_agents.start(owner,body.get('names',[]),str(body.get('task','')),configurations=configurations)
        if path == '/api/platform/agents/status':
            import multi_agents
            return 200, multi_agents.status(owner,str(body.get('id','')))
        if path == '/api/platform/agents/message':
            import multi_agents
            return 200, multi_agents.message(owner,str(body.get('id','')),str(body.get('text','')),str(body.get('to','all')))
        if path == '/api/platform/agents/cancel':
            import multi_agents
            return 200, multi_agents.cancel(owner,str(body.get('id','')))
        if path == '/api/platform/templates/history':
            import local_exports
            return 200, local_exports.template_history(state,owner)
        if path == '/api/platform/templates/rollback':
            import local_exports
            return 200, local_exports.rollback_template(state,owner,str(body.get('id','')),owner_confirmed=body.get('owner_confirmed'))
        if path == '/api/platform/browser/prepare':
            import browser_driver
            return 200, browser_driver.prepare(owner,str(body.get('url','')),body.get('fields'),
                form_index=body.get('form_index',0),operation=body.get('operation','submit'))
        if path == '/api/platform/browser/confirm':
            import browser_driver
            return 200, browser_driver.submit(owner,str(body.get('approval_ticket','')),owner_confirmed=body.get('owner_confirmed'))
        if path == '/api/platform/browser/read':
            import browser_driver
            return 200, browser_driver.read(str(body.get('url','')))
        if path.startswith('/api/platform/backup/'):
            import cloud_backup
            action = path.rsplit('/',1)[-1]
            passphrase = str(body.get('passphrase',''))
            if action == 'status':
                return 200, cloud_backup.status(state,owner)
            if action == 'create':
                return 200, cloud_backup.create(state,owner,passphrase,upload=body.get('upload',True) is not False)
            if action == 'flush':
                return 200, cloud_backup.flush(state,owner)
            if action == 'list':
                return 200, cloud_backup.list_backups(state,owner)
            if action == 'verify':
                return 200, cloud_backup.verify(state,owner,str(body.get('backup_id','')),passphrase)
            if action == 'restore':
                return 200, cloud_backup.restore(state,owner,str(body.get('backup_id','')),passphrase,
                                                 owner_confirmed=body.get('owner_confirmed'))
        if path == '/api/platform/sync/status':
            import offline_sync
            return 200, offline_sync.status(state)
        if path == '/api/platform/sync':
            import offline_sync
            return 200, offline_sync.sync_memories(state,owner)
        if path == '/api/platform/notify/test':
            import notify
            return 200, {'ok':True,'desktop':notify.desktop('Simko SI','Desktop notifications are enabled.')}
    except Exception:
        return 400, {'ok':False,'error':'invalid request or integration unavailable'}
    return 404, {'ok':False,'error':'unknown desktop action'}
