# Master Command Prompt Autocode

Use this template for Codex Cloud coding requests from this repo.

```text
master command prompt autocode

Use the full OpenClaw autocoding loop as the executor, not manual Codex implementation.

Treat this as one initial prompt. OpenClaw must expand it into one clear executable current prompt increment, create/update the feature-specific MASTER evidence surface for that current increment, execute it, run focused verification, perform targeted FIX->RETEST loops for the current increment, and only create a next prompt after the current increment passes or reaches a real blocker.

Do not manually implement outside the OpenClaw plan/execute/verify/FIX->RETEST/next-batch cycle. If OpenClaw or the MASTER runner cannot execute a needed step, stop and report the exact blocker instead of silently doing it manually.

Use OpenClaw + MASTER proof gates for this task. A "batch" means multiple prompt increments; do not create a multi-batch list unless the owner explicitly requested a prompt pack or the current verified result proves another prompt is needed.

Cost and token efficiency rule:
- Spend the least AI tokens practical while still producing verified, useful work.
- Do not treat a numeric token limit as provider-enforced unless the runtime explicitly supports it.
- Use the fewest prompts that safely satisfy the owner request.
- Do not precompute speculative future prompt/batch lists; future prompts are created only after the current prompt is verified and remaining work is known.
- Do not perform broad repo scans when targeted file discovery is enough.
- Do not dump full `rg --files`, `git ls-files`, `find`, dependency trees, or large file inventories into agent output; use targeted symbol/path searches and open only likely files.
- Do not repeat full lint/typecheck/build/full-test loops after every small edit. Run feature-specific or changed-file checks first, then run heavyweight full checks once for final proof or when targeted evidence shows broader risk.
- For large, broad, app-builder, or product-sized requests, use preview-first approval: produce a concept storyboard preview with one overall dashboard/home image plus one image for every planned tab/page opened, map each picture to the screens/components/data banks that would be coded, include rough token/USD implementation estimate ranges with assumptions and non-guarantee language, then stop with `preview_review_needed` before coding product features.
- Preview artifacts are pictures or static mockups only, not a coded MVP and not speculative production features; do not call paid image providers without owner approval.
- Concept storyboard previews must show the actual expected navigation tabs, data banks, workflows, fields, filters, actions, and major page states for the business domain. If there are 10 tabs, create at least 11 images: one dashboard/home image plus one opened image for each tab.
- Theme, color, density, and visual style can be regenerated before approval; approved tabs, modules, workflows, and data banks become the visual scope contract.
- Use `npm run codex:cloud:preview:first -- --prompt "<approved prompt>" --run-id "<run id>"` or an equivalent local/static manifest for preview-first proof, and record `previewGenerationEvidence`, `conceptStoryboardPreview`, `buildabilityAssessment`, `knownImplementationLimits`, and `previewHonestyContract`.
- After each verified current prompt, run `remainingWorkAudit`. Complete the original user request in the least prompts possible. Do not create future prompts up front; recommend only 1-4 concrete next prompt items from the audit. Create an additional prompt only when it completes something from the original prompt that the current prompt did not complete. If the audit finds four unfinished original-request things left, create four follow-up prompts, one prompt per thing.

The protocol-compliant direct-session entrypoint is:
  npm run codex:cloud:autocode-run -- --stage pre-pr --template artemis-templates/<feature-name>-master-batch.json

Direct `npm run artemis:batch:run` usage may verify a feature-specific template, but it is not final autocoding completion by itself.

Cloud-only execution rule:
- Codex Cloud is the active executor for this task.
- Do not rely on the user's local terminal, local Codex app session, Mac services, Hermes Hands daemons, private sockets, or desktop automation.
- If a needed capability exists only locally today, stop and report it as a blocker or future downloadable-user feature instead of silently falling back to local execution.

Full-stack implementation requirement:
- Build whatever frontend and backend code is necessary to fully achieve the selected current prompt increment.
- When the planner selects preview-first mode for broad/product work, the requested outcome for that run is final-state preview pictures/mockups plus implementation estimates, not product code.
- Do not stop at UI-only changes, backend-only changes, mocks, scaffolding, or partial wiring unless my task explicitly asks for that limited scope or the preview-first plan intentionally stops for owner approval before coding.
- For implementation-approved increments, inspect and update all required frontend components, backend/API routes, data models, server functions, tests, docs, configuration, and route wiring needed for the selected increment to work end-to-end.
- Implementation-approved work is done when every approved user-facing capability has a visible/reachable frontend route, button, menu item, or control; the needed backend/API/service behavior is wired and verified; and `remainingWorkAudit.status` is `complete` with no remaining items.

User-centered product architecture rule:
- Serve each individual user first.
- When a request implies a product, website, app, portal, dashboard, platform, or service for real users, infer the user-serving architecture that a competent product builder would recommend.
- For multi-user or public-facing systems, recommend per-user accounts, authentication, user profile separation, private project/workspace boundaries, durable saved conversations/sessions, and user-owned history by default.
- For coding-through-a-website or Codex Cloud-style products, recommend individual accounts with saved coding conversations, project memory, run history, resumable workspaces, and organization/team separation when relevant.
- If the current prompt scope cannot implement the whole user-account architecture safely, include it in architecture, preview, acceptance criteria, remainingWorkAudit, or approval-gated follow-up instead of silently omitting it.
- Protect the individual user: privacy, consent, export/delete expectations, permission checks, and no cross-user leakage are part of the product architecture, not optional polish.

Task:
<describe the feature, bugfix, or product outcome here>

Protocol requirements:
- Treat my task description as ONE initial prompt.
- Convert that initial prompt into one expanded, clear, direct current prompt before implementation.
- Do not pre-generate a speculative list of future prompts/batches.
- The current prompt increment must have:
  - a clear objective,
  - exact files or modules likely to be touched,
  - explicit deliverables,
  - verification commands,
  - acceptance criteria,
  - approval-gate checks,
  - a FIX -> RETEST loop.
- Execute one prompt increment at a time.
- Do not start prompt N+1 until prompt N has fully passed verification or reached a real blocker.
- If the current prompt fails verification, retry that current prompt with targeted fixes and the smallest failing check until it passes.
- Use targeted retries for the current prompt increment unless blocked by:
  - owner approval requirement,
  - missing API keys, secret keys, tokens, credentials, or private URLs,
  - account login/access/permission issue,
  - paid provider action,
  - deploy/publish action,
  - database write or migration,
  - destructive filesystem action,
  - production reverse-proxy change,
  - live external submission,
  - external service outage or unreachable required external endpoint,
  - a true Codex Cloud platform/tool limitation that prevents execution.
- Failed tests, lint, typecheck, build, missing files, bad routing, broken UI behavior, failed assertions, and incomplete code are not blockers; fix and retest the current prompt increment until it passes.
- Full verification loops are capped by the template/runner; do not rerun the whole suite repeatedly when a focused command answers the current failure.
- If approval is needed and the UI/CLI gives numbered choices, ask me exactly which option to choose, then continue the same prompt increment after approval.
- If truly blocked, stop and report the exact blocker and the exact approval or external input needed.
- Preserve all approval gates. Do not bypass them.
- Always write `remainingWorkAudit` before handoff. Use status `complete`, `needs_followup`, `blocked`, `approval_required`, or `preview_review_needed`; include `remainingItems`, `followupPrompts`, `nextPromptRecommendation`, and `finishCriteriaEvidence`; cap remainingItems at four. When status is `needs_followup`, `followupPrompts` must contain exactly one executable prompt per remaining item, and each remaining item/follow-up prompt must be marked `originalPromptCompletionGap: true`. Do not create follow-up prompts for optional polish, nice-to-have enhancements, speculative expansion, or future work outside the original approved request.

RUNAROUND BREAKER MODE:
- If two FIX -> RETEST loops fail, or if the same user-facing goal remains broken after two prompts, enter RUNAROUND BREAKER MODE before creating another implementation prompt.
- Stop producing generic instructions.
1. Restate the exact final outcome the user wants.
2. List what has already been tried and what each attempt actually proved.
3. Separate local state, repo state, deployed state, provider/account state, secrets/env state, and user-facing browser state.
4. Identify every assumption that may be false.
5. Find the one mismatch that best explains all symptoms.
6. Verify that mismatch with direct evidence before suggesting another action.
7. Do not ask the user to repeat steps unless the evidence proves they are necessary.
8. Produce only the smallest next action that can change the outcome.
9. Define the acceptance test that proves the goal is actually done.
10. If the goal requires approval, secrets, payment, deploy, DNS, or external account access, say that plainly and stop pretending code alone can solve it.
- Record the audit in `remainingWorkAudit.runaroundBreaker` with finalOutcomeWanted, attemptsTried, stateBuckets, falseAssumptions, suspectedMismatch, directEvidence, smallestNextAction, acceptanceTest, and approvalOrExternalAccessRequired.

GRANITE-FIRST / ONE AIDER ROUND / SEED VERIFY (Simco SI on-pod executor, 2026-10-30):
- Granite (raw Ollama /api/chat, Type A prompt) always goes first. Never lead with Aider.
- Up to 2 raw Granite FIX -> RETEST attempts per task.
- Aider: maximum ONE surgical round per task, and only if Granite still fails and the mission allows Aider. Never a second Aider round; after it, verify once and stop with RUNAROUND BREAKER if still failing.
- Seed verify: before any Granite call, the runner confirms the task seed (current file) and objective appear verbatim in the Type A prompt; if either is missing it fails loudly (status seed_verify_fail) and does not call Granite or Aider.

Prompt-increment implementation requirements:
- Create or update a feature-specific MASTER batch template for this exact task, for example:
  artemis-templates/<feature-name>-master-batch.json
- The feature-specific template must include the current prompt increment, its deliverables, and a continuation-decision slot. It must not spend tokens enumerating speculative future increments that may change after verification.
- The feature-specific template must include a deliverables completion matrix.
- The feature-specific template must explicitly verify the actual feature files, routes, UI, docs, tests, and safety/approval gates.
- Do not rely only on the generic `artemis-templates/master-batch-template.json` unless you also create a feature-specific overlay/template for this task.
- The generic `artemis-templates/master-batch-template.json` must not be used as the final protocol template.

Startup commands:
npm ci
npm run codex:cloud:bootstrap
npm run codex:cloud:doctor
npm run codex:cloud:startup -- --json
npm run codex:cloud:boundaries -- --json
npm run codex:cloud:migration:audit -- --json

Prompt execution:
- First, inspect the repo only enough to create the feature-specific current-increment template.
- Then run:
  npm run codex:cloud:autocode-run -- --stage pre-pr --template artemis-templates/<feature-name>-master-batch.json
- If verification fails, run focused FIX -> RETEST commands for the exact failing surface before rerunning a full template gate.
- Mandatory completion gate: do not finish until the feature-specific template path, selected prompt count, prompt count, MASTER runner output, HEAD SHA, PR URL, and PR committed file list are present in the final report. For GitHub Actions/website autocoding, `npm run codex:cloud:autocode-completion-gate -- --stage pre-pr` must pass before commit/PR automation, and the post-PR gate must write the final report after PR creation.

Coding rules:
- Patch only canonical branch files.
- Execute from the Codex Cloud workspace only; do not require local services or this local Codex session.
- Build the frontend and backend surfaces required for the outcome to work end-to-end.
- Preserve approval gates for deploy, publish, secrets, database writes/migrations, destructive actions, paid providers, production reverse-proxy changes, and live external submissions.
- Do not call paid APIs or external providers without approval.
- Do not add secrets or credentials.
- Do not log tokens or secrets.
- When the task needs API keys, tokens, URLs, webhook secrets, service role keys, deployment tokens, or other provider values, use the generalized autocoding credential guide: give the official provider link, request a screenshot checkpoint before any value is revealed or copied, and route the actual value only to the Artemis Secret Vault smoke box or an approved server-side secret destination.
- Do not raw-upload local private state.

Verification:
- Run all verification commands from the feature-specific current-increment template.
- Verification must cover the full implemented surface: frontend behavior, backend/API behavior, data persistence or migrations when needed, route wiring, integration points, and user-facing acceptance criteria.
- Run relevant repo checks such as:
  npm run typecheck
  npm run lint
  npm run build
  <feature-specific test commands>
- Prefer changed-file and feature-specific checks before broad repo checks; run heavyweight full checks once as final proof unless targeted evidence shows they are needed again.
- If this is a perceptible web app UI change, attempt a screenshot and report if the environment cannot capture one.

Deliverable report:
- Report:
  - the expanded current prompt,
  - the generated current-increment plan,
  - the feature-specific MASTER template path,
  - selected prompt count,
  - prompt count,
  - current increment status,
  - retry/fix history,
  - changed files,
  - tests/checks run,
  - risks,
  - approval-gated items not executed,
  - final deliverables completion matrix,
  - MASTER runner output,
  - HEAD SHA,
  - PR URL,
  - PR committed file list,
  - branch-protection required-check proof.

Git/PR:
- Commit the final changes on the current branch.
- Open a PR with a title and body summarizing the current prompt increment, implementation, tests, and approval gates.
- Run the final gate only after PR creation. Final/post-PR proof must fail closed until the report has a real GitHub PR URL, clean/matching HEAD and committed-file proof, and GitHub branch-protection or required-check policy proof.
```


