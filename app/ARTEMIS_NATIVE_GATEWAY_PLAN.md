# Artemis Native Gateway Plan

Date: 2026-05-08

## Purpose

Artemis Gateway is the native Frontier AI nervous system. It is not an OpenClaw dependency or product layer. It is the Frontier-owned coordination layer between Artemis Chat, Artemis Operator, Omega local conversations, Hermes internal execution, model providers, memory sources, tools, permissions, background work, and future channels.

## Completed Gateway Skeleton

The first safe skeleton is implemented under `src/lib/artemis/gateway/`.

- `sessionManager.ts`
  - Defines gateway session types and in-memory session management.
  - Session types include `user_chat`, `omega_conversation`, `operator_mission`, `channel_session`, and `tool_session`.

- `toolRegistry.ts`
  - Defines gateway tools, tool categories, risk tiers, approval requirements, and allowed modes.
  - Includes placeholders for chat, Omega storage, Operator, Hermes executor, local model, paid model, Twilio, file system, browser, terminal, and future channel tools.

- `permissionPolicy.ts`
  - Defines risk tiers and approval decisions.
  - Keeps outbound messages, paid API use, deploys, commits, pushes, public tunnels, money, destructive actions, and secrets approval-gated.

- `modelRouter.ts`
  - Defines lightweight model provider selection.
  - Normal chat can prefer local or paid model routing.
  - Coding/operator tasks prefer Codex.
  - Deterministic actions prefer deterministic local tools.
  - Paid usage is marked approval-required unless allowed by configuration.

- `artemisGateway.ts`
  - Exposes central gateway functions:
    - `createGatewaySession`
    - `getGatewaySession`
    - `listGatewaySessions`
    - `routeGatewayMessage`
    - `registerGatewayEvent`
    - `getGatewayStatus`

- `index.ts`
  - Exports the gateway modules cleanly.

The UI now includes a read-only Artemis Gateway Status section in `AgentWorkspacePage.tsx`.

## Owner-Approved Twilio Voice Calling

The first real Artemis communication action is implemented as a narrow owner-only channel action.

- `src/lib/artemis/channels/twilioVoiceAdapter.ts`
  - Defines Twilio owner call request creation, validation, risk metadata, and summaries.
  - Marks outbound voice as `tier_4_external_action`.

- `server/lib/twilioOwnerCall.js`
  - Server-side Twilio REST call helper.
  - Loads `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, and `ARTEMIS_OWNER_PHONE` from env.
  - Supports direct Twilio or a Twilio-compatible SignalWire LaML base URL through `TWILIO_COMPATIBLE_API_BASE_URL`.
  - Calls only `ARTEMIS_OWNER_PHONE`.
  - Returns safe JSON without credentials.

- `scripts/artemis-controller.mjs`
  - Adds `POST /api/artemis/twilio/call-owner` to the local Artemis API.
  - Keeps the route local-origin protected.
  - Requires `approvalStatus: "owner_approved"` or `testMode: true`.

- `scripts/test-artemis-twilio-call.mjs`
  - Adds `npm run artemis:test-call`.
  - Places the explicit owner test call with: "This is Artemis. Twilio calling is connected."

- `src/lib/artemis/gateway/toolRegistry.ts`
  - Registers `twilio_voice_call_owner`.

- `src/lib/artemis/gateway/permissionPolicy.ts`
  - Confirms calls/texts/email/paid APIs/deploys/commits/pushes/public tunnels/spending are external approval-gated actions.
  - Blocks arbitrary phone destinations for now.

The Twilio SDK is not currently installed; this implementation uses Node's built-in HTTPS client against Twilio's REST API and does not add dependencies. If the project later standardizes on the official SDK, install it intentionally with `npm install twilio`.

## Communication OS Foundation Implemented

The next foundation pass adds a local-first personal assistant communication layer.

- `server/lib/artemisCommunicationOs.js`
  - Owns channel matrix status, unified inbox normalization, Personal OS store validation, reminders, contacts, trusted devices, call audit/schedule/allowlist state, onboarding checklist, plugin validation, and notification stubs.

- `src/components/ArtemisUnifiedInboxPanel.tsx`
  - Adds a minimal unified inbox UI for local API-backed SMS/MMS/call/Telegram/WhatsApp/email-placeholder events.
  - Approval buttons call the existing local approval API.
  - Call control queues an owner call draft; it does not place a call directly.

- `scripts/test-artemis-personal-os.mjs`, `scripts/test-artemis-channels.mjs`, and `scripts/test-artemis-onboard.mjs`
  - Add local smoke coverage for the channel registry, inbox normalization, draft lifecycle, reminder lifecycle, contact memory, call allowlisting, onboarding, and plugin manifest validation.

- `docs/artemis-personal-communication-os.md`
  - Documents channel matrix, unified inbox, workflows, devices, calling, Telegram, WhatsApp, onboarding, plugins, tests, and native app roadmap.

New command surfaces:

- `npm run artemis:channels`
- `npm run artemis:owner-loop`
- `npm run artemis:onboard`
- `npm run artemis:test`
- `npm run artemis:test-channels`
- `npm run artemis:test-onboard`
- `npm run artemis:test-personal-os`
- `npm run artemis -- assistant "show everything I missed today"`
- `npm run artemis -- personal-os summary`
- `npm run artemis -- devices list`
- `npm run artemis -- calls log`
- `npm run artemis -- plugins list`

## SignalWire Owner-Only Assistant Loop Implemented

Current native Communication OS defaults:

- SignalWire is the only active real provider.
- Twilio-compatible route names remain in code where the current runtime already uses them.
- Owner-only contact mode is enforced in the local policy and contact store.
- Owner profile, quiet hours, allowlisted owner contact, approval policy, and owner instruction queue are stored under `.artemis/`.
- Outbound SMS/MMS/call lifecycle events are recorded in `.artemis/communications/messages.jsonl`, `.artemis/communications/calls.jsonl`, and `.artemis/communications/events.jsonl`.
- The unified inbox reads SignalWire message/call audit events plus existing local drafts and approval items.
- Telegram, WhatsApp, email, and push are visible as disabled health-check placeholders and do not require credentials during onboarding.

New local loop commands:

- `npm run artemis:owner-loop`
- `npm run artemis -- owner-loop status`
- `npm run artemis -- owner-loop defaults`
- `npm run artemis -- owner-loop ingest "task"`
- `npm run artemis -- owner-loop sms-prompt "message"`
- `npm run artemis -- owner-loop call-prompt "message"`

Intentionally still local-only:

- No public webhook tunnel is started automatically.
- No Telegram/WhatsApp/email/push credentials are required.
- No non-owner outbound calls/texts are enabled.
- No automatic send bypass was added.

## Remaining OpenClaw-Like Features To Build Natively

- Persistent session storage under `.artemis/gateway` or `.omega/gateway-index`.
- Gateway event log persisted locally.
- Device pairing and trusted-device identity.
- Background daemon status reporting.
- Native scheduling and wakeup tasks.
- Memory source registry for local conversations, saved files, project context, and knowledge indexes.
- Plugin/tool manifest loading.
- Provider health checks for local models, Codex, OpenAI paid models, and deterministic tools.
- Channel adapter runtime for SMS, voice, WhatsApp, Telegram, Slack, Discord, email, and calendar.
- Phone destination allowlists beyond the single owner number.
- Approval inbox shared across chat, Operator, and channels.
- Remote approval replies.
- Audit views for gateway decisions.
- Safe retry and rollback policy for background tasks.

## Recommended Build Order

1. Persist read-only gateway status.
   - Write a lightweight status snapshot from Artemis controller or Artemis Operator.
   - Keep UI read-only.

2. Record gateway sessions from Artemis Chat.
   - Call `routeGatewayMessage` when a chat message is submitted.
   - Do not change assistant response behavior yet.

3. Connect Omega Conversation Store to gateway sessions.
   - Map Omega conversation IDs to gateway `omega_conversation` sessions.
   - Keep current storage keys and folder names until migration is planned.

4. Connect Artemis Operator missions to gateway sessions.
   - Map mission IDs to `operator_mission` sessions.
   - Record permission decisions and model route decisions.

5. Add persisted gateway events.
   - Store append-only JSONL under `.artemis/gateway/events.jsonl`.
   - Redact secrets and avoid command stdout dumps.

6. Add read-only channel adapter manifests.
   - Define capabilities and approval policies before implementing real sends.

7. Add channel draft-only mode.
   - SMS/voice first because Twilio readiness already exists.
   - WhatsApp, Telegram, Slack, Discord, email, and calendar later.

8. Add approval inbox unification.
   - One policy surface across Artemis Chat, Operator, Omega, and channels.

## Channel Adapter Roadmap

- Phase 1: Twilio SMS/voice status and draft queue.
- Phase 2: Twilio approval replies and owner notifications.
- Phase 3: WhatsApp and Telegram draft-only adapters.
- Phase 4: Email and calendar read/draft adapters.
- Phase 5: Slack and Discord draft-only adapters.
- Phase 6: Approved outbound sends with allowlists, quiet hours, audit logs, and per-channel policy.

No channel should send externally until its adapter has:

- account authorization,
- destination allowlist,
- approval policy,
- audit logging,
- failure handling,
- user-visible status,
- and a dry-run test path.

## Daemon And Status Roadmap

- Add `.artemis/gateway/status.json`.
- Add `.artemis/gateway/events.jsonl`.
- Add gateway status to `scripts/artemis-controller.mjs` `/status`.
- Add gateway status to the local Operator health payload later.
- Add a background heartbeat that records:
  - active sessions,
  - pending approvals,
  - active missions,
  - model provider health,
  - channel adapter readiness,
  - daemon PID/status,
  - last successful check time.

## Testing Checklist

- `npm run typecheck`
- `npm run lint`
- `npm run build`
- Create a gateway session in a unit or smoke check.
- Verify `getGatewayStatus()` returns:
  - `ok: true`,
  - session count,
  - registered tool count,
  - approval policy active,
  - model routing available.
- Verify risk policy decisions:
  - read-only does not require approval,
  - draft-only does not require approval,
  - safe local write requires approval outside trusted workspace,
  - code patch requires approval unless preapproved,
  - external actions require approval,
  - destructive/secret actions always require approval.
- Verify model router decisions:
  - normal chat can use local model,
  - coding/operator prefers Codex,
  - deterministic actions use deterministic local tool,
  - paid model fallback is approval-gated unless allowed.
- Verify Gateway Status UI is read-only and does not create sessions or execute tools.
