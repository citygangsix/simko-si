# AGENTS.md - Codex Cloud Startup Contract

This repository is cloud-reproducible. Treat this file as the first startup contract for Codex Cloud tasks in this repo.

## Runtime Role

- OpenClaw is the main coding orchestration runtime.
- The MASTER batch runner is the structured mission layer for sequential batches, verify gates, FIX -> RETEST loops, approval gates, and deliverables matrices.
- Artemis coordinates chat/gateway routes and operator checks.
- Hermes Hands and local desktop services are local/downloadable-user surfaces, not required Codex Cloud dependencies.

## First Commands

Start every cloud task by orienting to the repo and running the cloud-safe bootstrap/doctor path when the task involves code changes, verification, OpenClaw, Artemis, Hermes Hands, or migration readiness:

```bash
npm ci
npm run codex:cloud:bootstrap
npm run codex:cloud:doctor
```

Use the focused checks when relevant:

```bash
npm run codex:cloud:startup -- --json
npm run codex:cloud:boundaries -- --json
npm run codex:cloud:migration:audit -- --json
npm run codex:cloud:stabilization-gate
npm run codex:cloud:autocode-run -- --stage pre-pr --template artemis-templates/<feature-name>-master-batch.json
```

## Master Command Prompt Autocode

When the user says `autocode this`, `auto code this`, or makes an obvious coding request, use `artemis-templates/master-command-prompt-autocode.md` as the governing contract.

Use OpenClaw + MASTER batching for the task. Treat the user's task description as one initial prompt. Decompose it into one or more efficient sequential batches, create or update a feature-specific MASTER batch template, execute batches in order, run verification, perform targeted FIX -> RETEST loops for the current batch, and only advance after the current batch passes.

One complete batch is acceptable for small work, but it must still run discovery, planning, implementation, verification, repair if needed, and handoff. Multi-surface or risky work must use multiple sequential batches.

Mandatory completion gate: cloud autocoding must refuse to finish unless completion proof exists. Run `npm run codex:cloud:autocode-completion-gate` when validating final batch/PR proof; use `--stage pre-pr` only before PR creation. MASTER runs must use `--max-verify-loops 999999`; `--max-verify-loops 1` is an incomplete protocol run. In Codex Cloud sessions, include the feature-specific MASTER template path, selected batch count, prompt count, max verify loops, each batch status, retry/fix history, changed files, tests/checks run, risks, approval-gated items not executed, MASTER runner output, HEAD SHA, a valid GitHub PR URL, PR committed file list, and final deliverables completion matrix. Missing proof, a missing/placeholder PR URL, or a one-loop runner command means the run is incomplete.

Stabilization rule: do not keep opening new autocoding protocol PRs for preferences or wording changes. Run `npm run codex:cloud:stabilization-gate` on `main`; if it passes, use the current protocol for the next real product task. Open another protocol PR only when the stabilization gate fails, a live Codex Cloud run fails the mandatory completion gate, the user asks for a specific product capability, or a concrete approval/secret/provider/account/platform blocker must be represented in code.

## Cloud-Safe Execution

- Use Codex Cloud workspace commands, MASTER batch files, deterministic mocks, and route-shape checks instead of Mac GUI automation.
- Do not rely on the user's local terminal, local Codex app session, Mac services, Hermes Hands daemons, private sockets, AppleScript, `launchd`, `systemd`, or desktop automation.
- If a needed capability exists only locally today, stop and report it as a blocker or future downloadable-user feature instead of silently falling back to local execution.
- Keep `package-lock.json` committed and use `npm ci` for dependency parity.

## Approval Gates

Stop and ask for owner approval before:

- deploy or publish actions
- secrets or credential changes
- database writes or migrations
- destructive filesystem actions
- paid provider actions
- production reverse-proxy changes
- live external submissions

Failed tests, lint, typecheck, build, missing files, bad routing, broken UI behavior, failed assertions, and incomplete code are not blockers. Fix and retest the current batch until it passes. If approval is needed and the UI/CLI gives numbered choices, ask the owner exactly which option to choose, then continue after approval.

Do not log tokens or secrets. Do not raw-upload local private state.

## Required References

- `CODEX_CLOUD_REPRO.md`
- `docs/CODEX_CLOUD_STARTUP_CONTRACT.md`
- `docs/CODEX_CLOUD_REPRODUCIBILITY.md`
- `docs/CODEX_CLOUD_AUTOCODING_STABILIZATION_GATE.md`
- `config/codex-cloud-boundaries.json`
- `artemis-templates/master-command-prompt-autocode.md`
- `artemis-templates/master-batch-template.json`
