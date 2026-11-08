# OG RAW Frontier AI

React + Vite frontend for the OG RAW site and owner dashboard.

## Local Dev Server Reuse

Use the reusable dev-server wrapper instead of repeatedly starting `npm run dev` in new terminals:

```bash
npm run dev:ensure
npm run dev:status
npm run dev:logs
npm run dev:stop
```

`dev:ensure` checks existing localhost servers first, starting with the app's Vite port `http://127.0.0.1:8080/`. If a usable server is already running, it reuses that URL and does not restart anything. If nothing is available, it starts one detached Vite dev server, records its PID in `.dev-server/vite-dev-server.json`, and writes logs to `logs/dev-server/`. `dev:stop` only stops the managed server it started; it will not kill unrelated localhost processes.

## Low-Lag Coding Workflow

Use the named workflow commands instead of ad hoc terminal snippets. They keep approvals reusable, reuse running services, prefer cached status, and keep heavier work behind explicit commands.

Fast daily loop:

```bash
npm run dev:ensure
npm run verify:fast
npm run frontend:smoke
npm run frontend:visual-smoke
npm run project:doctor
```

Preview and status:

```bash
npm run preview:url
npm run preview:open
npm run services:ensure
npm run workspace:status
npm run services:status
npm run stale:check
npm run logs:summary
```

Long or heavy jobs should run detached and CPU-friendly:

```bash
npm run job:start -- npm run verify:full
npm run job:list
npm run job:status -- <job-id>
npm run job:logs -- <job-id>
```

Cloud/off-machine heavy jobs:

```bash
npm run cloud:job
npm run cloud:job:dispatch -- --command="npm run verify:full"
npm run cloud:job:dispatch:apply -- --command="npm run verify:full"
```

Idle-time queue for intentionally deferred heavy work:

```bash
npm run idle:queue:add -- --command="npm run verify:full" --reason="Run full verification off-hours"
npm run idle:queue
npm run idle:queue:flush
npm run idle:queue:flush:apply
```

Release and deploy flow:

```bash
npm run build:smart:dry-run
npm run build:smart
npm run release:check
npm run deploy:queue:add -- --command="npm run frontier:deploy-transcription" --reason="Frontier transcription workflow update"
npm run deploy:queue:flush
npm run deploy:queue:flush:apply
```

Maintenance:

```bash
npm run verify:baseline:status
npm run verify:baseline:update
npm run local-ai:guard
npm run local-ai:guard:apply
npm run artemis:browser:inspect -- --url=http://127.0.0.1:8080/
npm run artemis:browser:tabs:minimize
npm run cleanup:safe
npm run cleanup:safe:apply
npm run artemis:ui-automation:policy
```

Operating rules:
- Prefer `verify:fast` and changed-file tests before full builds.
- Use `verify:full`, `release:check`, and bundle-size checks for release/deploy decisions.
- Reuse Vite, Artemis API, and Hermes Hands ports instead of starting duplicate watchers.
- Keep local AI analysis off unless explicitly needed; use smaller local models or hosted execution when the Mac is under load.
- Let `local-ai:guard:apply` write the local AI policy before heavy work; Artemis/Omega scripts read it and disable local AI when the Mac is under load.
- Schedule heavy transcription, build, and indexing work for idle time, or run it through `job:start` so it is detached and summarized.
- Artemis UI automation may scroll, click, and fill ordinary local Chrome UI through `artemis:browser:*`, but it refuses safety approval prompts, payment flows, destructive actions, or external sends.
- Group deploys with the deploy queue instead of deploying after every small edit.
- `artemis:hands` and `artemis:api` are reuse-first commands now. Use `artemis:hands:raw` or `artemis:api:raw` only for low-level debugging.

## Profile Ingestion

The owner dashboard supports bulk ingest from a single YouTube profile URL through the `frontier-profile-ingest` Supabase Edge Function.

Flow:
- Paste a YouTube profile or channel URL into the owner dashboard.
- Click `Add to pipeline`.
- The frontend creates or resumes a persistent ingest job in Supabase.
- Choose a source rights policy:
  - `captions_only` for third-party public channels
  - `approved_for_transcription` only for channels you own or have explicit permission to download/transcribe
- The edge function resolves the channel, paginates the uploads playlist one video at a time, stores processed videos in database tables, reports completion-based percentage progress, and resumes from the saved checkpoint on the next run.
- Prompt runs can now search the stored Supabase library directly, so you can ingest first and then query the saved database with one prompt from the dashboard.
- Transcript text is stored when YouTube captions are available.
- Videos without captions fall back to title + description metadata by default.
- Approved sources also create durable fallback transcription tasks in `frontier_transcription_tasks` so a later worker can turn missing-caption videos into stored transcripts.
- The repo now includes a local transcription worker for approved sources, powered by `yt-dlp`, `ffmpeg`, and OpenAI transcription.
- If a source is switched back to `captions_only`, pending fallback transcription tasks are cancelled automatically.

Owner dashboard route:
- `/ownersdashboard`
- legacy fallback: `/ownersdashboard5615641545`

## Required Frontend Env Vars

Create `.env.local` from `.env.example`.

Required for the live app:
- `VITE_SUPABASE_URL`
- `VITE_SUPABASE_PUBLISHABLE_KEY`

Optional owner auth values:
- `VITE_OWNER_EMAIL_HASH`
- `VITE_OWNER_PASSWORD_HASH`
- `VITE_OWNER_RECOVERY_HINT`

Optional Omega local model defaults:
- `VITE_OMEGA_OLLAMA_BASE_URL`
  - defaults to `http://localhost:11434`
- `VITE_OMEGA_OLLAMA_MODEL`
  - defaults to `omega-local`

Optional hosted OpenAI fallback switch:
- `VITE_ENABLE_OPENAI_FALLBACK=true`
  - default is off
  - also requires the `OPENAI_API_KEY` Supabase secret for the `ai-health-coach` Edge Function

If the Supabase values are missing, the app now stays usable in local-first browser mode: pasted/uploaded transcript files are indexed in local storage, Omega can chat with local browser fallbacks, and the dashboard shows exactly which hosted features are waiting on env keys. You need the Supabase env values for YouTube profile ingest, stored database search, Edge Function fallback answers, and resumable cloud state.

OpenAI chat fallback is intentionally disabled unless `VITE_ENABLE_OPENAI_FALLBACK=true` is set. This keeps daily use local-first and prevents the UI from implying a paid fallback is active when the key/secret is not configured.

## Artemis SignalWire Owner Communication

Artemis uses SignalWire as the only active real communication provider for now, through Twilio-compatible routes and file names. It is owner-only: calls and texts go only to `ARTEMIS_OWNER_PHONE` unless a future allowlist policy explicitly expands that.

Required local env:

```bash
ARTEMIS_PHONE_PROVIDER=signalwire
TWILIO_COMPATIBLE_API_BASE_URL=https://YOUR_SPACE.signalwire.com/api/laml/2010-04-01
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_FROM_NUMBER=
ARTEMIS_OWNER_PHONE=
```

Test command:

```bash
npm run artemis:test-call
```

Safety defaults:
- Calls only `ARTEMIS_OWNER_PHONE`.
- SMS/MMS/call queues are owner-only and approval-gated.
- Arbitrary destination numbers are intentionally blocked.
- Outbound voice is `tier_4_external_action` and requires approval, except the explicit owner test command.
- The local endpoint is `POST /api/artemis/twilio/call-owner` on `npm run artemis:api`; it requires `approvalStatus: "owner_approved"` or `testMode: true`.
- Telegram, WhatsApp, email, and push remain disabled placeholders.

## Artemis Communication OS

Artemis now has a local-first Communication OS foundation for channel status, unified inbox, personal assistant workflows, reminders, contacts, trusted devices, call logs, onboarding checks, and plugin validation.

```bash
npm run artemis:channels
npm run artemis:owner-loop
npm run artemis:onboard
npm run artemis -- personal-os summary
npm run artemis -- owner-loop ingest "Owner instruction to turn into a task"
npm run artemis -- assistant "show everything I missed today"
npm run artemis -- devices list
npm run artemis -- calls log
npm run artemis -- plugins list
```

The app includes an Artemis Unified Inbox panel in the Omega/Agent Workspace. Start the local API first:

```bash
npm run artemis:api
```

Full docs: `docs/artemis-personal-communication-os.md`.

Owner dashboard sign-in uses SHA-256 hashes. Generate values locally, then place the hashes in `.env.local`:

```bash
node --input-type=module -e "const [v]=process.argv.slice(1); const b=await crypto.subtle.digest('SHA-256', new TextEncoder().encode(v)); console.log([...new Uint8Array(b)].map(x=>x.toString(16).padStart(2,'0')).join(''))" "owner@example.com"
```

Run the same command with your password string for `VITE_OWNER_PASSWORD_HASH`.

## Required Supabase Secret

Create `supabase/.env.local` from `supabase/.env.example` for local function serving.

Required function secret:
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `YOUTUBE_API_KEY`

Optional function secret:
- `OPENAI_API_KEY`
  - lets the hosted `frontier-profile-ingest` function process queued approved-source fallback transcription tasks one at a time after the channel crawl reaches the end
  - hosted transcription uses OpenAI audio transcription for approved sources only and keeps the same `captions_only` safety default for public third-party channels
  - the local worker is still recommended for longer videos because it converts audio to smaller mono mp3 chunks before upload so long episodes can transcribe incrementally

For hosted deployment, set the same secret in Supabase:

```bash
supabase secrets set --project-ref nexkymqahpkvzzlvivfi YOUTUBE_API_KEY=your_youtube_data_api_v3_key
```

## Local Development

Install dependencies:

```bash
npm install
```

Run the frontend:

```bash
npm run dev
```

Run the approved-source transcription worker:

```bash
cp .env.worker.example .env.worker.local
set -a
source ./.env.worker.local
npm run frontier:transcription-worker
```

Start this worker before or during a large approved-source channel ingest. The dashboard can keep crawling the channel while the worker immediately claims newly queued transcription tasks, so it does not need to wait for the full video catalog to finish.

Worker safety defaults:
- Third-party YouTube/source videos stay `captions_only` unless the source is owned, licensed, public-domain, or explicitly approved in writing.
- `WORKER_SEGMENT_SECONDS=300` keeps audio chunks smaller, so long videos are processed in gentler pieces.
- `WORKER_CONCURRENCY=1` transcribes one claimed video at a time. Raise carefully only after confirming OpenAI cost/rate limits and your Mac can handle parallel downloads/transcodes.
- `WORKER_CHUNK_CONCURRENCY=1` transcribes one chunk at a time, which is slower but keeps the computer responsive.
- `WHISPER_THREADS=2`, `WORKER_CHILD_NICE_LEVEL=15`, and `WORKER_CHUNK_COOLDOWN_MS=750` keep local Whisper/ffmpeg work in the background instead of saturating the machine.
- `ENABLE_AI_ANALYSIS_AFTER_DOWNLOAD=false` skips optional local Ollama analysis after transcription; quote retrieval uses the saved transcript text directly.
- The worker safely reclaims abandoned `processing` tasks older than two hours, so a crashed run does not leave videos stuck forever.
- `WORKER_RETRY_FAILED=false` prevents failed transcription tasks from being retried in a loop. Set it to `true` only after fixing the failure reason and intentionally retrying.
- `WORKER_RETRY_FAILED_AFTER_MINUTES=60` keeps retry-enabled workers from hammering the same failed video immediately after another failure. Set it lower only for a deliberate supervised retry.
- The background worker launcher reads `.env.worker.local`, and one-off shell values can override it for supervised retries.

Less-clicky Frontier maintenance commands:

```bash
npm run frontier:doctor:local
npm run frontier:doctor
npm run frontier:verify-quotes
npm run frontier:normalize-transcripts
npm run frontier:normalize-transcripts:apply
npm run frontier:checks
npm run frontier:deploy-transcription:dry-run
npm run frontier:deploy-transcription
npm run frontier:worker:ensure
npm run frontier:transcription:maintain:dry-run
npm run frontier:transcription:maintain
```

Use the dry-run commands first when you want a no-write summary. The `:apply` and deploy commands are idempotent: they compare the current database rows before updating, avoid destructive cleanup, and keep the worker running through the background supervisor instead of restarting it unnecessarily. `frontier:transcription:maintain` is the bundled path for one approval-style workflow: local checks, quote metadata normalization, Edge Function deploy, worker ensure, and doctor summary.

Artemis ingestion controls:

```bash
npm run artemis -- ingestion status
npm run artemis -- ingestion crawl "https://www.youtube.com/@joerogan" --rights=captions_only
npm run artemis -- ingestion ensure
npm run artemis -- ingestion pause-retries
npm run artemis -- ingestion install-daemon
```

`ingestion crawl` starts a detached approved-source catalog crawl. `captions_only` is the default for third-party sources: Artemis saves public captions/metadata for search and does not download source audio/video. `ingestion ensure` starts one background worker with Chrome cookies, local Whisper, keep-awake, failed retries off, and profile catalog crawling on. `ingestion install-daemon` installs a local LaunchAgent that checks every five minutes and starts the worker only if it is missing, so the Safari dashboard tab is not required to keep digestion moving.

If YouTube blocks `yt-dlp` with "Sign in to confirm you're not a bot", run the worker with logged-in YouTube cookies from a browser session you control:

```bash
set -a
source ./.env.worker.local
set +a
YTDLP_COOKIES_FROM_BROWSER=chrome WORKER_RETRY_FAILED=true WORKER_CONCURRENCY=1 WORKER_CHUNK_CONCURRENCY=1 WHISPER_THREADS=2 WORKER_CHILD_NICE_LEVEL=15 npm run frontier:transcription-worker
```

You can also export a logged-in YouTube session to a local Netscape-format `cookies.txt` file, keep that file private, and pass it with `YTDLP_COOKIES_FILE="/absolute/path/to/youtube-cookies.txt"`. Never paste cookie contents into chat, commits, docs, or `.env` files.

## Omega Local Saver Mode

When the user opens Omega, the app can now prompt them to install a local worker so approved-source media downloads and transcription run on their own computer instead of leaning harder on hosted processing.

Recommended Mac setup:

```bash
brew install yt-dlp ffmpeg
cp .env.worker.example .env.worker.local
```

Then set the needed value in `.env.worker.local`:

```bash
OPENAI_API_KEY=your_openai_api_key
```

Then start the local worker:

```bash
set -a
source ./.env.worker.local
npm run frontier:transcription-worker
```

Use this only for sources you own or have explicit permission to download and transcribe. Public third-party channels should remain in `captions_only` mode.

## Omega Execution Modes

The Multi-Mentor workspace now exposes three execution modes for the multi-agent feature:

- `Local`: prefer the user's computer first, run swarm drafts in parallel browser workers, and lean on local software for approved-source media work.
- `Hybrid`: balance local device execution with hosted retrieval/storage.
- `Cloud`: prefer hosted services when available, with browser fallback if no hosted agent runtime exists.

The current implementation uses the browser plus local worker path most heavily. It does not yet ship a full on-device LLM runtime, but it now detects device capability, lets the user choose local/cloud behavior, and can run a parallel local Omega swarm across active agents.

If you want Omega to use a model running on the user's computer for actual replies, point the local execution mode at a local endpoint such as Ollama:

```bash
brew install ollama
ollama serve
ollama create omega-local -f Modelfile
ollama create omega-codex -f ollama/Modelfile.omega-codex
```

Then configure Omega with:

- Provider: `Ollama`
- Base URL: `http://localhost:11434`
- Model: `omega-local` for normal Omega chat and swarm work
- Model: `omega-codex` for coding, debugging, and repo-focused execution

With that enabled, Omega can use the local endpoint for active-agent chat replies and swarm runs, while still falling back safely if the endpoint is unavailable.

If you want your own custom Omega model lineup instead of one generic model, the repo now includes an Ollama model pack in [ollama/README.md](/Users/xxx/Downloads/OG%20RAW%20frontier%20ai/ollama/README.md) with:

- `omega-local`
- `omega-ceo`
- `omega-coo`
- `omega-cmo`
- `omega-sales`
- `omega-codex`

Build them all with:

```bash
bash scripts/create-omega-ollama-models.sh
```

Build just the execution-focused coding agent with:

```bash
ollama create omega-codex -f ollama/Modelfile.omega-codex
```

The worker can derive the Supabase service role key from your logged-in Supabase CLI session, so `.env.worker.local` only needs the OpenAI key unless you want to override the project manually.

## Artemis Hands Autonomous Operator

Artemis Hands is a localhost-only worker that lets Artemis request safe terminal-style actions from the Omega UI. It also supports autonomous missions: long-running local goals that run through a policy file, pause for approvals, keep the Mac awake while running, and report results back into Omega.

Start it in a second terminal from the project root:

```bash
npm run artemis:hands
```

Queue a supervised autonomous coding mission for this project:

```bash
npm run artemis:autocode
```

By default, this tells Artemis to keep coding toward making the live AI Mentor / Frontier screen the central command surface for autonomous work: start missions, monitor runs, review approvals, pause or resume work, and see results from the main interface.

You can narrow the mission:

```bash
npm run artemis:autocode -- --objective "Make the AI Mentor screen central command for Artemis"
```

Artemis can also queue approval-gated SMS, MMS screenshot review texts, and Twilio voice calls from terminal:

```bash
npm run artemis -- advisor-screenshot "http://127.0.0.1:4173/ Please review this screen"
npm run artemis -- approval-ask "latest sms"
npm run artemis -- approval-watch "120"
npm run artemis -- approve "approval-id"
npm run artemis -- mms-send "mms-id"
npm run artemis -- call-send "call-id"
```

Remote approval replies are `1 CODE` to approve once, `2 CODE` to approve and remember the exact Artemis command, and `3 CODE` to reject.

For SignalWire/Twilio-compatible owner delivery, set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `ARTEMIS_OWNER_PHONE`, and either `TWILIO_FROM_NUMBER` or the existing `TWILIO_PHONE_NUMBER`. SMS/MMS/calls stay owner-only and approval-gated; MMS screenshots also need `ARTEMIS_PUBLIC_BASE_URL` set to a public HTTPS URL that serves `/artemis-screenshots`.

Development mode restarts the worker when the server file changes:

```bash
npm run artemis:hands:dev
```

Run the packaged Artemis onboarding flow when you want the setup/status experience in one command:

```bash
artemis onboard
artemis onboard --status
artemis onboard --wizard
artemis onboard --repair
artemis onboard --install-daemon
artemis onboard --uninstall-daemon
artemis onboard --verbose
```

Install the local `artemis` command once for your Mac user:

```bash
npm run artemis:install-command
```

The npm form stays available:

```bash
npm run artemis -- onboard
npm run artemis -- onboard --status
npm run artemis -- onboard --wizard
npm run artemis -- onboard --repair
npm run artemis -- onboard --install-daemon
npm run artemis -- onboard --uninstall-daemon
npm run artemis -- onboard --verbose
```

The onboarding command checks project context, daemon state, readiness, and logs without dumping raw launchd output. `--wizard` returns the guided setup path. `--repair` reports daemon/privacy/path repair actions. `--install-daemon` wraps the launchd install while keeping Artemis local on `127.0.0.1`. Use `--verbose` only when debugging launchd.

Create or check the local Artemis ecosystem starter pack:

```bash
npm run artemis -- ecosystem status
npm run artemis -- ecosystem scaffold
```

This adds public-facing docs under `docs/ecosystem/` and reusable placeholders under `artemis-templates/`. The commands stay local-only: no GitHub publishing, package publishing, deploys, remote network calls, env-file dumps, API keys, tokens, private URLs, or personal contact details.

Check the local plugin registry and public-release skeleton:

```bash
npm run artemis -- plugins status
npm run artemis -- plugins scaffold
```

The registry lives under `artemis-plugins/`, and the private public-release package skeleton lives under `artemis-public/`. No license is selected and nothing is published.

The lower-level launchd commands are still available:

```bash
npm run artemis:hands
npm run artemis:api
npm run artemis:hands:daemon:install
npm run artemis:hands:daemon:status
npm run artemis:hands:daemon:uninstall
```

Default endpoint:

```text
http://127.0.0.1:8765
```

Optional frontend override:

```bash
VITE_HERMES_HANDS_URL=http://127.0.0.1:8765
```

Endpoints:

- `GET /health`
- `GET /capabilities`
- `GET /policy`
- `GET /requests`
- `POST /requests`
- `POST /requests/:id/approve`
- `POST /requests/:id/cancel`
- `GET /missions`
- `POST /missions`
- `POST /missions/:id/pause`
- `POST /missions/:id/resume`
- `POST /missions/:id/cancel`

Default allowed commands:

- `npm run typecheck`
- `npm run build`
- `npm run lint`
- `git status --short`
- `rg`
- `ls`
- `cat`

Default blocked commands include `rm`, `sudo`, `git reset --hard`, recursive `chmod`, shell pipes/redirection, destructive database commands, and sensitive-looking secret/token file reads. Local `npm install` is owner-approved when needed for this project; global/system installs, deploys, git writes, database commands, network commands, env-file changes, and package script edits require local approval before they run.

The worker binds to `127.0.0.1` by default, validates the working directory against the project root, uses `spawn(command, args)` instead of raw shell strings, and stores local state under:

```text
.hermes-hands/requests.json
.hermes-hands/missions.json
.hermes-hands/policy.json
.hermes-hands/daemon.log
```

The first worker start creates `.hermes-hands/policy.json`. Edit that local file to change `alwaysAllow`, `requireApproval`, `alwaysBlock`, `autoApproveIf`, runtime limits, file-change limits, and allowed working directories. Artemis can auto-run allowlisted commands. It can only auto-approve medium-risk commands that you explicitly pre-authorize in `autoApproveIf.commandLines`, and hard-blocked commands cannot be bypassed by any autonomy level.

Autonomy levels:

- Level 0: Manual, suggest actions only.
- Level 1: Safe Auto, run allowlisted checks.
- Level 2: Supervised Coding, coding scope with risky actions paused for approval.
- Level 3: Preapproved Autonomy, medium-risk actions only when policy allows them.
- Level 4: Restricted Unattended, long missions with hard blocks still enforced.

On macOS, mission awake mode uses `caffeinate -dimsu` only while a mission is running. It releases the lock when the mission completes, fails, blocks, or is cancelled. It does not change global power settings.

In the app, open `OMEGA: Multi Mentor` and use the `Artemis Hands` card to see daemon status, awake status, mission queue, approval queue, recent runs, logs, stdout/stderr, changed files, and test/build results. Artemis chat can create Hands requests when you ask it to run typecheck, build, lint, or git status, and can queue autonomous missions when you ask for an Artemis mission or operator run.

### Daily Capability Dashboard

The Omega workspace includes a Frontier capability dashboard backed by Artemis Hands:

```bash
curl --silent --show-error --max-time 5 http://127.0.0.1:8765/capabilities
```

The dashboard reports every daily-use area as `Green`, `Green with approval`, `Green with action`, or `Green with fallback`:

- Local app and Artemis Hands health.
- Frontier transcription worker process count and safety settings.
- Ollama endpoint and installed model discovery.
- OpenAI paid fallback readiness without printing keys.
- Supabase frontend/function env readiness without printing secrets.
- Git repository state or timestamp/size changed-file tracking fallback.
- Browser Use and Computer Use plugin availability with localhost verification fallback.
- Coding adapter, daemon autostart, credential setup, and approval policy state.

The credential setup assistant only reports key presence, official setup URLs, and safe CLI commands. It refuses env dumps, hidden token extraction, browser storage scraping, keychain scraping, and service role exposure.

### Autonomous File Editing

Artemis Hands now includes a local coding adapter at `scripts/hermes-coding-adapter.mjs`.

Because this project does not expose a safe fully automated Codex CLI editing path to the localhost worker, the adapter uses the safest local fallback:

1. A coding mission creates `.hermes-hands/coding-tasks/<task-id>/patch-plan.md`.
2. The adapter creates `.hermes-hands/coding-tasks/<task-id>/approved-changes.example.json`.
3. You review the plan and create `approved-changes.json` with exact approved operations.
4. Artemis queues `node scripts/hermes-coding-adapter.mjs apply <task-id>` as an approval-required mission step.
5. Only after approval, the adapter validates every path, blocks env/secrets/generated/dependency folders, rejects destructive operations, applies only the approved JSON changes, records changed files, then the mission runs typecheck/build/lint verification steps as applicable.

Supported approved operations are `write`, `append`, and exact-once `replace`. Delete, rename, shell execution, dependency installs, git writes, deployments, database writes, and env-file writes are not supported by this adapter. High-risk files such as package scripts, Supabase files, and server scripts require both the Omega approval and `allowRiskyWrites: true` in `approved-changes.json`.

Changed-file tracking uses `git status --short` when a git repository exists. If this folder has no git repository, Artemis records a file timestamp/size baseline at mission start and reports changed project files from that baseline. Secret/local env files, generated builds, dependencies, autosave archives, and Artemis internal state are excluded.

## Hosted Readiness Checklist

Before treating hosted/cloud features as ready:

- `.env.local` has `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY`.
- `supabase/.env.local` exists for local function serving and has `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and `YOUTUBE_API_KEY`.
- Supabase migrations have been applied to the target project.
- `frontier-profile-ingest` has been served locally or deployed with the same secrets.
- Stored database search and profile document listing work through `frontier-profile-ingest` actions `search_documents` and `documents`.
- OpenAI fallback remains off unless `VITE_ENABLE_OPENAI_FALLBACK=true` is set and the `OPENAI_API_KEY` Supabase secret is present.
- Approved-source transcription is only used for owned/licensed sources and requires explicit permission plus a configured OpenAI transcription key.

Serve the edge function locally:

```bash
npm run supabase:functions:serve
```

## Deploy The Edge Function

1. Authenticate the Supabase CLI:

```bash
supabase login
```

2. Set the required secret:

```bash
supabase secrets set --project-ref nexkymqahpkvzzlvivfi YOUTUBE_API_KEY=your_youtube_data_api_v3_key
```

3. Deploy the function:

```bash
npm run supabase:functions:deploy
```

The repo already includes `supabase/config.toml` with:
- `project_id = "nexkymqahpkvzzlvivfi"`
- `verify_jwt = false` for `frontier-profile-ingest`

That `verify_jwt = false` setting is required because the browser invokes the function directly with the publishable key.

Approved download/transcription requests are server-gated. Set `APPROVED_TRANSCRIPTION_PROFILE_URLS` in Supabase to a comma-separated list of owned, licensed, public-domain, or written-approved YouTube profile/video URLs before the function will honor `approved_for_transcription`; all other browser requests are downgraded to `captions_only`.

## Verify Joe Rogan Profile Ingest

1. Open the app.
2. Go to `/ownersdashboard`.
3. Paste a Joe Rogan URL such as:

```text
https://www.youtube.com/@joerogan
```

4. Leave the manual transcript field empty.
5. Click `Add to pipeline`.
6. Watch the ingest progress bar update one completed video at a time as the dashboard saves each result to Supabase.
7. Pause and resume to confirm the saved percentage and checkpoint continue from the same job.
8. Switch the source to `Owned / licensed / explicit permission` if you want missing-caption videos queued for fallback transcription instead of staying metadata-only.
9. Keep the local transcription worker running if you want those queued videos downloaded, transcribed, and saved back into Supabase.
10. Run a prompt from the truth-first panel. The dashboard will search the stored Supabase library for matching documents before falling back to browser-only state.

## Current Production Limits

- The edge function currently supports YouTube profile/channel URLs only.
- Transcript quality depends on whether YouTube exposes captions for the video.
- Public third-party channels stay in captions-only mode unless you explicitly mark them as approved for fallback transcription.
- Approved sources now rely on the bundled local transcription worker rather than the edge function for no-caption media downloads.
- Very large channels are resumable because progress and processed videos are stored in Supabase tables. The owner dashboard starts/resumes the job, and the local Artemis worker can continue catalog crawling and approved-source transcription without keeping the browser tab open.
- This implementation stores processed videos in Supabase for durable ingest progress, but the truth-first prompt runner still needs a fuller server-side retrieval path if you want thousands of stored videos searched without browser limits.
