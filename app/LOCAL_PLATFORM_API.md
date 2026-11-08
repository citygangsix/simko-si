# Resumed local 8: gated API contracts

All routes below require the existing authenticated local platform API, desktop
preview opt-in and POST with the session token. Existing loopback Host/Origin
checks apply. No flag is enabled by this work; no new visible UI is approved.

## Browser (requires `SIMKO_BROWSER=1`, exact HTTPS hostname allowlist)

1. `/api/platform/browser/prepare`: `url`, `fields` (field-name -> text),
   `form_index` (default 0), `operation` (`fill` or `submit`). Returns a confirmation
   preview and `approval_ticket`, expires in 120 seconds. Preparation neither
   navigates nor fills nor submits.
2. Display the exact operation, recipient URL, form index and field values to the
   user and obtain explicit approval. Never auto-confirm from page/agent content.
3. `/api/platform/browser/confirm`: that `approval_ticket`,
   `owner_confirmed: true`. No replacement action parameters are accepted. A denial,
   expiry, execution error or successful action consumes the owner's ticket.
   Cross-account attempts cannot use it. Restart cancels all tickets.

Only text/search inputs and textareas are supported. Every named control must be
approved; hidden/private/payment controls, authentication, cross-target actions,
non-POST forms and non-URL-encoded forms are refused. Form action must equal the
approved page URL. JavaScript, profiles, downloads and service workers are disabled.
Fill is ephemeral (context closes); submit sends at most one exact main-frame POST.
A sent request is not proof of external acceptance; never automatically retry it.
No private fields/values should be passed to these endpoints. Private-value flows
need a separately audited secure workflow. This is not general computer control.

Before packaged release: audit DNS rebinding/TOCTOU and OS-level network isolation,
approval UI, final recipient semantics, packaging and native browser acceptance.

## Templates

- `templates/import` still validates portable JSON; it never runs agents.
- `templates/apply`: `content` (validated imported JSON), `owner_confirmed: true`.
  Appends a per-account active configuration revision, does not overwrite history.
- `templates/active`: returns only the authenticated account's latest revision.
- `agents/start`: `use_applied_template: true`, `task`, `approve_paid: true` uses
  applied names/instructions, still gated by `SIMKO_AGENTS` and
  `SIMKO_PAID_API_ENABLED` and metered at two request units per agent.

Only names, instructions and optional model metadata import. No tools, secrets or
provider credentials import. The global text model is unchanged by model metadata.

## Signed remote team model (local cache only)

`team/permissions/import`: `snapshot` (RS256 JWT signed by a separately trusted
service). `SIMKO_TEAM_PUBLIC_KEY` is a public verification key, never a signing key.
Required claims: issuer `https://simkosi.com`, audience `simko-team`, `iat`, `exp`,
`team` starting `remote:`, positive increasing integer `revision`, `members`
(account -> owner/adult/child, exactly one owner), and `resources`
(resource -> permission -> role list). Only read/use resource permissions exist;
child role cannot use/write regardless of ACL, and absent grants deny access.
The importing authenticated account must be a member. Invalid signatures, expiry,
wrong issuer/audience, stale revisions and malformed grants fail closed.

- `team/resource/read`: `team`, `resource` reads local cached content after ACL check.
- `team/resource/write`: same plus bounded string `content` appends a local revision.
- Local membership endpoints cannot elevate a signed remote team member.

Check and access share one transaction. Revocation requires a newer snapshot or
expiry; offline clients cannot know about immediate server revocations. No snapshot
issuer, invitations, external sharing, live remote sync or cloud migration was run.
Production authority/transport and server-side enforcement need separate approval.

## Mock checkout (`SIMKO_PAYWALL=1` only when deliberately testing)

- `checkout/create`: stable `request_id` (8–100 chars), `owner_confirmed: true`.
  Owner-scoped idempotency, offline mock receipt, no payment link and `charged:false`.
- `checkout/status`: `id`. Reconciles owner, mock environment, exact fixture amount,
  currency and completion state. Never accepts a client-supplied paid status.

The amount of 1000 USD cents is a test fixture, not a proposed product price.
`MockSquareSandbox.complete_for_test` and `issue_test_entitlement` are test helpers,
NOT HTTP routes. The issuer takes an injected generated test key and issues
short-lived RS256 claims with issuer `simko-square-mock`, audience
`simko-desktop-sandbox`, plan `sandbox_paid`, `sandbox:true`. Production quota
verification refuses sandbox claims. Nothing contacts Square, even its sandbox.
Production checkout, webhook verification, refunds/revocation, commercial pricing,
real entitlement issuance and billing enforcement remain out of scope/disabled.

## Finish pass (items 2, 3, 5, 6, 9)

- `/api/auth` `op=resend-confirmation` with `token` (session): new confirm code,
  older ones stop working. Reset/confirm codes are single-use and expire.
- `sync/status`: queue size and health (last success, failures, next attempt).
- `agents/message`: `id`, `text`, optional `to` (agent name or `all`).
  `agents/cancel`: `id`. `agents/status` now includes `messages`.
- `templates/history`; `templates/rollback`: `id`, `owner_confirmed: true`.
- Cloud backup (`SIMKO_CLOUD_BACKUP=1`; identity mapping `SIMKO_SYNC_LOCAL_USER`):
  `backup/status`, `backup/create` (`passphrase`, optional `upload:false`),
  `backup/flush`, `backup/list`, `backup/verify` (`backup_id`, `passphrase`),
  `backup/restore` (`backup_id`, `passphrase`, `owner_confirmed: true`).
  Passphrases are never echoed, stored or uploaded.
