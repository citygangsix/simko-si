# Frontier AI Architecture Audit

Date: 2026-05-09

## Product Boundary Summary

Frontier AI currently has the right ingredients, but the names and boundaries are mixed across the website, local runtime, and saved state.

- **Artemis** should be the primary AI assistant and commander. It should own the default chat experience, project context, saved knowledge, local files, agent awareness, and Operator Mode.
- **Omega** should be the multi-chat workspace. It should open from the Omega entrypoint, show multiple conversations/agents at once, and save conversations into local structured storage.
- **Hermes** should be the local executor layer. It should stay behind the scenes and handle commands, missions, patch generation, patch application, rollback metadata, and task execution.
- **OpenClaw** is not a Frontier AI product layer or dependency. It was only a reference point for broad gateway/personal-assistant capabilities that Artemis should implement natively.

## Current Artemis Implementation

### CLI, API, And Local State

- `bin/artemis.mjs`
  - Installed CLI entrypoint.
  - Spawns `scripts/artemis-controller.mjs` with `ARTEMIS_PROJECT_ROOT`.

- `scripts/artemis-controller.mjs`
  - Main Artemis CLI/API controller.
  - Owns `.artemis` state paths: runs, screenshots, skills, memory, audits, rollbacks, backups, project context, personal assistant scope, and status files.
  - Exposes local API on port `8789`.
  - Handles planning, autonomous coding runs, approvals, remote approval prompts, SMS/MMS/call queues, savings mode, project context, personal assistant scope, ecosystem/plugin audits, backups, and rollbacks.
  - Calls Hermes executor endpoints for local coding missions through `HERMES_HANDS_BASE_URL`.
  - Still exposes compatibility paths like `/hermes/approve-latest` and `/hermes/apply-latest`.

- `.artemis/`
  - Working Artemis local state directory.
  - Contains project context, run logs, memory, audits, backups, screenshots, rollbacks, state, and generated skills.

- `src/components/ArtemisDashboard.tsx`
  - UI dashboard for the Artemis controller.
  - Reads `http://127.0.0.1:8789/status` and falls back to `public/artemis-status.json`.
  - Displays Artemis run state, approvals, commands, skills, and local controller status.

- `public/artemis-status.json` and `public/artemis-screenshots/`
  - Public build artifacts for Artemis status/screenshot display.

### Artemis Chat Surface

- `src/components/FrontierLandingPage.tsx`
  - Currently acts as the primary AI/command-center surface under `/aimentor`.
  - Imports chat thread helpers from `src/lib/hermesAgentNetwork.ts`.
  - Imports Hermes executor helpers from `src/lib/hermesHands.ts`.
  - Includes command parsing for Artemis local API calls, conversation archive commands, Omega coding bridge commands, and Hermes Hands missions.
  - Uses Artemis branding heavily, but also embeds Omega workspace and Hermes executor behavior.

- `src/components/MentorChatbotPage.tsx`
  - Older/default chatbot-style page.
  - Calls `requestHermesReply` for assistant replies.
  - Uses local React chat state rather than a clear Artemis conversation store.
  - Currently reachable only through the internal `chatbot` tab, not the main app routes.

- `src/components/AICoach.tsx`
  - Wellness/coach component that also calls `requestHermesReply`.

- `src/lib/hermesAgentNetwork.ts`
  - Despite the Hermes name, this is currently the main chat brain/client-side agent network.
  - Defines chat thread types, default thread creation, localStorage keys, OpenCog/category context, source quote retrieval, prompt construction, fallback replies, and dispatch recording.
  - Uses `HERMES_CHAT_THREADS_STORAGE_KEY = 'ograw.hermes.chatThreads'`.
  - Creates thread IDs like `hermes-chat-*`.
  - Function names like `requestHermesReply`, `createHermesChatThread`, `loadHermesChatThreads`, and `recordHermesDispatch` are Artemis/Omega-facing behavior with Hermes names.

## Current Omega Implementation

### Website Routes And Download Page

- `src/App.tsx`
  - Routes `/omega`, `/download`, and `/omega/download` to `OmegaDownload`.
  - Does not currently route `/omega` to a real Omega multi-chat workspace.
  - Routes `/aimentor` to `Index initialActiveTab="ai-mentor"`, which renders `FrontierLandingPage`.

- `src/pages/OmegaDownload.tsx`
  - Current Omega website/download page.
  - Positions Omega as the local app that connects Artemis to Terminal, Codex, Ollama, Gemini, Supabase, and local credentials.
  - Calls `checkHermesHandsHealth()` but describes the result as the local Artemis bridge.

- `src/lib/omegaDistribution.ts`
  - Defines Omega domains, installer targets, autonomy tiers, installer URLs, local AI defaults, privacy/security copy, and download prompts.
  - Mostly correct as Omega distribution/onboarding copy.

- `src/components/ContrastOmegaLogo.tsx`
  - Omega-named logo component.
  - Uses `/frontier-logo.png` and defaults alt text to `OGRaw`, which mixes brand signals.

### Omega Workspace UI

- `src/components/AgentWorkspacePage.tsx`
  - Current multi-agent workspace implementation.
  - Contains Omega views, agent tabs/messages, local AI model setup, credential setup, conversation archive, Artemis capability dashboard, Artemis Hands/operator UI, swarm runner, and map/timeline views.
  - Imports Hermes executor APIs directly.
  - Imports Artemis dashboard directly.
  - Imports Omega credentials/distribution/local AI helpers.
  - This file is the biggest mixed-responsibility area in the codebase.

- `src/components/OmegaMapView.tsx`
  - Omega visual map view.
  - Uses conversation archive insights when available.

- `src/components/OmegaLinearTimelineView.tsx`
  - Omega timeline view.
  - Uses conversation archive insights when available.

- `src/lib/omegaGoalBuildouts.ts`
  - Defines Omega goal buildout blueprints and local workspace mutations.
  - Imports `AGENT_WORKSPACE_STORAGE_KEY` and OpenCog types from `hermesAgentNetwork`, which couples Omega setup to a Hermes-named chat/agent module.

- `src/workers/omegaSwarm.worker.ts`
  - Worker for Omega swarm behavior.

### Omega Local Storage And Memory

- `.omega/`
  - Local Omega state directory exists and is active.
  - Contains:
    - `.omega/conversation-index/conversations.json`
    - `.omega/conversations/YYYY-MM-DD/conversation-hermes-chat-*/`
    - `.omega/secure-credentials/vault.json`
  - Conversation folders are currently named from Hermes chat IDs, which is a naming mismatch.

- `src/lib/conversationArchive.ts`
  - Client for local conversation memory/archive.
  - Exposes status, capture, search, pause/resume, delete, export, insights, and LifeBook retrieval.
  - Uses `HERMES_HANDS_BASE_URL`, so Omega/Artemis memory is currently served by the Hermes executor server.

- `scripts/hermes-hands-server.mjs`
  - Implements the actual conversation archive server endpoints under `/conversation-archive/*`.
  - Writes local conversation artifacts into `.omega/conversations`.
  - Defaults `sourceApp` to `Omega` and participants to `['user', 'Artemis']`.
  - This storage behavior is useful, but it lives inside the Hermes executor server.

- `src/lib/omegaCredentials.ts`
  - Client for Omega credential status/save/delete.
  - Uses `HERMES_HANDS_BASE_URL`.

- `scripts/hermes-hands-server.mjs`
  - Implements `/omega-credentials/status`, `/omega-credentials/save`, and `/omega-credentials/delete`.
  - Stores encrypted credential presence/data under `.omega/secure-credentials/vault.json`.

## Current Hermes Implementation

### Executor Server And State

- `scripts/hermes-hands-server.mjs`
  - Local executor server on port `8765`.
  - Data root is `.hermes-hands`.
  - Owns request logs, mission logs, policy, daemon logs, coding task state, file baselines, and awake lock behavior.
  - Exposes executor endpoints:
    - `/health`
    - `/capabilities`
    - `/policy`
    - `/requests`
    - `/requests/:id/approve`
    - `/requests/:id/cancel`
    - `/missions`
    - `/missions/:id/cancel|pause|resume`
  - Also serves Omega credentials and conversation archive, which should eventually move out of the Hermes boundary.
  - Logs itself as `Artemis local executor`, which is acceptable as user-facing language if Hermes remains hidden, but the file/API boundary is still Hermes.

- `.hermes-hands/`
  - Active executor state directory.
  - Contains requests, missions, policy, daemon logs, file baselines, and coding task artifacts.

- `src/lib/hermesHands.ts`
  - Frontend client for the local executor server.
  - Defines Hermes request, mission, health, policy, and autonomy types.
  - Calls `/health`, `/requests`, `/missions`, `/policy`, and approval/cancel endpoints.
  - Includes Omega Coding Bridge helpers.
  - User-facing summaries often say Artemis while exported names say Hermes.

### Patch Generation, Apply, And Rollback

- `scripts/hermes-coding-adapter.mjs`
  - Local patch/task adapter.
  - Data root is `.hermes-hands/coding-tasks`.
  - Creates `approved-changes.json`, `patch-plan.md`, `critic-review.json`, `rollback.json`, `audit.json`, `result.json`, and rollback results.
  - Supports safe `write` and `replace` patch operations.
  - Blocks env files, dependency folders, generated folders, and high-risk files unless explicitly allowed.
  - Restricts generated changes to `src/`, `docs/`, and `scripts/`.
  - This is clearly Hermes executor behavior, although copy inside the file calls it Artemis coding.

- `scripts/hermes-hands-daemon.mjs`
  - Daemon installer/status/uninstaller for the local executor.
  - Current launch label has moved toward `com.frontier.artemis-hands`, with a legacy Hermes label still present.

- `scripts/activate-hermes-autocoder.mjs`
  - Hermes autocoder activation script.

- `scripts/activate-artemis-autocoder.mjs`
  - Thin Artemis-named wrapper around the Hermes activation script.

## Current OpenClaw References

No direct OpenClaw references were found in the project source tree when searching for `OpenClaw`, `openclaw`, or `OPENCLAW` outside generated/dependency folders.

OpenClaw does exist as an external local install outside this repo:

- `/Users/xxx/.local/bin/openclaw`
- `/Users/xxx/.openclaw/openclaw.json`
- `/Users/xxx/.openclaw/logs/`
- `/Users/xxx/.openclaw/plugins/`
- `/Users/xxx/.openclaw/tasks/runs.sqlite`

Conclusion: OpenClaw is not currently integrated into the Frontier AI source code. That is good for product clarity. Artemis Gateway should implement this class of capability natively instead of depending on OpenClaw.

## Incorrectly Mixed Responsibilities

### 1. Artemis Chat Is Implemented In Hermes-Named Modules

- `src/lib/hermesAgentNetwork.ts` is actually Artemis chat/agent-network behavior.
- Thread IDs and localStorage keys use Hermes naming.
- UI components call `requestHermesReply` for user-facing Artemis/Omega chat replies.
- Conversation archive folders inherit `conversation-hermes-chat-*` IDs.

This should be renamed or wrapped as Artemis/Omega chat behavior, not Hermes executor behavior.

### 2. Omega Workspace Is Embedded Inside Artemis/AI Mentor

- `/omega` opens `OmegaDownload`, not the Omega workspace.
- The actual workspace is embedded through `AgentWorkspacePage` inside `FrontierLandingPage`, reached through `/aimentor`.
- Navigation still labels the primary surface as `AI Mentor`.

Omega needs its own route and product boundary.

### 3. Hermes Executor Also Owns Omega Memory And Credentials

- `scripts/hermes-hands-server.mjs` owns:
  - Hermes executor requests/missions.
  - Omega conversation archive.
  - Omega credential vault endpoints.
- `src/lib/conversationArchive.ts` and `src/lib/omegaCredentials.ts` both depend on `HERMES_HANDS_BASE_URL`.

Hermes can physically serve these endpoints for now, but the product/API boundary should be renamed to an Artemis/Omega local service or wrapped behind domain-specific clients.

### 4. Operator Mode Is Split Between Artemis And Hermes Names

- UI says `Artemis Hands`.
- Runtime files say `hermes-hands`.
- CLI scripts expose `artemis:hands`.
- API still has `/hermes/approve-latest` and `/hermes/apply-latest`.

The user-facing feature should be `Artemis Operator Mode`. Hermes should remain the implementation detail.

### 5. Omega Coding Bridge Mixes Product And Executor Concepts

- `src/lib/hermesHands.ts` contains Omega Coding Bridge helpers.
- `FrontierLandingPage` starts Omega coding bridge missions through Hermes executor APIs.
- `AgentWorkspacePage` treats Hermes health as Omega readiness in places.

Omega should orchestrate workspace context and chat tabs. Artemis should decide/command. Hermes should execute.

### 6. Branding Is Inconsistent

- `AI Mentor`, `FrontierLandingPage`, `Artemis`, `Omega`, `Hermes`, `OpenCog`, and `OGRaw` all appear in the primary experience.
- `ContrastOmegaLogo` uses the Frontier logo with OGRaw default alt text.
- Some copy says `Artemis/OpenCog threads`; some thread migration code still handles `New Hermes chat`.

The visible app needs one hierarchy: Frontier AI product, Artemis assistant, Omega workspace, Hermes executor behind the curtain.

## What Should Be Renamed, Separated, Or Refactored

### Rename Or Wrap First

Do not immediately rename files/directories that runtime scripts depend on. The safest first move is an adapter layer.

- Add `src/lib/artemisChat.ts` that wraps/re-exports:
  - `requestHermesReply` as `requestArtemisReply`
  - `createHermesChatThread` as `createArtemisChatThread`
  - `loadHermesChatThreads` as `loadArtemisChatThreads`
  - `saveHermesChatThreads` as `saveArtemisChatThreads`
  - `recordHermesDispatch` as `recordArtemisDispatch`

- Add `src/lib/artemisOperator.ts` that wraps/re-exports Hermes executor client calls as Operator Mode calls:
  - `checkHermesHandsHealth` as `checkArtemisOperatorHealth`
  - `createHermesHandsMission` as `createArtemisOperatorMission`
  - `createHermesHandsRequest` as `createArtemisOperatorRequest`
  - `approveHermesHandsRequest` as `approveArtemisOperatorRequest`

- Add `src/lib/omegaConversationStore.ts` that wraps `conversationArchive.ts` using Omega/Artemis vocabulary.

### Separate Routes

- Keep `/omega/download` for the download page.
- Add a real Omega workspace route, preferably `/omega`.
- Move the current `AgentWorkspacePage` entrypoint to that route.
- Keep `/aimentor` or redirect it to the Artemis default chat only.

### Separate Long-Term Services

Later, split the local server boundaries:

- Artemis local controller: chat, project context, approvals, global assistant state.
- Omega local store: multi-chat tabs, conversation archive, credentials, workspace memory.
- Hermes executor: commands, missions, patches, rollback, verification.
- Native Artemis Gateway: sessions, routing, device readiness, scheduling, memory/tool registry, and provider coordination without an OpenClaw dependency.

### Storage Migration Later

Do not do this first. It needs compatibility code.

- Migrate localStorage keys:
  - `ograw.hermes.chatThreads` -> `frontier.artemis.chatThreads` or `frontier.omega.conversations`
  - `ograw.hermes.activeThreadId` -> Artemis/Omega equivalent
  - `ograw.hermes.dispatches` -> `frontier.artemis.dispatches`

- Migrate folder IDs:
  - `conversation-hermes-chat-*` -> `conversation-artemis-chat-*` or `conversation-omega-chat-*`

- Keep read fallback for old keys/folders.

## What Is Already Working

- Artemis CLI is installed and wired through `bin/artemis.mjs`.
- Artemis controller state exists under `.artemis`.
- Artemis can plan, run local loops, queue approvals, record runs, manage project context, and expose local API endpoints.
- Hermes executor server exists and has a clear command/request/mission policy model.
- Hermes coding adapter supports approved patch generation, critic review, apply, audit, rollback metadata, and rollback execution.
- `.hermes-hands` contains real request, mission, task, baseline, and policy state.
- Omega local storage exists under `.omega`.
- Conversation archive writes structured local folders with `index.json`, `messages.json`, `metadata.json`, `summary.md`, and `transcript.md`.
- Omega map and linear timeline views exist and can consume archive insights.
- Omega distribution/download copy and local setup checks exist.
- Credential vault behavior exists locally under `.omega/secure-credentials`.
- Artemis dashboard can read the Artemis controller status API.

## Missing For Artemis Chat Mode

- A clean default route for a new Artemis chat.
- Clear visible naming: `Artemis`, not `AI Mentor`, `Hermes`, or `OpenCog`.
- Artemis-named chat API/client functions instead of `requestHermesReply`.
- Artemis-named thread IDs and storage keys with migration fallback.
- Default saving of every Artemis chat into the local conversation archive.
- A clear knowledge/context panel showing what Artemis can use: project context, saved files, previous conversations, agents, and local memory.
- Separation from Omega workspace UI. Artemis chat should not have to render the entire multi-agent workspace.
- A single answer path for chat mode. Current logic can route through quote search, OpenCog snapshot, Hermes dispatches, conversation archive commands, Artemis local commands, and Omega bridge commands in the same component.

## Missing For Omega Multi-Chat And Local Storage

- `/omega` should open the Omega workspace, not only the download page.
- Conversation tabs should be first-class Omega objects, not Hermes chat threads.
- Each Omega conversation should be saved into `.omega` by default with Omega/Artemis IDs.
- Agent tabs should be explicit: Artemis as global/top brain, other agents as separate tabs.
- The Omega workspace needs a smaller shell component that owns layout, tabs, and persistence. `AgentWorkspacePage` is currently too broad.
- Omega memory APIs should be domain-named, even if they temporarily call the Hermes server underneath.
- Local storage should have a compatibility migration path from current Hermes-named keys.
- The download/onboarding page should be separate from the installed/local workspace.

## Missing For Artemis Operator Mode

- A user-facing `Artemis Operator Mode` concept that hides Hermes.
- A dedicated Operator Mode UI separate from the Omega workspace.
- Clear autonomy presets for overnight work, including:
  - Manual/suggest only.
  - Low-risk checks only.
  - Trusted workspace coding.
  - Approval-required sensitive actions.
- A clear “while I sleep” mission flow with:
  - objective,
  - allowed workspace,
  - allowed commands,
  - maximum runtime,
  - keep-awake setting,
  - approval policy,
  - progress summary,
  - rollback status,
  - final report.
- Better integration between Artemis controller runs and Hermes mission state.
- A stable API boundary where Artemis commands missions and Hermes executes them.
- Native gateway support for remote sessions, device pairing, and scheduling, without exposing or depending on OpenClaw.
- Computer-use/browser-use task execution is not yet clearly unified with Operator Mode. Current implementation is strongest for coding missions and local shell commands.

## Recommended Smallest Safe Next Refactor

The smallest safe next refactor is a naming-boundary adapter pass, not a filesystem rename.

1. Add `src/lib/artemisChat.ts`.
   - Wrap the Hermes-named chat functions with Artemis names.
   - Keep old imports working.
   - Do not migrate localStorage yet.

2. Add `src/lib/artemisOperator.ts`.
   - Wrap the Hermes executor client with Artemis Operator Mode names.
   - Keep `src/lib/hermesHands.ts` as the implementation detail.

3. Add `src/lib/omegaConversationStore.ts`.
   - Wrap `conversationArchive.ts` with Omega-local-storage names.
   - Keep the existing server endpoints for now.

4. Update only UI imports and visible labels in:
   - `src/components/FrontierLandingPage.tsx`
   - `src/components/MentorChatbotPage.tsx`
   - `src/components/AICoach.tsx`
   - `src/components/AgentWorkspacePage.tsx`
   - `src/pages/OmegaDownload.tsx`

5. Add a real Omega workspace route.
   - Prefer `/omega` for `AgentWorkspacePage`.
   - Move the current download page to `/omega/download`.
   - If preserving `/omega` marketing behavior is important, add `/omega/workspace` first, then switch later.

This refactor changes the product boundary without breaking the underlying local executor, saved state, or existing CLI scripts. After that, the next phase can safely migrate storage keys and split `AgentWorkspacePage` into smaller Artemis Chat, Omega Workspace, and Artemis Operator components.

## Adapter Refactor Implemented

Date: 2026-05-08

### Files Added

- `src/lib/artemis/artemisChat.ts`
  - Adds the Artemis Chat boundary for the default user-facing Frontier AI assistant.
  - Wraps the existing Hermes-named chat implementation without duplicating chat logic.
  - Exposes Artemis names for creating/loading/saving chat threads, active thread selection, reply generation, title generation, and dispatch recording.

- `src/lib/artemis/artemisOperator.ts`
  - Adds the Artemis Operator boundary for autonomous coding and computer-working mode.
  - Wraps the existing Hermes Hands executor client.
  - Preserves existing approval gates, mission controls, policy checks, request approvals, and Omega Coding Bridge helpers.
  - Provides compatibility aliases so large UI files can move to the Artemis boundary before all internal variable names are renamed.

- `src/lib/omega/omegaConversationStore.ts`
  - Adds the Omega conversation store boundary for multi-chat workspace conversations.
  - Defines interfaces for creating, listing, reading, saving, appending messages, updating metadata, converting to archive snapshots, and archiving conversations.
  - Wraps existing local chat storage and optional `.omega` archive capture without migrating existing storage.

### Files Modified

- `src/components/FrontierLandingPage.tsx`
  - Uses `artemisChat.ts` for primary chat behavior.
  - Uses `artemisOperator.ts` for Operator mission/request behavior.
  - Updates visible wording from AI Mentor toward Artemis and Operator language.

- `src/components/AgentWorkspacePage.tsx`
  - Uses `artemisChat.ts` for Artemis replies and dispatch recording.
  - Uses `artemisOperator.ts` as the import boundary for local operator/executor behavior.
  - Updates visible `Artemis Hands` language to `Artemis Operator`.

- `src/components/MentorChatbotPage.tsx`
  - Uses `requestArtemisChatReply` instead of importing the Hermes-named reply function directly.

- `src/components/AICoach.tsx`
  - Uses `requestArtemisChatReply` for assistant replies.

- `src/pages/OwnerDashboard.tsx`
  - Uses `requestArtemisChatReply` for fallback AI answers.

- `src/pages/OmegaDownload.tsx`
  - Uses `checkArtemisOperatorHealth` for local bridge readiness.

- `src/components/Navigation.tsx`
  - Updates the main AI navigation label from `AI Mentor` to `Artemis`.

### What Changed

- Artemis Chat now has a clear adapter boundary for the default assistant.
- Artemis Operator now has a clear adapter boundary over the current Hermes executor.
- Omega conversation storage now has a defined adapter interface for multi-chat conversations and metadata.
- User-facing UI language is less mixed: Artemis is the assistant/commander, Omega is the workspace, and Operator language replaces visible Hands language.
- Existing Hermes runtime behavior remains in place behind the adapters.

### What Was Intentionally Not Changed

- No Hermes runtime files were renamed or deleted.
- No `.hermes-hands`, `.artemis`, or `.omega` storage migration was performed.
- Existing localStorage keys were not migrated.
- Existing `conversation-hermes-chat-*` folder names were not migrated.
- Existing CLI scripts such as `npm run artemis:hands` were not renamed.
- OpenClaw setup was not changed.
- `AgentWorkspacePage.tsx` still has internal Hermes variable names where renaming would create unnecessary risk in this pass.
- `src/lib/hermesAgentNetwork.ts` and `src/lib/hermesHands.ts` remain as implementation modules.

### Checks Run

- `npm run typecheck`
  - Passed.

- `npm run lint`
  - Passed with 11 existing Fast Refresh warnings in shared UI/context files.

- `npm run build`
  - Passed.
  - Vite reported a non-failing large chunk warning for the main bundle.

### Next Recommended Step

Split `AgentWorkspacePage.tsx` into smaller shells:

- `ArtemisChatShell`
- `OmegaWorkspaceShell`
- `ArtemisOperatorPanel`

That should happen before storage migration. It will make the later localStorage and folder-prefix migration much safer because each product boundary will already have a smaller owner.

## Workspace Shell Refactor Implemented

Date: 2026-05-09

### Files Created

- `src/components/artemis/ArtemisChatShell.tsx`
  - Adds the reusable normal chat shell for the default user-facing Artemis assistant.
  - Uses `src/lib/artemis/artemisChat.ts` so Chat Mode enters through the Artemis adapter boundary.
  - Presents Artemis as the primary assistant and keeps Operator Mode separate.

- `src/components/omega/OmegaWorkspaceShell.tsx`
  - Adds the reusable Omega shell for the multi-chat workspace.
  - Uses `src/lib/omega/omegaConversationStore.ts` for a read-only local conversation count.
  - Presents Omega as the workspace where Artemis is the global/default assistant and other agents can remain separate conversations.

- `src/components/artemis/ArtemisOperatorPanel.tsx`
  - Adds the reusable Operator Mode panel for autonomous local coding/computer work.
  - Uses `src/lib/artemis/artemisOperator.ts` so Operator UI enters through the Artemis adapter boundary.
  - Surfaces online state, mission counts, queued/running work, and approval counts without bypassing approval gates.

### Files Modified

- `src/components/AgentWorkspacePage.tsx`
  - Now composes `ArtemisChatShell`, `OmegaWorkspaceShell`, and `ArtemisOperatorPanel`.
  - Keeps existing chat, Omega workspace, mission, approval, log, and command behavior intact.
  - Cleans safe visible copy from older OpenCog/OpenClaw language toward Artemis/Omega product language.

- `src/components/FrontierLandingPage.tsx`
  - Updates visible `OMEGA: Multi Mentor` and older OpenCog copy to `Omega Workspace` and Frontier AI/Omega wording.
  - Keeps legacy `New Hermes chat` title detection only as compatibility for old saved threads.

- `src/components/MentorChatbotPage.tsx`
  - Updates the multi-chat category label to `Omega Workspace`.

- `FRONTIER_AI_ARCHITECTURE_AUDIT.md`
  - Documents the shell refactor and current frontend boundaries.

### What Changed

- `AgentWorkspacePage.tsx` is now a composition layer for the three product-facing frontend surfaces instead of one page owning all visible product identity directly.
- Artemis Chat has a reusable shell for normal conversations.
- Omega has a reusable shell for the multi-chat workspace.
- Artemis Operator has a reusable panel for autonomous work, status, missions, logs, and approvals.
- Product copy is clearer: Artemis is the assistant, Omega is the workspace, and Operator Mode is separate from Chat Mode.

### Current Frontend Boundaries

- `ArtemisChatShell` = normal user chat.
- `OmegaWorkspaceShell` = multi-chat workspace.
- `ArtemisOperatorPanel` = autonomous work/operator mode.
- Hermes remains internal executor infrastructure behind the Artemis Operator adapter.
- OpenClaw remains external gateway/infrastructure context only and is not a Frontier AI product layer.

### What Was Intentionally Not Changed

- No storage migration was performed.
- No localStorage keys or conversation folder names were migrated.
- No Hermes runtime files were renamed or deleted.
- No OpenClaw setup was changed.
- Existing Operator commands and approval gates were preserved.
- Existing internal Hermes-named variables remain where renaming would add risk without changing behavior.
- No deploy, commit, or push was performed.

### How This Improves Product Boundaries

- New Chat Mode work can now attach to `ArtemisChatShell` instead of growing the workspace page.
- New Omega multi-chat/storage work can now attach to `OmegaWorkspaceShell` without touching Operator UI.
- New autonomous coding/computer-working UI can now attach to `ArtemisOperatorPanel` while Hermes stays hidden behind adapters.
- Later storage migration can happen per boundary instead of inside one mixed page.

### Next Recommended Smallest Safe Step

Move the remaining normal chat state and Omega workspace state out of `AgentWorkspacePage.tsx` into the new shell components one slice at a time. Start with the low-risk Chat Mode state, then move Omega conversation/tab state, and leave Operator mission state for last because it has the most approval and runtime coupling.

## Artemis Chat State Refactor Implemented

Date: 2026-05-09

### Files Modified

- `src/components/artemis/ArtemisChatShell.tsx`
  - Owns normal Chat Mode draft text, input focus, sending state, per-section message history, default empty state, quick prompts, new-chat clearing, and assistant message rendering.
  - Calls the Artemis Chat adapter directly through `artemisChat.requestReply` for normal assistant replies.
  - Keeps an optional route hook for special commands that need page-level state.

- `src/components/AgentWorkspacePage.tsx`
  - No longer owns normal Artemis Chat message/input/send state.
  - Provides a narrow `onRouteMessage` callback only for special compatibility behavior: conversation archive commands, Operator handoff, and Omega Coding Bridge handoff.
  - Receives message snapshots from `ArtemisChatShell` only to preserve the existing conversation archive autosave path.

- `src/components/FrontierLandingPage.tsx`
  - Adds a comment clarifying that `New Hermes chat` detection is legacy storage compatibility, not user-facing Hermes branding.

- `FRONTIER_AI_ARCHITECTURE_AUDIT.md`
  - Documents this state-boundary follow-up.

### What Chat State Moved

- Active normal chat messages.
- Normal chat draft/input text.
- Input focus and Enter-to-send behavior.
- Sending/thinking state.
- User-message append and assistant-message append.
- Default new Artemis chat clearing.
- Normal Artemis adapter call for default replies.

### What Stayed In `AgentWorkspacePage.tsx`

- Route-level section/workspace selection.
- Shared layout, theme controls, and navigation.
- Omega workspace state and agent chat state.
- Artemis Operator mission/request/approval state.
- Special command routing that depends on page-level Operator/Omega/archive state.
- Conversation archive snapshot compatibility.

### What Was Intentionally Not Changed

- No Omega conversation storage migration.
- No Omega workspace state move yet.
- No Operator mission state move yet.
- No Hermes runtime file rename or deletion.
- No OpenClaw setup change.
- No approval gate changes.
- No stored thread rename or migration.

### How This Improves Boundaries

- Normal Artemis Chat can now evolve inside `ArtemisChatShell` without adding more chat state to `AgentWorkspacePage.tsx`.
- The workspace page remains a composition layer plus route/state bridge.
- Special Operator/Omega actions still pass through their existing approval-gated page-level flows.

Next smallest safe step: move Omega conversation/tab UI state into `OmegaWorkspaceShell` while keeping the existing local storage and archive behavior untouched.

## Omega Workspace UI State Refactor Implemented

Date: 2026-05-09

### Files Modified

- `src/components/omega/OmegaWorkspaceShell.tsx`
  - Owns the active Omega workspace view (`omega`, `map`, `linear`).
  - Owns Omega workspace draft text, composer refs, focus behavior, empty-draft focus, and UI submit/swarm wrappers.
  - Owns the local Omega conversation list UI, active local conversation selection, new-conversation action, refresh action, and local empty/error states.
  - Records submitted Omega chat/swarm exchanges through the existing Omega conversation store adapter.
  - Keeps using the adapter-backed legacy local storage format; no keys, folders, or saved thread IDs were migrated.

- `src/components/AgentWorkspacePage.tsx`
  - No longer owns Omega tab/view state or Omega workspace composer draft/ref state.
  - Provides callbacks for existing Omega message handling, swarm runs, archive compatibility, Operator handoff, Coding Bridge behavior, and adapter-safe exchange summaries.
  - Preserves the existing `AGENT_WORKSPACE_STORAGE_KEY` snapshot behavior by patching `omegaView` through the shell callback instead of migrating storage.

### What Stayed In `AgentWorkspacePage.tsx`

- Omega agent roster, selected category, selected agent, and agent messages.
  - This stays temporarily because agent messages still feed local model routing, swarm output, archive snapshots, and Operator/Coding Bridge handoffs.
- Local AI setup, credential setup, usage metering, and device profile state.
- Conversation archive autosave/command compatibility.
- Artemis Operator mission/request/approval state.
- Omega Coding Bridge special route handling.

### What Was Intentionally Not Changed

- No Omega conversation storage migration.
- No `.omega` folder layout or saved thread ID migration.
- No Operator mission state move.
- No Hermes runtime rename or deletion.
- No approval gate changes.
- No existing saved thread is auto-selected for writes; old local conversations are listed and selectable, while a fresh Omega exchange creates a fresh adapter-backed conversation unless the user picks an existing one.

## Artemis Operator UI State Refactor Implemented

Date: 2026-05-09

### Files Modified

- `src/components/artemis/ArtemisOperatorPanel.tsx`
  - Owns Operator Mode identity, mission draft text, mission autonomy/max-runtime/keep-awake controls, selected mission, selected request, panel busy state, local Operator error state, approval/status display, mission details, request stdout/stderr display, execution logs, and empty states.
  - Calls the Artemis Operator adapter for panel-owned actions: safe request creation, mission creation, request approval/cancel, mission pause/resume/cancel, and output copy.
  - Uses a focus seed so route-level handoffs can focus a request or mission without `AgentWorkspacePage.tsx` owning selection state.

- `src/components/AgentWorkspacePage.tsx`
  - No longer owns normal Artemis Operator mission draft/config state or selected mission/request UI state.
  - Provides Operator data arrays, health/error status, refresh callbacks, result-change callbacks, and a focus seed for compatibility handoffs.
  - Keeps Omega Coding Bridge and chat command routing on the page because those flows still combine Omega context, archive compatibility, local model routing, and Operator mission creation.

### What Operator State Moved

- Mission draft/input state.
- Operator mission configuration UI state.
- Selected/current mission and request display state.
- Operator panel loading/error state for panel actions.
- Approval warning/status display.
- Execution log, stdout, stderr, changed-files, and check-result display state.
- Safe Operator action buttons for checks, mission start, approvals, cancels, and mission controls.

### What Stayed In `AgentWorkspacePage.tsx`

- Polling health, requests, missions, capabilities, and credential status.
- Route-level Operator handoff compatibility from Artemis Chat and Omega Workspace.
- Omega Coding Bridge mission/control compatibility.
- Archive snapshot/reporting compatibility.
- Dispatching completed Operator results back into the Omega agent bus.

### What Was Intentionally Not Changed

- No Hermes runtime file was renamed or deleted.
- No executor behavior, patch behavior, rollback behavior, or approval policy was changed.
- No approval gate was bypassed or auto-approved.
- No storage migration was performed.
- No dependency install, deploy, commit, or push was performed.

### How This Improves Product Boundaries

- `ArtemisOperatorPanel` now owns Operator Mode UI state and presents Hermes-backed execution through the Artemis Operator adapter.
- `AgentWorkspacePage.tsx` is closer to a composition and compatibility bridge instead of owning every product surface’s UI state.
- Hermes remains the internal executor layer behind Artemis Operator.

### Next Recommended Smallest Safe Step

Create a thin integration/status layer that lets `AgentWorkspacePage.tsx` consume only shell-level summaries from Artemis Chat, Omega Workspace, and Artemis Operator.

## Shell Status Integration Layer Implemented

Date: 2026-05-09

### Files Modified

- `src/components/workspace/workspaceShellStatus.ts`
  - Adds compact, presentation-friendly status contracts for Artemis Chat, Omega Workspace, and Artemis Operator.
  - Keeps summaries limited to labels, counts, busy/error state, and display text; no raw logs, secrets, or low-level executor internals are exposed.

- `src/components/artemis/ArtemisChatShell.tsx`
  - Emits `ArtemisChatShellStatus` through an optional `onStatusChange` callback.
  - Reports section identity, message count, draft/sending state, last activity label, and compact summary text.

- `src/components/omega/OmegaWorkspaceShell.tsx`
  - Emits `OmegaWorkspaceShellStatus` through an optional `onStatusChange` callback.
  - Reports active view, active workspace/conversation label, local conversation count, draft/busy/error state, and compact summary text.

- `src/components/artemis/ArtemisOperatorPanel.tsx`
  - Emits `ArtemisOperatorShellStatus` through an optional `onStatusChange` callback.
  - Reports Operator online/busy/error state, approval count, queued/running count, mission count, selected mission/request display labels, and compact summary text.

- `src/components/AgentWorkspacePage.tsx`
  - Stores only shell-level status summaries from the three product shells.
  - Adds a small page-level status strip for Artemis Chat, Omega Workspace, and Artemis Operator.
  - Continues to own route/layout state, archive compatibility, Operator handoff compatibility, Omega Coding Bridge compatibility, local model routing, and shared page composition.

### What Was Intentionally Not Changed

- No storage migration or schema change.
- No Hermes runtime rename, deletion, or execution behavior change.
- No approval policy change or approval bypass.
- No OpenClaw setup change.
- No dependency install, deploy, commit, or push.

### How This Improves Product Boundaries

- `AgentWorkspacePage.tsx` can now show cross-shell status without reclaiming normal UI state from Artemis Chat, Omega Workspace, or Artemis Operator.
- The shells remain responsible for their own drafts, selections, busy states, empty states, and product-specific display logic.
- Hermes remains the internal executor layer behind Artemis Operator, while user-facing status language stays on Artemis/Omega product terms.

### Next Recommended Smallest Safe Step

Reduce `AgentWorkspacePage.tsx` by extracting route/special-command handling into a dedicated workspace controller hook without changing behavior.

## Native Artemis Gateway Skeleton Implemented

Date: 2026-05-08

### Files Added

- `src/lib/artemis/gateway/sessionManager.ts`
  - Defines native Artemis Gateway session types:
    - `user_chat`
    - `omega_conversation`
    - `operator_mission`
    - `channel_session`
    - `tool_session`
  - Provides lightweight in-memory create, get, list, update, touch, and clear helpers.
  - Keeps persistence intentionally out of scope for this pass.

- `src/lib/artemis/gateway/toolRegistry.ts`
  - Defines a formal Artemis tool registry.
  - Defines tool categories for chat, Omega storage, Operator, Hermes executor, local model, paid model, Twilio, file system, browser, terminal, and future channels.
  - Provides safe lookup/list/register/count helpers.
  - Does not execute tools directly.

- `src/lib/artemis/gateway/permissionPolicy.ts`
  - Defines gateway risk tiers from read-only through destructive/secret-sensitive actions.
  - Encodes approval rules for local writes, code patches, outbound messages, paid APIs, deploys, commits, pushes, public tunnels, money, destructive actions, and secrets.
  - Returns decisions only; it does not bypass existing Hermes or Artemis approval gates.

- `src/lib/artemis/gateway/modelRouter.ts`
  - Defines provider categories:
    - `local_model`
    - `codex`
    - `openai_paid`
    - `deterministic_local_tool`
  - Provides lightweight selection logic for chat, coding/operator tasks, deterministic actions, memory retrieval, and tool execution.
  - Marks paid model fallback as approval-required unless explicitly allowed by configuration.

- `src/lib/artemis/gateway/artemisGateway.ts`
  - Central native Artemis Gateway module.
  - Coordinates sessions, event recording, tool counts, model routing, and permission decisions.
  - Exposes:
    - `createGatewaySession`
    - `getGatewaySession`
    - `listGatewaySessions`
    - `routeGatewayMessage`
    - `registerGatewayEvent`
    - `getGatewayStatus`

- `src/lib/artemis/gateway/index.ts`
  - Clean export barrel for the gateway modules.

- `ARTEMIS_NATIVE_GATEWAY_PLAN.md`
  - Captures the completed skeleton, missing OpenClaw-like features, recommended build order, channel adapter roadmap, daemon/status roadmap, and testing checklist.

### Files Modified

- `src/components/AgentWorkspacePage.tsx`
  - Adds a read-only `Artemis Gateway Status` section.
  - Shows gateway status, session count, registered tool count, approval policy status, model routing availability, and in-memory storage mode.
  - Does not create sessions, execute tools, send messages, or change approvals from the UI.

- `FRONTIER_AI_ARCHITECTURE_AUDIT.md`
  - Documents this gateway skeleton implementation.

### How Artemis Gateway Differs From OpenClaw

- Artemis Gateway is native Frontier AI architecture, not an OpenClaw integration.
- It is designed around Artemis Chat, Artemis Operator, Omega local conversation storage, Hermes internal execution, Frontier knowledge/memory, and local approval policy.
- OpenClaw remains external infrastructure and is not treated as a product layer, runtime dependency, or required backend.
- The new gateway skeleton represents the OpenClaw-like shape the product needs, but under Frontier-owned naming, policy, storage, and routing.

### What Was Intentionally Not Implemented Yet

- No Slack, Discord, Telegram, WhatsApp, email, or calendar integration.
- No OpenClaw integration, uninstall, migration, or dependency.
- No Hermes runtime file renames.
- No `.artemis`, `.omega`, `.hermes-hands`, or localStorage migration.
- No persistent gateway database.
- No real tool execution from the gateway.
- No daemon changes.
- No deploy, commit, or push.

### Checks Run

- `npm run typecheck`
  - Passed.

- `npm run lint`
  - Passed with 11 existing Fast Refresh warnings in shared UI/context files.

- `npm run build`
  - Passed.
  - Vite reported the existing non-failing large chunk warning for the main bundle.

### Next Smallest Safe Step

Add a persistent gateway status snapshot written by the existing Artemis controller or Hermes/Operator server, then have the UI read that snapshot. This should stay read-only first. After that, add a tiny `routeGatewayMessage` call from Artemis Chat that records sessions/events without changing reply behavior.

## Owner-Approved Twilio Voice Calling Implemented

Date: 2026-05-08

### Files Added

- `src/lib/artemis/channels/twilioVoiceAdapter.ts`
  - Adds the first Artemis channel adapter for Twilio voice.
  - Creates, validates, risk-labels, and summarizes owner call requests.
  - Marks voice calls as `tier_4_external_action`.

- `server/lib/twilioOwnerCall.js`
  - Adds server-side Twilio outbound call logic without exposing credentials to the browser.
  - Loads `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, and `ARTEMIS_OWNER_PHONE` from env.
  - Supports direct Twilio or a Twilio-compatible SignalWire LaML base URL through `TWILIO_COMPATIBLE_API_BASE_URL`.
  - Generates simple TwiML and calls only the configured owner phone.
  - Returns safe JSON with provider, action, status, call SID, approval requirement, and error.

- `scripts/test-artemis-twilio-call.mjs`
  - Adds the explicit owner test call script.
  - Uses the message: "This is Artemis. Twilio calling is connected."
  - Uses the reason: "Testing Artemis owner call."

### Files Modified

- `scripts/artemis-controller.mjs`
  - Adds `POST /api/artemis/twilio/call-owner`.
  - Restricts the endpoint to loopback/local-origin requests.
  - Requires `approvalStatus: "owner_approved"` or `testMode: true`.

- `src/lib/artemis/gateway/toolRegistry.ts`
  - Registers `twilio_voice_call_owner`.

- `src/lib/artemis/gateway/permissionPolicy.ts`
  - Confirms outbound calls, texts, emails, paid APIs, deploys, commits, pushes, public tunnels, spending money, and external actions require approval.
  - Blocks arbitrary outbound phone destinations until allowlists and audit workflows exist.

- `src/components/AgentWorkspacePage.tsx`
  - Adds a read-only Twilio Voice status tile to the Artemis Gateway Status panel.

- `scripts/configure-artemis-twilio.mjs`
  - Tracks `ARTEMIS_OWNER_PHONE` in setup/status output.

- `.env.example`, `.env.worker.example`, `README.md`, `docs/artemis.md`, `docs/artemis-messaging-connectors.md`, and `ARTEMIS_NATIVE_GATEWAY_PLAN.md`
  - Document required env, safety rules, and `npm run artemis:test-call`.

### What Is Working

- Artemis has a real owner-only Twilio voice action.
- The test command can place a real call only to `ARTEMIS_OWNER_PHONE`.
- The local API endpoint does not accept arbitrary destination numbers.
- Twilio credentials stay server-side.
- The official Twilio SDK was not installed; the implementation uses Node HTTPS against Twilio REST.

### What Is Intentionally Not Implemented Yet

- No arbitrary outbound phone numbers.
- No public frontend call button.
- No channel allowlist UI.
- No recurring or automatic call scheduling.
- No OpenClaw dependency.
- No Hermes runtime rename.
- No deploy, commit, or push.

### Next Smallest Safe Step

Add a persisted owner-call audit log under `.artemis/gateway/events.jsonl` or `.artemis/communications/calls.jsonl`, recording request ID, approval status, reason, provider status, and call SID without storing credentials or full phone numbers.

## SignalWire Owner-Only Communication Loop Implemented

Date: 2026-05-08

### Files Modified

- `server/lib/artemisCommunicationOs.js`
  - Adds owner-only defaults for Joseph / Jo Sim, SignalWire as the active provider, quiet hours, and draft/approval-first policy.
  - Adds owner profile/contact initialization under `.artemis/`.
  - Adds owner instruction routing to convert local owner instructions into structured safe tasks.
  - Adds SignalWire/Twilio-compatible SMS, MMS, call, and generic communication audit helpers.
  - Keeps Telegram, WhatsApp, email, and push as disabled placeholders with health checks only.

- `scripts/artemis-controller.mjs`
  - Prefers `ARTEMIS_OWNER_PHONE` for SignalWire/Twilio-compatible owner messaging.
  - Records outbound SMS/MMS/call queue, send, success, and failure events into the Communication OS audit/inbox.
  - Adds `owner-loop` commands for status, defaults, instruction ingest, and owner prompt drafts.
  - Adds a local inbound SMS webhook placeholder at `POST /webhooks/twilio/sms`.

- `scripts/test-artemis-twilio-call.mjs`
  - Records the explicit owner-only test call in the call audit and unified inbox.

- `src/components/ArtemisUnifiedInboxPanel.tsx`
  - Narrows the current UI to the SignalWire owner timeline while preserving the future-compatible inbox schema.

- `scripts/test-artemis-personal-os.mjs`, `scripts/test-artemis-channels.mjs`, and `scripts/test-artemis-onboard.mjs`
  - Cover owner defaults, owner instruction routing, SignalWire audit logging, disabled Telegram health, and onboarding placeholders.

- `.env.example`, `README.md`, `ARTEMIS_NATIVE_GATEWAY_PLAN.md`, and `docs/artemis-personal-communication-os.md`
  - Document SignalWire-first owner-only mode, disabled placeholders, owner loop commands, audit files, and local-only webhook posture.

### What Changed

- SignalWire is now the only active real provider in the local Communication OS policy.
- Owner-only contact mode is seeded into `.artemis/contacts.json`, `.artemis/owner-profile.json`, and `.artemis/approval-policy.json`.
- Every owner SMS/MMS/call queue/send attempt now has a local audit/inbox trail without printing credentials.
- Artemis can record owner instructions and produce structured safe local task plans.
- Telegram, WhatsApp, email, and push are visible but policy-disabled.

### Intentionally Not Changed

- Existing SignalWire/Twilio-compatible owner test call behavior was not broken.
- No public tunnel or permanent webhook URL was added.
- No Telegram, WhatsApp, email, or push real send/receive integration was enabled.
- No non-owner contact communication was enabled.
- No approval gate was bypassed.
- No OpenClaw dependency or Hermes rename was introduced.

### Next Smallest Safe Step

Add a small SignalWire owner status sender that can send a preapproved owner-only SMS for task progress, still logged through the same audit path and still blocked during quiet hours except urgent/owner-requested workflows.
