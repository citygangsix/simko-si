# Codex Cloud Repro

This repo contains a cloud-safe OpenClaw + MASTER autocoding contract for Codex Cloud sessions.

Run this before coding work:

```bash
npm ci
npm run codex:cloud:bootstrap
npm run codex:cloud:doctor
npm run codex:cloud:startup -- --json
```

For `autocode this` requests, Codex Cloud must use the MASTER flow:

1. Treat the task as one initial prompt.
2. Create or update `artemis-templates/<feature-name>-master-batch.json`.
3. Select one or more efficient batches.
4. Run `npm run artemis:batch:run -- --template artemis-templates/<feature-name>-master-batch.json --max-verify-loops 999999 --json`.
5. Fix and retest the current batch until it passes or an approval/external blocker is reached.
6. Refuse completion unless the final answer includes batch count, prompt count, max verify loops, MASTER runner output, HEAD SHA, a valid GitHub PR URL, PR file list, and the deliverables matrix.

For machine-enforced proof, run `npm run codex:cloud:autocode-run -- --stage pre-pr --template artemis-templates/<feature-name>-master-batch.json` before PR creation. After a real GitHub PR exists, run the same command with `--stage final`, `--head-sha`, `--pr-url`, and `--file-list`. Final proof fails without a valid GitHub PR URL, clean working tree, and committed file list matching HEAD. See `docs/CODEX_CLOUD_AUTOCODE_RUNNER.md`.

Codex Cloud is the active executor. Do not depend on local desktop services, private sockets, Hermes Hands daemons, AppleScript, or the user's local terminal.
