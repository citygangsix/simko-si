"""Owner-approved default-on features for the desktop app (Joseph, 2026-11-08 7:43 AM ET).

Applied once at app start with os.environ.setdefault, so an explicit
``SIMKO_<FLAG>=0`` in the environment still turns a feature off. Tests and
imports never apply these implicitly.

On: memory sync (+ background retries), cited Grok web search and prompt images
(paid per call, each still needs approve_paid), multi-agent work, routines and
their desktop notifications. Approval cards are always on.
Stays off: browser control/reading, connectors/vault OAuth, phone calls,
paywall/Square, cloud backup, the unapproved desktop-lab UI, X search,
uploads and running code.
"""
import os

APPROVED_ON = ('MEMORY_SYNC', 'MEMORY_SYNC_AUTO', 'PAID_API_ENABLED', 'AGENTS', 'ROUTINES', 'NOTIFICATIONS')
MUST_STAY_OFF = ('PLATFORM_UI', 'BROWSER', 'CONNECTORS', 'CALLS', 'PAYWALL', 'CLOUD_BACKUP', 'APPLE_SUPABASE')


def apply(environ=None):
    env = os.environ if environ is None else environ
    for name in APPROVED_ON:
        env.setdefault('SIMKO_' + name, '1')
    return {name: env.get('SIMKO_' + name) == '1' for name in APPROVED_ON}
