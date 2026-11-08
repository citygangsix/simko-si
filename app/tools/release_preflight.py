"""Read-only unsigned release-prep audit. Never builds, signs, installs or submits."""
import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Must stay off. Owner-approved default-on features (Joseph, 2026-11-08) are listed
# in podcoder/feature_defaults.py APPROVED_ON and may be on.
FLAGS = ('PLATFORM_UI', 'BROWSER', 'CONNECTORS', 'CALLS', 'PAYWALL', 'APPLE_SUPABASE', 'CLOUD_BACKUP')
APPROVED_ON = ('MEMORY_SYNC', 'MEMORY_SYNC_AUTO', 'PAID_API_ENABLED', 'AGENTS', 'ROUTINES', 'NOTIFICATIONS')


def audit(root=ROOT/'desktop-wrapper'):
    errors = []
    for name in FLAGS:
        if os.environ.get('SIMKO_' + name, '0') not in ('', '0'):
            errors.append('feature flag must remain off: SIMKO_' + name)
    try:
        import ast
        source = (ROOT/'podcoder-translator-renter/podcoder/feature_defaults.py').read_text()
        declared = next(ast.literal_eval(node.value) for node in ast.parse(source).body
                        if isinstance(node, ast.Assign) and node.targets[0].id == 'APPROVED_ON')
        if set(declared) - set(APPROVED_ON) or set(declared) & set(FLAGS):
            errors.append('default-on features exceed the owner-approved list')
    except (OSError, StopIteration, ValueError, AttributeError):
        errors.append('feature defaults missing or unreadable')
    try:
        config = json.loads((root/'src-tauri/tauri.conf.json').read_text())
        if config['bundle']['windows'].get('certificateThumbprint') is not None:
            errors.append('Windows signing placeholder is configured; approval audit required')
        if config['bundle']['macOS'].get('signingIdentity') is not None:
            errors.append('Apple signing placeholder is configured; approval audit required')
        for platform, targets in [('macos', ['app', 'dmg']), ('windows', ['nsis']), ('linux', ['appimage'])]:
            selected = json.loads((root/'src-tauri'/('tauri.'+platform+'.conf.json')).read_text())
            if selected.get('bundle', {}).get('targets') != targets:
                errors.append('unexpected host targets: ' + platform)
        package = json.loads((root/'package.json').read_text())
        if 'universal-apple-darwin' not in package['scripts'].get('build:mac:universal', ''):
            errors.append('universal macOS script missing')
    except (OSError, ValueError, KeyError, TypeError):
        errors.append('missing or invalid release-prep configuration')
    return {'ok': not errors, 'errors': errors, 'signed': False, 'release_ready': False,
            'remaining': ['Joseph approves Apple enrollment and Windows signing quote',
                          'native Mac/Windows builds and acceptance',
                          'separate approval for signing, notarization and store submission']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--wrapper', type=Path, default=ROOT/'desktop-wrapper')
    result = audit(parser.parse_args().wrapper)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['ok'] else 1)
