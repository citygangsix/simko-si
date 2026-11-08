# Local desktop platform work — implementation versus launch readiness

Branch: `cursor/simko-local-platform`. Local only. Nothing pushed, deployed, sent,
purchased, signed, registered, rented, or published. Existing installers were not
rebuilt. Source is staged into `/workspace/simko-si-tauri` using
`tools/sync_desktop_wrapper.py`; the wrapper is not itself a Git repository.

## Per-item status (do not describe the whole app as finished)

1. **Implemented, native acceptance pending:** vault AES-256-GCM + scrypt,
   versioned envelope, authenticated legacy migration on unlock, atomic writes,
   fail-closed bad-password behavior, collision-resistant account filenames,
   serialized writes, opt-in native keychain storage and original-passphrase
   fallback. No real vault was opened/migrated during development; tests use fixtures.
2. **Code complete offline; live mailbox/OAuth acceptance pending:** real TLS SMTP
   465/587 plus offline dev inbox. Email confirm and password reset now work end to
   end in both code paths (dev inbox and SMTP, tested with a fake SMTP server):
   one-time codes are stored only as SHA-256 digests, confirm codes expire in 48 h
   and reset codes in 1 h, a newer code supersedes older ones, reset revokes all
   sessions and marks the email confirmed, `op=resend-confirmation` issues a fresh
   code, mail is throttled to 5 per account per hour, reset responses are identical
   for unknown/provider/known addresses (no account enumeration), the dev inbox is
   written atomically with owner-only permissions, SMTP headers reject CR/LF
   injection and errors expose only an exception class. `SIMKO_DEV_INBOX_ECHO=0`
   stops dev codes being echoed to the local UI (release builds should set it or
   configure SMTP). Google OIDC (system browser, loopback, PKCE S256, state,
   nonce, signed ID-token validation) and the Apple Supabase broker are unchanged
   and still need Joseph's Google OAuth clients / Apple Services ID. No mailbox
   has been configured and no real email was sent.
3. **Sync code robust offline; cloud setup pending:** explicit opt-in Supabase
   authenticated memory upload/pull with a lossless offline queue; only
   `wxvjajecvklfjxppawdx.supabase.co` accepted, user JWT + anon key required,
   append-only conflict variants preserved. Robustness added: corrupt queue files
   are quarantined (never overwritten); every queue row has an id and only
   acknowledged rows are removed; the network is never touched while holding the
   queue lock (notes written mid-sync survive); one sync runs at a time; pulls are
   paginated; an expired access token is refreshed once from
   `SUPABASE_REFRESH_TOKEN` (kept in memory only); failures record health with
   exponential backoff; optional background retries behind
   `SIMKO_MEMORY_SYNC_AUTO=1`. The sync table + RLS is applied (migration
   `simko_memory_sync_rls`, 2026-11-08) and sync is on by default; obtaining the user session (sign-in to Supabase/account linking)
   remains configuration work. Routine ticks and desktop/email notifications are
   wired; app must be open.
4. **Implemented, provider acceptance pending:** xAI Responses web_search with
   source links and image-generation API with bounded base64 image saves to gallery.
   Paid integrations are disabled and require per-action confirmation. Only fake
   transports exercised. No video endpoint/model was added; video remains the
   existing rented GPU ComfyUI/Wan path. Rental-free video conflicts with the rule.
5. **Done for gated local code; release acceptance partial:** named text agents
   run concurrently with peer messages and owner-scoped status. Added offline:
   owner notes to a running group or one agent (`agents/message`, labelled
   `owner`, treated as data), `agents/cancel` (stops further turns, keeps text),
   and the message-bus transcript in `agents/status`. The optional
   Playwright adapter now supports explicit **prepare -> confirm** for fill or
   submit. Tickets bind owner, exact URL, form index, operation and field values;
   expire after 120 seconds; and are consumed atomically once (including failure).
   Confirmation must be literal `owner_confirmed=true`; the confirm API cannot
   replace the action. Ephemeral, scripts-disabled contexts support only simple
   non-sensitive POST forms whose action is the exact approved URL. One exact
   main-frame URL-encoded POST is allowed; other writes and follow-up requests
   are blocked. Fill-only contexts close without sending. No login, private-value,
   payment, hidden-field, cross-target, download or arbitrary-click workflow.
   Real Chromium DOM/typing is tested with **all responses fulfilled locally**;
   no external form was submitted. DNS/network sandbox production audit and native
   packaged-browser acceptance remain; Playwright stays excluded/disabled in the
   frozen release. API confirmation is implemented; no unapproved UI was changed.
6. **Done for scoped offline code; live service integration partial:** existing
   read-only OAuth connectors and escaped report/template exports remain. Imported
   templates can now be explicitly applied per account, stored as append-only
   revisions, and used by agent start (`use_applied_template=true`) without an
   automatic run or credential/tool import. Applied instructions reach each turn;
   the global text model remains authoritative (template model metadata does not
   change it). Agent start still needs paid-API approval and its independent flags.
   Added offline: owner-scoped revision history (`templates/history`) and
   append-only rollback (`templates/rollback`, explicit confirmation).
   Remote team-permission **model** accepts only RS256 authority-signed, expiring,
   increasing-revision snapshots with team membership and per-resource read/use
   ACLs. Every local resource operation revalidates the signature/expiry and role
   within the access transaction; local role changes cannot grant remote rights.
   Revocation takes effect on a newer imported snapshot or expiry. This is a local
   cache/model, NOT a deployed remote content/invitation/ACL-signing service.
   Checkout now has an idempotent owner-scoped **offline Square-shaped mock**,
   receipt reconciliation and test-only signed sandbox entitlements. Only verified
   completed mock receipts can issue them; sandbox claims never grant production
   paid access. `SIMKO_PAYWALL=0`; no Square SDK, live/sandbox network requests,
   actual keys, webhook registration or payment links. The fixture amount is not
   an approved commercial price. Production checkout/entitlement authority, remote
   transport and server-side quota/ACL enforcement still require separate work and
   Joseph's approval. Local files are not a tamper-proof billing authority.
7. **Done as deliberately disabled framework:** provider contract, E.164 validation,
   duration/budget gate and owner-scoped expiring single-use approval tickets.
   No real adapter, phone account or call. Runtime API exposes status only, not dial.
   Provider-side duration/spend caps must be proven before enabling any real adapter.
8. **Partial — free preparation done; signed releases blocked:** Mac app/DMG,
   universal target and Windows signing placeholders retained. Added a read-only
   `tools/release_preflight.py` audit of targets, scripts, null signing identities
   and disabled flags, plus an explicit release-evidence checklist in `SIGNING.md`.
   Both committed snapshots and staged wrapper pass. No installer rebuild, Mac
   build, certificate purchase, signing, notarization, registration or publication.

## Owner-approved default-on features (Joseph, 2026-11-08 7:43 AM ET)

`podcoder/feature_defaults.py` turns these on at app start (repo server `main()`
and the Tauri backend); an explicit `SIMKO_<FLAG>=0` still disables one:
memory sync + background retries (`MEMORY_SYNC`, `MEMORY_SYNC_AUTO`), cited Grok
web search and prompt images (`PAID_API_ENABLED`; each call still needs
`approve_paid=true`; images cost money per image), multi-agent work (`AGENTS`),
routines (`ROUTINES`) and their desktop notifications (`NOTIFICATIONS`).
Approval cards were already always on. These routes are now reachable by API
without the unapproved desktop-lab UI (`SIMKO_PLATFORM_UI` stays 0; no layout
change). Still off: browser, connectors/vault OAuth, calls, paywall, cloud
backup, Apple broker, X search, uploads, running code. The release preflight
enforces that list. The sync table `simko_memory_sync` with RLS was applied as
migration `simko_memory_sync_rls` on wxvjajecvklfjxppawdx (approved). Live sync
still needs a signed-in Supabase user session (`SUPABASE_ACCESS_TOKEN`/refresh
token, `SIMKO_SYNC_LOCAL_USER`); without it sync fails closed and keeps the queue.

## Opt-in settings and preview

All new UI and external integrations default off. For the lab, set
`SIMKO_PLATFORM_UI=1`, start the local server, then open `/desktop-lab.html` or chat.
Alternatively an authenticated `/api/settings` request with
`op=set-feature, name=desktop_lab, enabled=true` enables the lab for that account.
This does not enable paid APIs, browser driving, notifications or connectors.

Other independent flags: `SIMKO_AGENTS`, `SIMKO_BROWSER`, `SIMKO_MEMORY_SYNC`,
`SIMKO_NOTIFICATIONS`, `SIMKO_ROUTINES`, `SIMKO_PAID_API_ENABLED`,
`SIMKO_CONNECTORS`, `SIMKO_CALLS`, `SIMKO_PAYWALL`. Each requires value `1`.
Use `SIMKO_BROWSER_DOMAINS` as an exact comma-separated HTTPS hostname allowlist.
`local-platform.config.example` documents configuration NAMES, never real values.

Install runtime dependencies into an isolated environment from
`podcoder-translator-renter/requirements-desktop.txt`. Optional Playwright is not
installed automatically (nor bundled). Its Chromium download and a production
network/approval audit are separate steps before browser-driving release.
The new confirmation/template/ACL/mock-checkout API contracts are documented in
`LOCAL_PLATFORM_API.md`; no UI change was made without sign-off.

## Cross-platform verification boundaries

- Linux: Python unit/integration and existing Playwright regression suite, loopback
  HTTP and mocked provider transports. Wrapper raw-Python module selftest passes.
- Windows/macOS: data-directory branches, keychain backend selection/fallback, and
  notification native fallback dispatch are simulated with monkeypatches only.
  No real Credential Manager, Keychain, toast, osascript, WebView, signing or
  installers were tested. Cross-platform source is NOT native acceptance proof.
- SMTP tests verify TLS before login at 587 and implicit SSL at 465.
- OIDC tests verify local state rejection, PKCE verifier matching and signature,
  issuer, audience, nonce checks using generated test keys, not actual accounts.
- Supabase tests use fake transports: no live DDL, writes or credentials.

## Joseph's remaining actions / approvals

- Approve/configure a sending mailbox. No Hostinger trial was claimed.
- Register Google desktop OIDC and Drive OAuth clients/consent scopes, GitHub OAuth
  app; supply IDs/secrets through env/vault. Complete provider verification if needed.
- Configure Apple Services ID with HTTPS return URL
  `https://wxvjajecvklfjxppawdx.supabase.co/auth/v1/callback`; configure Apple provider
  there and allow desktop loopback return URLs (`http://127.0.0.1:*/callback/**`).
  Approve these cloud auth configuration changes first. Keep Apple signing keys in
  provider configuration, not this app; rotate the Apple OAuth secret every six months.
  Enable `SIMKO_APPLE_SUPABASE=1` only after that setup and native acceptance.
- Item 9 bucket SQL and the memory sync RLS SQL are applied (approved).
- Approve review SQL for the permitted Supabase project, configure authenticated
  user/session and local-account mapping; never use service_role or the other project.
- Approve any paid xAI API usage before enabling it. Provide XAI key through env/vault.
- Production checkout/entitlement issuance, a trusted remote ACL-signing service,
  remote content/invitation transport and server-side enforcement remain engineering
  dependencies; offline mocks/local enforcement are not substitutes for these services.
- Sign off preview screens; perform Acer acceptance. Approve a Mac rental budget
  and Apple $99/year enrollment if desired; choose/approve a Windows signing quote.
  Register/verify store publisher identities personally and approve submissions.
- A phone provider, caller identity, usage budget and legal/consent constraints need
  approval before real call-adapter work; no service is provisioned.

## Mockup capture note

The actual UI is served at `/desktop-lab.html`. Headless `google-chrome --screenshot`
was attempted against the loopback server for 1440px and 390px, but Chrome hung
without writing PNGs (including a bounded 45-second retry). No screenshot is being
represented as produced. Capture must be retried through a working local test
browser. Source HTML and the configured mockup server state are retained under
`/workspace/simko-local-platform-mockups/`; no account data is in that fixture.

## Item 9 — Full encrypted cloud backup and restore (CODE DONE, flag off; bucket NOT live)

Green light given 2026-11-08 (via Career relay / parent). Module `podcoder/cloud_backup.py`,
behind `SIMKO_CLOUD_BACKUP=1` (default off; release preflight requires it off).

- Bundles one account's chats, memories, routines, settings and its already
  encrypted vault file. Encrypted on the device: scrypt (N=2^15, r=8, p=1, random
  16-byte salt) -> AES-256-GCM, per-chunk random nonce, AAD binds backup id,
  chunk index and count. The passphrase (min 12 chars) and key are never stored
  or uploaded. A sealed index (bundle SHA-256 and chunk hashes) authenticates
  the manifest; wrong passphrase or any tampering fails closed before any local
  write.
- Chunked (4 MiB) upload to private bucket `simko-backups` on project
  wxvjajecvklfjxppawdx only, as the signed-in user, under `<auth.uid()>/<backup_id>/`;
  the manifest uploads last as the commit marker; objects are never overwritten.
- Lossless offline queue: the full encrypted backup is written atomically to a
  local outbox first; uploads resume per chunk; the outbox entry is retired only
  after the manifest is acknowledged; background retries use backoff and need no
  passphrase. Offline restore can use this device's queued copy.
- List and pick: `backup/list` shows complete cloud backups, incomplete uploads
  and local queued ones. `backup/verify` is a dry-run integrity check.
  `backup/restore` needs `owner_confirmed=true`, takes a local pre-restore
  snapshot, then merges without loss: newer chat wins in place and the other copy
  is kept; memory/routine conflicts kept as variants; a differing vault or
  settings file stays local with the backup copy saved beside it.
- Tests (fake Storage + fake Supabase REST): round trip, fresh-profile restore,
  wrong passphrase, chunk and manifest tampering, offline queue/resume after crash,
  per-user isolation, identity mapping, flag off means no upload, API gating,
  other-project refusal.
- Not done: automatic backup *creation* on change (needs a remembered
  passphrase; only queued uploads retry automatically); UI (no layout change
  without sign-off; API only).
- SQL: `supabase/item9_backup_bucket.sql` (private bucket, 8 MiB limit,
  select/insert/delete only in the caller's own `auth.uid()` folder, no update).
  **Applied 2026-11-08 7:41 AM ET** (Joseph approved; project restored to
  ACTIVE_HEALTHY) as migration `item9_simko_backups_bucket` (version
  20261108124159) on wxvjajecvklfjxppawdx only. Verified read-only: bucket
  private (`public=false`, 8 MiB, octet-stream), three own-folder policies
  (select/insert/delete, authenticated). Security advisor: no findings for
  storage/the bucket. No objects uploaded; flag still off in the app.
