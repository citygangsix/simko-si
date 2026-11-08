# Conversation preservation index

This index preserves the GitHub-safe results of the cloud-phone, ChatGPTMentors phone-authentication, and IBM-local-transfer conversation. The work belongs to the existing private `citygangsix/og-raw-frontier-ai` repository and is not a separate project.

## Records

- `docs/handoffs/2026-09-01-cloud-phone-conversation-summary.md` — sanitized human-readable decisions, status, dependencies, and unresolved work.
- `docs/handoffs/2026-09-01-cloud-phone-conversation-summary.json` — structured version of the same safe handoff.
- `TRANSFER-MANIFEST.json` — authoritative source/data separation and IBM transfer dependency inventory.
- `IBM-LOCAL-DEPLOYMENT.md` — deployment, recovery, Supabase, Granite/Ollama, and external-service guidance.
- `docs/social-cloud-phone-launch-checklist.md` — stopped-device launch and approval gates.
- `docs/FIREBASE_PHONE_SIGNUP.md` — Firebase/Supabase phone-signup operations.

## Project status

| Area | Status | Durable source | External or restricted state |
|---|---|---|---|
| ChatGPTMentors phone signup | Implemented and tested in production source | Firebase phone client, signup UI, mock test, operations guide | Firebase provider settings, Auth users, SMS activity, role-claim administration |
| Supabase integration | Source and migrations versioned | `supabase/`, RLS migrations, Edge Functions | Live rows, Auth, Storage, Realtime state, deployed secrets |
| Social cloud phones | Safe staging implemented; no autonomous launch completed | stopped configuration template, readiness checker/test, launch checklist | GeeLark account/profile IDs, proxy, API key, social credentials, cookies, 2FA, queues, audit data |
| Vercel deployment | Prior repair already merged | repository workflows and deployment scripts | Vercel account credentials and live deployment state |
| IBM Granite/Ollama | Deployment path documented and versioned | Compose/Docker files, Granite configuration template, local-AI boundary | model weights, IBM credentials, persistent volumes and runtime state |
| Social posting automation | Not activated | approval requirements and safety boundaries only | authorized account package, content, provider access, owner approvals |

## GitHub-safe versus restricted

GitHub contains only sanitized requirements, source, tests, migrations, templates, and handoff records. It must not contain the complete conversation, secrets, customer or Auth records, database dumps, Storage objects, provider profiles, browser state, social credentials, proxy details, media, transcripts, model weights, runtime queues, or ordinary logs.

The complete locally available conversation is preserved separately in an encrypted archive. Its raw Codex session is the authoritative local source; referenced ChatGPT material is complete only where it was cached or quoted into that session.

## Simplest IBM import

1. Clone the private repository and check out the reviewed production commit or approved transfer branch.
2. Copy `config/ibm-granite.example.env` to an untracked `.env.ibm` and supply real values through IBM Secrets Manager or OpenShift Secrets.
3. Start the existing deployment with `docker compose --env-file .env.ibm -f compose.ibm.yaml up --build`.
4. Pull the recorded model with `ollama pull granite4:3b`, or set the documented OpenAI-compatible base URL and model name for another approved local platform.
5. Initially keep Supabase, Firebase, Twilio and any cloud-device provider connected over TLS. Migrate their live data only through separate encrypted, access-controlled backups.
6. Verify `/healthz`, run the repository tests and build, confirm Granite inference, and test RLS with two distinct users before cutover.

Never expose Ollama, Postgres, provider credentials, or service-role keys directly to the public internet.

## CRM calendar and Dashboard 1 preservation

- Sanitized preservation record: `docs/handoffs/2026-09-02-crm-calendar-preservation.md`
- Structured summary: `docs/handoffs/2026-09-02-crm-calendar-export.json`
- Original implementation: pull request #20

## Implementation status

The repository preserves the worker repertoire/capability model, evidence-backed AI suggestions, human approval workflow, customer-safe portfolio projections, Twilio worker-message association, call-to-worker matching, Dashboard 1 worker PWA/calendar, worker authentication projections, notification drafts, migrations, and focused tests.

Live activation remains operational work: apply reviewed migrations, connect technician Auth identities, deploy the webhook/service adapter, configure Twilio and private media storage, enable Realtime/push infrastructure, and validate two-worker RLS isolation. AI-inferred capabilities and schedules must never publish without human approval.

## Database and media

Supabase migrations, RLS policies, and Edge Function source are GitHub-safe. Live rows, Auth identities/sessions, recordings, transcripts, provider media, private Storage objects, Web Push endpoints, database dumps, and logs are restricted data and must move only through encrypted, access-controlled backups or remain connected over TLS.

## Automations and providers

Twilio, push, calls, calendar updates, and customer-profile sending remain approval-gated. Credentials belong in IBM Secrets Manager, OpenShift Secrets, or an equivalent secret store. Provider callbacks must use signature verification and idempotency.

## IBM Granite and Ollama

Use the existing `IBM-LOCAL-DEPLOYMENT.md`, `compose.ibm.yaml`, and `config/ibm-granite.example.env`. Granite operates through the OpenAI-compatible local-AI boundary and may produce redacted advisory classifications only. Model weights and caches are reproducibly downloaded on the IBM host and never committed.

## Security separation

GitHub contains sanitized source, tests, migrations, templates, and handoffs. Complete conversation exports and any private operational material belong only in the separately encrypted restricted backup.
