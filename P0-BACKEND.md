# P0 backend: projects, saved files, scheduled tasks, MCP connectors

Branch `cursor/simkosi-p0-backend` (from `wip/asc-features` 7a76dba). Nothing here is deployed.
Every feature is behind its own `platform` flag, and each flag is **off** by default. Turning a flag off makes all of that feature's ops answer 404.

## Conventions followed

- All ops go through `POST /api/platform` with `{op, ...}`.
  - The request passes the same `simko_require_post_json()` check as every other op: POST only, a same-origin Origin/Referer check (CSRF), and a JSON body.
  - `simko_require_user()` reads the session from the cookie `simko`, body `token`, or a Bearer header.
- Tables are add-only. Each module creates its own with `CREATE TABLE IF NOT EXISTS` inside `simko_<feature>_migrate()`, which has a static guard.
  - The tables appear the first time a feature is used, and only once its flag is on.
  - The one new column is `chats.project_id`, added with `simko_add_column`; it is on the allow-list.
- Every row is read with `user_id = ?`. Another account's id answers **404**.
- xAI calls are made only for accounts that may use Grok (`simko_api_key()` / `simko_can_use_grok`). Task runs check the daily spend caps first and skip without calling xAI when over.
- MCP bearer tokens are sealed with the existing connector envelope (`connectors.token_key`, libsodium secretbox) and are never returned by any op.

## Tables

| Table | Purpose |
|---|---|
| `library_files` | Saved files (id, user_id, name, mime, kind, bytes, sha256, xai_file_id, use_count, created_at, last_used_at). Bytes are stored in `simkosi-private/data/library/u<id>/`. |
| `message_files` | Which saved file was used in which chat. |
| `projects`, `project_files` | Projects (name, instructions, collection_id) and the library files in each one. |
| `tasks`, `task_runs` | Scheduled prompts and their run history (status delivered / failed / skipped_cap / skipped_access / missed). |
| `mcp_servers`, `mcp_tools` | Remote MCP servers (url, host, sealed token) and their tools (kind read/write, allowed). |

## Ops (all `POST /api/platform`, signed in, same-origin)

| op | Purpose | Extra auth |
|---|---|---|
| library-list `{q?, kind?}` | List saved files and usage | owner of rows |
| library-save `{name, data(base64)}` | Save once: upload to xAI Files, dedupe by sha256 | Grok user; 60/h |
| library-rename `{file_id, name}` | Rename | owner (404) |
| library-delete `{file_id}` | Delete locally, from xAI Files, and from every project | owner (404) |
| project-list | List projects | |
| project-get `{project_id}` | Project with its files and chats | owner (404) |
| project-save `{id?, name, instructions}` | Create or edit | owner (404) |
| project-delete `{project_id}` | Delete the project and its collection; its chats are kept | owner (404) |
| project-file-add `{project_id, file_id}` | Add a library file to the project's xAI Collection | owner of both (404); Grok user |
| project-file-remove `{project_id, file_id}` | Remove from the collection | owner (404) |
| project-chat-assign `{chat_id, project_id\|0}` | Move a chat into or out of a project | owner of both (404) |
| task-list | List tasks | |
| task-save `{id?, name, prompt, freq, weekday?, run_date?, hour, minute, tz, deliver_push?, deliver_email?, use_search?, enabled?}` | Create or edit. Saved **paused**; with enabled on (default) it returns a `task-start` card. A rename on an approved task keeps it on; a prompt or schedule edit pauses it and needs a new card | Grok user; owner (404) |
| task-toggle `{task_id, enabled, approval_id?}` | Pause (never gated) or resume (a `task-start` card; call again with the approved `approval_id` to run it once) | owner (404) |
| task-delete `{task_id}` | Delete with its history | owner (404) |
| task-runs `{task_id}` | Last 30 runs | owner (404) |
| task-run-now `{task_id, approval_id?}` | Run once now: a `task-start` card first; with the approved `approval_id` it runs once | owner (404); Grok user; 5/h |
| mcp-list | Servers and tools (never tokens), plus the allow-list | |
| mcp-check `{url, bearer_token?}` | Probe and list tools without saving | Grok user; 30/h |
| mcp-save `{label, url, bearer_token?}` | Connect, list tools, seal the token | Grok user; 30/h |
| mcp-refresh `{server_id}` | List tools again, keeping on/off choices | owner (404) |
| mcp-tools `{server_id, tools:{name:bool}, enabled?}` | Turn tools or the server on or off | owner (404) |
| mcp-delete `{server_id}` | Disconnect | owner (404) |
| mcp-hosts | Read the allow-list | **site owner only** (403) |
| mcp-hosts-save `{hosts:[...]}` | Set the in-app allow-list | **site owner only** (403) |

## Chat additions (`POST /api/simco/turn`)

- `project_id`: adds the project's instructions to the system prompt. When the project has files, it also adds `{"type":"file_search","vector_store_ids":[collection_id]}`. Responses path only.
- `library_file_ids` (up to 4): adds `input_file` / `input_image` parts that reference the xAI file id. These need `platform.search` (the Responses path).
- MCP:
  - Allowed **read** tools (those with `annotations.readOnlyHint=true`) are sent as xAI `{"type":"mcp", server_url, server_label, allowed_tools, headers.Authorization}`.
  - Allowed **write** tools become our own function tools named `mcp_<server>_<tool>`. A call creates an `mcp-write` approval.
  - After Approve, the next turn with `approval_id` runs `tools/call` once from this server. It re-checks the owner, the allow-list and that the tool is still allowed, and logs to audit_log.
  - Write tools are never given to xAI's mcp tool, because xAI has no `require_approval`.

## Caps (config, defaults)

`library` max_file_mb 25 / max_total_mb 200 / max_files 200 · `projects` max_projects 50 / max_files 20 ·
`tasks` max_per_user 5 / run_now_per_hour 5 · `mcp` max_servers 10 / max_tools 50.

## MCP safety

- Hosts must be on the allow-list: config `mcp.allowed_hosts` plus the site setting, which only the site owner can edit. `*.example.com` allows subdomains.
- URLs must be https and cannot contain user:pass.
- Every resolved IP must be public, and the request is pinned to that IP with CURLOPT_RESOLVE.
- Redirects are not followed, replies are capped at 2 MB, and timeouts are 25 s.

## Scheduled tasks worker

The existing cron line runs tasks too, because `routines-worker.php` now calls `simko_tasks_run()`, which does nothing while the flag is off. `tasks-worker.php` runs tasks on their own.
Missed runs older than 6 h are recorded as `missed` without an xAI call.

## Tests (all xAI calls mocked)

`tests/mock-xai-p0.php` covers Files, Collections, and Responses with file_search, mcp and input_file. `tests/fake-mcp.php` is a Streamable HTTP MCP server with read and write tools; it uses an SSE reply for tools/call.

```
php tests/platform-40-library.php
php tests/platform-41-projects.php
php tests/platform-42-tasks.php
php tests/platform-43-mcp.php
```

## In-chat approval cards (Nov 24, 2026)

Spec: `simkosi-ops/p0-backend/APPROVAL-PROMPT-SPEC.md`. The front end stays chat + New Chat. A sensitive action shows a Yes/No card inline under the reply that asked for it, and it never runs before Yes.

### How a card works

- **Create.** `simko_approval_create()` (approvals.php) adds a `pending` row to `approvals`.
  - The card's display facts (`title`, `what`, `cost_usd`/`cost_unit`, `where`, `facts`) and its chat (`_session`) are stored inside the row's JSON `payload`. No new column.
  - `simko_guard_approval()` uses it and stops the turn with `{approval: card}`.
  - Cards that don't stop the turn (the token card) come back in the reply as `approvals: [card]`.
- **Card shape.** `id, action, status (pending|approved|declined|expired), title, what, facts[], cost_label` ("About $0.020 per run x 1 run/day · $4.98 of today's $5.00 left", or "Free"), `cap_left_usd, where, session_id, created_at, expires_at, result`.
- **Yes.** `decide` → the next `/api/simco/turn` with `approval_id` runs the action's `*_apply_approved()` exactly once.
  - `simko_approval_claim()` writes "Ran approval N: …" to audit_log inside a `BEGIN IMMEDIATE` transaction. A second Yes, a replayed turn, or two turns at once never run it again.
  - `decide` itself is atomic (`UPDATE … WHERE status='pending'`).
  - The turn returns `approval_result` (the chip text) and `approval_card`.
- **No.** Nothing runs. For 30 minutes, later turns in that chat tell Grok "The person tapped No on these … do not try again".
- **Expiry.** A pending card older than 24 h (checked from `created_at`) is `expired`. `decide` answers **410** `{expired: true}`, and the chat shows "Expired, ask again".
- **Approvals flag off.** Gated actions refuse; they never run ungated. A task can still be saved paused.
- **UI** (`index.html` `#approvalCards` + `<template id="chatApprovalTpl">`, `simco-app.js` `showChatApproval`):
  - Each card shows title, what happens, cost + cap left, where, and Yes/No buttons.
  - After a decision it collapses to "Approved, ran: <result>" or "Declined, nothing ran".
  - Pending cards re-render when a chat is reopened (`approvals-pending`).
  - The ask and the result are saved in the chat, so cards stay under their reply when the chat is redrawn.

### Actions

| action | Made by | Yes does | Apply |
|---|---|---|---|
| `task-start` | task-save (enabled on), task-toggle on, task-run-now, Grok tool `create_task` | enable (mode `enable`), run once (`run`), or create+enable (`create`) | `simko_task_apply_approval` / `simko_tasks_apply_approved` (tasks.php). Re-checks owner, flag, caps, and that the prompt+schedule fingerprint is the one approved |
| `mcp-spend` | a connector call with a cost: a host in `mcp.paid_hosts` (USD per call), or reads when `mcp.xai_tool_fee_usd` > `mcp.spend_threshold_usd` (default 0.01) | runs `tools/call` once from our server and adds the cost to today's spend | `simko_mcp_apply_approved` (also `mcp-write`). A paid write is **one** card with facts "Changes something" + "Costs money". Paid servers' reads are never handed to xAI's mcp tool; they become function tools that ask first. Checks the cap left before running |
| `paywall-on` | owner: op `paywall-set {on:true}` or Grok tool `turn_paywall_on` (offered to owners only) | sets the paywall flag | `simko_paywall_apply_approval` (paywall-switch.php). Card: price (`billing.price_label`, default $9.99/month), 5 free messages, Stripe mode test/live + account last 4 only (from config, never calls Stripe), non-owner count. Other accounts never see it, can't decide it (404), and can't ask for it (403) |
| `mcp-token-share` | first chat turn where a connector with a login token would get read tools; again when the token changes (sha256 fingerprint) | logs `mcp-token-consent: <server>` to audit_log; read tools are offered from then on | decided at `decide`; `simko_mcp_token_apply_approved` on the next turn. No: the connector stays connected, its read tools are not offered, and it doesn't ask again for that token. Writes still go through our server after Yes |

### Paywall setting storage

The smallest storage that works is the existing additive `site_settings` key/value table (bootstrap, `CREATE TABLE IF NOT EXISTS`), key `flag_paywall` (JSON bool). There is no new table and no destructive change.
- `simko_flag()` reads the stored value first for switchable flags (only `paywall`), with config `platform.paywall` as the fallback.
- If the database file isn't there yet, it uses config.
- `paywall-set {on:false}` (owner) turns it off without a card.

### New ops (`POST /api/platform`)

| op | Purpose | Auth |
|---|---|---|
| approvals-pending `{session_id?}` | Pending/expired cards for a chat (cards with no chat show everywhere). paywall-on only for an owner | signed in; approvals flag |
| paywall-set `{on, approval_id?}` | on: paywall-on card, or apply the approved card once; off: right away | **owner only** (403) |
| decide (changed) | 410 when expired; paywall-on only for an owner; Yes on mcp-token-share logs consent | |

### Tests

- `tests/platform-44-approval-cards.php`: pending rows, Yes runs once, double Yes doesn't rerun, No runs nothing, expired can't be approved, non-owner can't see or decide paywall-on, token consent shown once and again on a new token, the combined spend card, approvals off refuses, and the xAI fee threshold.
- `platform-42-tasks.php` and `platform-43-mcp.php` were updated for the new gates.
- The mock (`tests/mock-xai-p0.php`) answers `TASKCREATE`, `PAYWALLON` and `MCPREAD` with function calls.
- UI: `node tests/approval-cards-ui.mjs [outDir]` runs a real mouse-and-keyboard check against a local `php -S` with a mocked xAI and a fake MCP. It clicks Yes and No on every card type, checks reopen and expiry, and saves screenshots.
