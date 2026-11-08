# IBM local deployment

## Canonical source

- Repository: `https://github.com/citygangsix/og-raw-frontier-ai.git`
- Transfer branch: `agent/ibm-granite-transfer`
- Production target: the repository's protected default branch after its pull request passes
- Application surface: ChatGPTMentors Omega (`/dashboard`, Omega workspace)

This Omega work belongs in the existing OG RAW Frontier repository because it shares the frontend, Supabase schema, Edge Functions, local-AI provider, and tests. Do not create a duplicate repository.

After cloning, record the immutable source with `git rev-parse HEAD` and compare it with `TRANSFER-MANIFEST.json` and the accepted pull request.

## Minimum platform

- Git, Node.js 22, npm, and approximately 4 GB free build space
- Docker Engine with Compose v2, or an OpenShift cluster capable of building `Dockerfile.ibm`
- For `granite4:3b`, begin with 8 GB RAM and 10 GB persistent model storage; validate latency on the actual IBM CPU/GPU before production
- Outbound access during setup to npm, GitHub, the approved Granite model source, and the configured Supabase project
- TLS ingress, secret management, persistent model storage, monitoring, and backups in production

## Configuration and secrets

Use `.env.example` for the complete application variable inventory and `config/ibm-granite.example.env` for the Granite path. Copy values into IBM Secrets Manager or OpenShift Secrets; do not commit `.env`, service-role keys, OAuth tokens, database passwords, private TLS keys, customer data, or health data.

`VITE_*` values are embedded into the browser bundle. They may contain a Supabase publishable key, but must never contain a service-role/secret key. `SUPABASE_SERVICE_ROLE_KEY` is server-only.

The application uses an OpenAI-compatible model boundary. The known local Granite choice is `granite4:3b`; override it only after recording the exact model, quantization, license, source, and checksum. A browser cannot reach the Compose-only hostname `granite`, so either keep browser inference at `localhost:11434` for a single workstation or expose Granite through an authenticated TLS reverse proxy and set the `VITE_LOCAL_AI_BASE_URL` at build time.

## Quick start with Docker Compose

```bash
git clone https://github.com/citygangsix/og-raw-frontier-ai.git
cd og-raw-frontier-ai
git checkout agent/ibm-granite-transfer
cp config/ibm-granite.example.env .env.ibm
docker compose --env-file .env.ibm -f compose.ibm.yaml up --build
```

Open `http://localhost:8080`; verify `http://localhost:8080/healthz` returns `ok`. Compose binds Granite only to host loopback at `127.0.0.1:11434`, stores model files in the `granite-models` volume, and does not store application/customer data. The `VITE_*` values supplied by `.env.ibm` are compile-time browser configuration, so rebuild the web image after changing them.

## Native build and verification

```bash
npm ci
npm run omega:test-project-intelligence
npm run omega:test-project-intelligence:integration
npm run test:firebase-phone-auth
npm run social:phones:test
npm run social:phones:readiness
npm run typecheck
npm run build
npm run preview -- --host 127.0.0.1
```

The integration test performs live anonymous checks only when public Supabase configuration is available, and authenticated checks only when an explicitly supplied test access token exists. Never commit that token.

## Database migration order

Apply the committed Supabase migrations in filename order. The Omega transfer sequence is:

1. `20260811150000_omega_project_intelligence.sql`
2. `20260811173000_omega_intelligence_completion.sql`
3. `20260811230000_omega_multitenant_workspaces.sql`
4. `20260812090000_omega_lifebook_conversation_memory.sql`
5. `20260812140000_omega_lifebook_scoring.sql`

Deploy `supabase/functions/omega-project-intelligence/index.ts` after the schema. Do not apply migrations to production as part of a source transfer. First restore or connect a non-production database, run the Supabase security advisors, test RLS with two owner accounts plus an anonymous client, and then schedule production changes under normal approval controls.

## Database and storage strategy

The Git repository contains schema migrations and Edge Function source only. It intentionally excludes live rows, Auth sessions/password material, database dumps, and Storage objects.

Choose one:

1. **Fastest:** keep the current Supabase project and configure the IBM application to connect to it over TLS.
2. **Fully local:** create encrypted, access-controlled database and Storage backups, restore them into the IBM environment, rotate credentials, and verify row-level and object-level policies before cutover.

The CRM source-of-truth decision remains operational: legacy jobs/invoices/customers versus `artemis_crm_*`. Resolve it before exporting live CRM data so records are not duplicated.

## Services, ports, and persistence

| Component | Port | Persistence | Health check |
|---|---:|---|---|
| Omega web | 8080 internal; 443 via TLS ingress | none | `/healthz` |
| Granite/Ollama | 11434 internal only | `granite-models` | `ollama list` |
| Granite GitHub agent (optional) | 8791 loopback or approved TLS ingress | `granite-github-state`, `granite-github-repositories` | `/healthz` |
| Supabase/Postgres | external TLS or 5432 internal | database volume/backups | provider/database readiness |
| Object storage | external TLS or internal S3 endpoint | object volume/backups | authenticated read/write probe |

Do not expose ports 5432 or 11434 publicly. Back up Postgres and object storage independently; model weights should normally be restored from an approved reproducible source.

## Backup, recovery, and acceptance

Before cutover, restore into an isolated namespace and verify:

- a clean clone installs and builds;
- the five Omega migrations apply in order;
- two users cannot read or alter each other's projects, LifeBook memories, scores, CRM mappings, or storage;
- Omega graphs, category drilldown, summaries, milestones, and CRM disconnected/connected states render correctly;
- Granite returns a grounded response through the configured OpenAI-compatible endpoint;
- Apple Health remains explicitly disconnected unless a consented import connector is configured;
- database and object backups restore successfully and their checksums match.

Rollback by returning ingress to the prior deployment and leaving the source database untouched. Keep at least one tested database backup and one object-storage backup outside the cluster.

## OrganicsRaw mentor corpus transfer

The versioned mentor files under `docs/` preserve review requirements, public source metadata, candidate decisions, and the 13 proposed winners. They do **not** contain downloaded media, transcripts, proof of owner approval, or proof of database publication.

For the simplest secure IBM transfer:

1. Clone this repository and verify the mentor JSON files.
2. Keep the existing remote Supabase project connected over TLS initially.
3. Transfer authorized media/caption/transcript artifacts separately in an encrypted, access-controlled corpus archive with checksums and provenance.
4. Configure Granite for transcript analysis and retrieval preparation; keep speech-to-text on the local Whisper worker.
5. Before any ingestion, recheck official-source status, lawful access, duplicates, and explicit owner approval.
6. Preserve `retry_historical_failures=false` / `--no-retry-failed`.
7. Add a video to Learn More only after Supabase insert and `frontier_search_ingested_videos` verification succeed.

If moving Supabase locally, export and restore the Frontier ingestion jobs/source profiles, `frontier_ingested_videos`, `frontier_transcription_tasks`, Lifebook taxonomy/mentor routing, Artemis knowledge tables, retrieval RPCs, policies, and related Storage objects through encrypted backups. Never place those records or objects in Git.

## Phone authentication and social-device transfer

The ChatGPTMentors Firebase phone-verification implementation, mock test, and Firebase/Supabase operations guide are already versioned in this repository. Production still depends on external owner-controlled settings: Firebase Phone Auth and authorized domains, the Supabase Firebase Third-Party Auth integration, and a supported Firebase Auth function/Admin SDK process that assigns the `role: authenticated` claim. The simplest IBM deployment initially keeps those managed services connected over TLS. Do not transfer Firebase service-account JSON, SMS records, Auth users, sessions, or two-factor material through Git.

The social cloud-phone workstream is also part of this repository. Its checked-in GeeLark template is stopped, disabled, and dry-run only; it stores no profile ID, provider key, proxy credential, social credential, cookie, content queue, or audit trail. Run the readiness command before considering a launch. GeeLark API access is plan-dependent, so the free-account path remains a supervised desktop handoff until an eligible API plan and locally stored key are confirmed. A real session requires separate launch and publish approvals and is capped at five minutes per profile per day for the first controlled test.

IBM Granite can draft, classify, validate, and prepare authorized social content through the existing local-AI boundary. It must not receive account passwords or two-factor codes, cannot bypass provider/platform controls, and does not itself operate a phone. Provider control remains an external integration with owner approval, audit logging, and immediate shutdown.

## Importing this preserved conversation context

Use `INDEX.md` and `docs/handoffs/2026-09-01-cloud-phone-conversation-summary.{md,json}` as the GitHub-safe operator context. For Granite/Ollama, clone the approved repository revision, start the existing Compose deployment, run `ollama pull granite4:3b`, and index only these sanitized handoff files if retrieval context is desired. Another AI platform may consume the JSON handoff through its normal document-ingestion path or use the Markdown as an operator prompt; never upload the encrypted restricted archive, its key, live database exports, browser state, credentials, private media, or complete conversation to a hosted model.

The encrypted local archive is a disaster-recovery artifact, not application input. Decrypt it only on an owner-controlled machine, verify its SHA-256/HMAC records, and selectively restore authorized material into access-controlled locations outside the Git checkout.

## Still external or credential-dependent

- Supabase database, Auth, Storage, Realtime, and deployed Edge Functions unless separately migrated
- CRM provider credentials and per-user OAuth tokens
- Apple Health import bridge (no server-side direct Apple Health connection is claimed)
- Stripe, messaging, telephony, email, and webhook providers where enabled
- GitHub and container-registry credentials
- DNS/TLS ownership and IBM cluster access

## Worker repertoire and Dashboard 1 transfer

The source-only worker repertoire and Dashboard 1 artifacts are versioned in this repository. The IBM application may use the existing OpenAI-compatible Granite boundary to classify redacted call transcripts and worker evidence, but every result remains advisory: capabilities, media, and call-derived schedules must stay in `pending_review` until an authenticated reviewer approves them. Granite must not directly send customer messages, place calls, publish schedules, or receive provider credentials.

For the simplest secure transfer, initially keep Supabase Auth/Database/Storage/Realtime and Twilio connected over TLS while moving the application and Granite runtime to IBM. Required external state includes worker Auth identities, technician-to-user mappings, repertoire evidence, private portfolio objects, appointments, notification subscriptions/preferences, delivery audit records, and Twilio provider identifiers. Keep all live rows, Storage objects, device endpoints, recordings, transcripts, and backups outside Git. A later migration must use encrypted, access-controlled backups and validate RLS with at least two worker identities before cutover.

Run the worker-focused tests before deployment. Review and apply the three worker migrations only through the approved database pipeline; then configure webhook signature validation, private media copying, Realtime, VAPID or native push credentials, verified Twilio senders, consent, quiet hours, status callbacks, retries, and idempotency.

## CRM calls, property context, parts, and payout transfer

The conversation-specific requirements are preserved in `docs/handoffs/2026-08-13-crm-ai-templates-handoff.md`. Reuse the existing Artemis CRM, worker repertoire, communications, job, pricing, route, document, and payout architecture.

For the first IBM deployment, keep Supabase, Twilio, maps/imagery, routing/fuel-price services, invoice delivery, and the authorized Marcone lookup path connected over TLS. Store credentials only in IBM Secrets Manager or OpenShift Secrets. Granite may process redacted evidence and make reviewable proposals, but it cannot approve customer sends, pricing, property decisions, OEM verification, orders, or payouts.

Keep call recordings/transcripts, SMS/MMS bodies, technician photos, property images, customer addresses, provider identifiers, live database rows, Storage objects, invoices, payout statements, and backups outside Git. Record schema and dependency versions in the transfer manifest. A fully local migration must use encrypted access-controlled database/object backups, checksums, RLS/object-policy tests, provider reauthorization, and a rehearsed rollback.

Property imagery is operational context only. It must never support wealth, income, protected-trait, creditworthiness, price-sensitivity, eligibility, prioritization, or pricing inference.

## Optional Granite GitHub agent

The optional service in `Dockerfile.granite-github-agent` and the `github-agent` Compose profile connects Granite to repositories selected by each user through a GitHub App. It replaces the single-user `gh` login assumption with per-user GitHub authorization, encrypted expiring tokens, isolated repository clones, one-time approval screens, and an encrypted tamper-evident audit trail.

Follow `docs/granite-github-agent.md` to create the GitHub App, select minimum permissions, generate three distinct 32-byte keys, and start the service. Store the GitHub App client secret and the data/session/audit keys only in IBM Secrets Manager or OpenShift Secrets. The checked-in environment files contain placeholders only.

The default Compose port is `127.0.0.1:8791`; it is not public. For remote users, add an approved authenticated TLS ingress, use the exact HTTPS callback/public origin, enable secure cookies, and retain Ollama on the private network. Production proxy changes, GitHub App creation, secret injection, and deployment remain separate approval-gated operator actions.

When `GRANITE_CANONICAL_AGENT_URL` is configured, repository coding operations go through the canonical Python agent bound to the selected private clone. Its host-owned patch and verification approvals are surfaced through the gateway and remain bound to the original GitHub repository. The gateway separately owns clone, fetch, commit, push, and draft pull-request actions. One canonical agent process is required per selected clone; never route a repository to an agent bound to a different workspace.

The model can list, read, and diff only inside the repository chosen in the interface. Clone, fetch, write, branch, commit, push, and draft pull-request actions require a fresh one-time approval. Force-push, merge, reset, deletion, arbitrary commands, arbitrary remotes, `.git` access, traversal, and symlink access are not exposed.

## Simple Granite/Ollama import

1. Clone `main` at the reviewed production commit and copy `config/ibm-granite.example.env` to an untracked secret-managed environment file.
2. Start `compose.ibm.yaml` on the IBM host; keep Ollama port 11434 private or loopback-only.
3. Pull the approved pinned Granite model on the IBM host, then record its model name, quantization, source, license, and digest in the deployment record.
4. Point the application's OpenAI-compatible local-AI URL at the private Ollama endpoint and run the repository tests plus a redacted inference smoke test.
5. Connect Supabase and Twilio over TLS initially. Restore live data only from a separately encrypted backup after RLS, Storage policies, credentials, and rollback have been verified.

Another OpenAI-compatible platform may replace Ollama if it preserves the same private-network, authentication, model-provenance, redaction, review, and audit boundaries.
