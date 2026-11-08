"""Stage this local feature branch into the existing Tauri wrapper; never builds.

Preserve wrapper-only Granite/setup work. Abort on unexpected divergence in the
shared modules instead of replacing somebody else's changes. No network or git.
"""
import argparse
import ast
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'podcoder-translator-renter'
SHARED = ['vault','auth_accounts','notify','offline_sync','memories','scheduler','gallery','connectors',
          'platform_paths','smtp_transport','desktop_oidc','multi_agents','browser_driver','platform_api',
          'user_settings','local_exports','usage_ledger','family_team','connector_oauth','phone_calls','sandbox_checkout','cloud_backup','feature_defaults']
# Filled with the historical originals during development; shared source is authoritative thereafter.
BASELINE = {'vault': '32c9dfe4075518c42229e3acd2f543897835eeee3d3f7f3b420c8935dba37578', 'auth_accounts': 'ff8b863c98bcb6df64cf7f2d89fcc757c6051adbb2517846058c553143ea9539', 'notify': '5a7194c499fc17bc25df293c8bb510675c6f819a29d64323bea26c6d487c66f3', 'offline_sync': '90e18931286d8a5816e34e56f6db6f955c0af50ae74e8d781d89b9dcc8711069', 'memories': '4342f7ec6c8803c197cb9aa7ab4016b7cee4acdfd03bee13ef60e6043b3a8b90', 'scheduler': 'e40626754f75e21a11d1ef471f8ee45dc7fcbe9811764571487fb64c04c27237', 'gallery': '02ad8d7591e9a0b3bfb1555f6509de260b677111d41eb20915bbd0204a6d6544', 'connectors': 'af3f1bfc0c12c17b8abcfc762c178f2a5067f28a79f3bec71d1362a190f0dc57'}

BASELINE['user_settings'] = 'bab76b5b76ed3f906c9981f2b020981444abf1a3354afd6d3a79ca53d8f0f4a9'
PREVIOUS = {'vault': '59bcb5dbaabc79ecff1b22bcb4bea2bf8a77860711b0f6d9d9884df25a90dc28', 'offline_sync': '5d909e669e0657e9cc0c1cfe84dcebfb13c6f16f6c872425f40297b3f4b50d12', 'desktop_oidc': '5c6fca1092e057da109bbbef872fc02ab83d7ae7301ef464a384ec301a5ac0e7', 'platform_api': '4e0c37d9e587ffe3243d9fcb809f8955ea23a36ebdd8ec307969b739106db259', 'connector_oauth': '0c8e122c7ab468ae98ddac02317455a8333ef68d6099edb5bb18b1a872208bf5'}

def replace_function(text, source, name, class_name=None):
    def node_for(text):
        nodes = ast.parse(text).body
        if class_name:
            nodes = next(n for n in nodes if isinstance(n,ast.ClassDef) and n.name==class_name).body
        return next(n for n in nodes if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
    old,new = node_for(text),node_for(source)
    lines, fresh = text.splitlines(keepends=True), source.splitlines(keepends=True)
    return ''.join(lines[:old.lineno-1]+fresh[new.lineno-1:new.end_lineno]+lines[old.end_lineno:])


def sync(target):
    if not (target/'backend/simko_backend.py').is_file():
        raise SystemExit('existing Simko SI wrapper required')
    pod = target/'backend/app/podcoder'
    local = target/'backend/app/local'
    manifest = target/'.simko-platform-staged.json'
    staged = json.loads(manifest.read_text()) if manifest.is_file() else {}
    # Validate all replacements before any writes.
    for name in SHARED:
        dst = pod/(name+'.py')
        src = SOURCE/'podcoder'/(name+'.py')
        if dst.exists() and dst.read_bytes()!=src.read_bytes():
            expected = BASELINE.get(name)
            digest = hashlib.sha256(dst.read_bytes()).hexdigest()
            accepted = {expected, PREVIOUS.get(name), staged.get(name)}
            if digest not in accepted:
                raise SystemExit('wrapper module diverged; merge manually: '+name)

    for name in SHARED:
        shutil.copy2(SOURCE/'podcoder'/(name+'.py'),pod/(name+'.py'))
    shutil.copy2(SOURCE/'local/platform-preview.js',local/'platform-preview.js')
    shutil.copy2(SOURCE/'local/desktop-lab.html',local/'desktop-lab.html')
    shutil.copy2(SOURCE/'requirements-desktop.txt',target/'backend/requirements-desktop.txt')
    server = local/'server.py'
    text = server.read_text()
    src = (SOURCE/'local/server.py').read_text()
    for name,cls in [('app_state_dir',None),('_product','H')]:
        text=replace_function(text,src,name,cls)
    if '"/platform-preview.js"' not in text:
        text=text.replace('STATIC_FILES = {','STATIC_FILES = {\n    "/platform-preview.js": "text/javascript; charset=utf-8",')
    if '"/desktop-lab.html"' not in text:
        text=text.replace('STATIC_FILES = {','STATIC_FILES = {\n    "/desktop-lab.html": "text/html; charset=utf-8",')
    server.write_text(text)
    chat = local/'chat.html'
    text = chat.read_text()
    if '<script src="/platform-preview.js">' not in text:
        chat.write_text(text.replace('</body>','<script src="/platform-preview.js"></script>\n</body>'))
    # Append only new functions; preserve wrapper xAI key/config fixes and coder behavior.
    client = pod/'xai_client.py'
    text=client.read_text()
    marker='\ndef _desktop_request('
    if marker in text: text=text[:text.index(marker)]
    src=(SOURCE/'podcoder/xai_client.py').read_text()
    client.write_text(text+'\n'+src[src.index(marker):])
    product=pod/'product_api.py'
    text=product.read_text()
    marker='\ndef try_handle('
    if '\ndef _try_handle(' not in text:
        text=text.replace('def try_handle(','def _try_handle(',1)
    elif marker in text:
        text=text[:text.index(marker)]
    src=(SOURCE/'podcoder/product_api.py').read_text()
    if 'if op == "set-feature":' not in text:
        text=text.replace('        if op == "set-model":','        if op == "set-feature":\n            return 200, user_settings.set_feature_flag(state,user,str(body.get("name") or ""),body.get("enabled"))\n        if op == "set-model":')
    product.write_text(text+'\n'+src[src.rindex(marker):])
    backend=target/'backend/simko_backend.py'
    text=backend.read_text()
    if 'feature_defaults.apply()' not in text:
        text=text.replace('    import scheduler\n    stop_routines = ','    import feature_defaults\n    feature_defaults.apply()\n    import scheduler\n    stop_routines = ',1)
    if 'stop_routines = ' not in text:
        text=text.replace('    ui = _make(server.H, want)','    import scheduler\n    stop_routines = scheduler.start_background(server.app_state_dir())\n    ui = _make(server.H, want)')
        text=text.replace('    finally:\n        setup_steps.stop_ollama()','    finally:\n        stop_routines.set()\n        setup_steps.stop_ollama()')
    backend.write_text(text)
    spec=target/'backend/simko-backend.spec'
    text=spec.read_text()
    if 'collect_submodules("cryptography")' not in text:
        text=text.replace('hidden += ["httpx", "bs4"]','hidden += ["httpx", "bs4"] + collect_submodules("cryptography") + collect_submodules("jwt") + collect_submodules("plyer")')
        text=text.replace('    strip=False,','    strip=False,\n    target_arch="universal2" if os.environ.get("SIMKO_UNIVERSAL2") == "1" else None,')
    spec.write_text(text)
    # Platform-specific bundle config is selected explicitly; no accidental cross-host bundling.
    config=target/'src-tauri/tauri.conf.json'
    doc=json.loads(config.read_text())
    doc['bundle']['targets']=['nsis','appimage','app','dmg']
    doc['bundle']['macOS']={'minimumSystemVersion':'12.0','signingIdentity':None}
    doc['bundle']['windows'].update(certificateThumbprint=None,digestAlgorithm='sha256',timestampUrl=None)
    config.write_text(json.dumps(doc,indent=2)+'\n')
    for name,targets in [('macos',['app','dmg']),('windows',['nsis']),('linux',['appimage'])]:
        (target/'src-tauri'/('tauri.'+name+'.conf.json')).write_text(json.dumps({'bundle':{'targets':targets}},indent=2)+'\n')
    package=target/'package.json'
    doc=json.loads(package.read_text())
    doc.setdefault('scripts',{}).update({
        'build:mac:universal':'tauri build --target universal-apple-darwin --config src-tauri/tauri.macos.conf.json',
        'build:windows':'tauri build --config src-tauri/tauri.windows.conf.json',
        'build:linux':'tauri build --config src-tauri/tauri.linux.conf.json'})
    package.write_text(json.dumps(doc,indent=2)+'\n')
    shutil.copy2(ROOT/'SIGNING.md',target/'SIGNING.md')
    manifest.write_text(json.dumps({name:hashlib.sha256((pod/(name+'.py')).read_bytes()).hexdigest() for name in SHARED},indent=2)+'\n')
    print('Staged local source only. No installers built, signed, published, or uploaded.')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('wrapper',type=Path)
    sync(parser.parse_args().wrapper.resolve())
