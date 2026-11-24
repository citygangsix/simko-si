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
| task-save `{id?, name, prompt, freq, weekday?, run_date?, hour, minute, tz, deliver_push?, deliver_email?, use_search?}` | Create or edit | Grok user; owner (404) |
| task-toggle `{task_id, enabled}` | Pause or resume | owner (404) |
| task-delete `{task_id}` | Delete with its history | owner (404) |
| task-runs `{task_id}` | Last 30 runs | owner (404) |
| task-run-now `{task_id}` | Run once now | owner (404); Grok user; 5/h |
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
