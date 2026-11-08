# On-pod MASTER autocode loop (quick integrate)

## What the GitHub template actually gives you

From `master-command-prompt-autocode.md` + `master-batch-template.json`:

1. One everyday ask → feature-specific `*-master-batch.json` (not the generic alone).
2. Sequential batches; verify; FIX→RETEST current batch only.
3. Approval gates (rent/deploy/secrets stay human).
4. RUNAROUND BREAKER after 2 failed loops on the same goal.
5. Codex Cloud `npm run codex:cloud:autocode-run` is Frontier-stack specific — **do not require that on Vast**.

Runnable essence for the renter app = (2)+(3)+(4) + Joseph’s Granite-first / Aider-only-when-necessary.

## What the renter/translator already has

| Piece | Status |
|-------|--------|
| Everyday → Type A (`everyday_to_granite` + `/api/translate`) | Local workbench; Utah Gate2 has detectIntent/buildPayload |
| Chat + picker + Send → Ollama `/api/chat` | Gate5 PASS |
| Confirm-gated rent UI | batch-5 / Gate6 in flight |
| Granite recipe knobs | Locked |
| Aider on pod | Used surgically |

Gap: after Send, **Researchy/AutoCoder still babysit** verify → next batch → Aider decision. Nothing on the pod owns the MASTER loop.

## Quick integrate (smallest autonomous path)

Add one **on-pod daemon** the rented box starts with Ollama. The chat/renter UI only drops a mission JSON; the daemon runs without Researchy.

### Mission JSON (drop folder or POST)

```json
{
  "id": "mission-…",
  "everyday": "add confirm rent button with checkbox",
  "template": "translator-everyday-typea-master-batch.json",
  "workspace": "/workspace/app",
  "model": "granite4.2:8b-q8_0",
  "seed": "path/to/current.html",
  "allowAider": true,
  "allowRent": false
}
```

### Daemon loop (per batch in template)

1. **Translate** everyday/current batch objective → Type A payload (reuse `everyday_to_granite` / Utah detectIntent).
2. **Granite primary:** `POST localhost:11434/api/chat` (think:false, temp 1.0, top_p 0.95, num_ctx≥8192). Abort if no useful tokens in 60–90s.
3. **Write** model HTML/patch into workspace; record artifact.
4. **Verify** batch `verify.commands` / click-assert / file checks.
5. On FAIL: FIX→RETEST with a tighter Type A rewrite (same batch). After 2 fails → if `allowAider`, **one surgical Aider**; else RUNAROUND BREAKER and stop with report.
6. On PASS: advance to next batch. Never call Vast rent/destroy unless mission `allowRent` **and** Joseph exact words already recorded in mission.
7. Write `mission-status.json` + `final-response.md` the UI polls.

### UI wiring (translator/renter)

- New control: **Run autonomous mission** (after target picked).
- Copies selected feature batch + everyday text to pod via existing Send channel **or** scp/`/api/mission` once Gate6 rent has a reachable host.
- Status panel polls `mission-status.json` (PASS/FAIL/blocked/approval_required).
- Rent remains confirm-gated; autonomous loop never rents.

### Ship kit on rent (post-confirm provision)

After Confirm Rent → Install runs (Ollama+Granite+Aider smoke) → then chat/calc. The official script is `install-on-pod-q8.sh`: official Ollama install.sh if missing, `granite4.2:8b-q8_0` only when the weights are absent, `pip install aider-chat`, smoke (`ollama list`, generate, `aider --version`), then this kit on `/opt/podcoder`. No CUDA-library rsync. No automatic Vast destroy. Utah 58092881 was shut by Joseph and is not a live box. The translator does not chat or run calc while Install is in progress.

When a computer is rented (Joseph-approved), bootstrap once:

```
/opt/podcoder/
  master-batch-template.json
  translator-everyday-typea-master-batch.json
  master-command-prompt-autocode.md   # policy text for prompts
  everyday_to_granite.py
  pod_autocode_runner.py             # NEW thin loop
  systemd or nohup: runner + ollama
```

No Codex Cloud npm. No Researchy webhook required for the happy path.

## What not to port yet

- Full OpenClaw / Hermes / Codex Cloud bootstrap
- Preview-first storyboard / Stripe / multi-user Omega batches
- Unlimited Aider thrash

## Suggested next AutoCoder batch (after Gate6 rent-confirm PASS)

`batch-7-onpod-runner`: implement `pod_autocode_runner.py` + `/api/mission` (or file drop) + status poll in translator UI; dry-run on Utah **without** new rent; Granite-first; Aider only if necessary; stop at approval_required for rent.

## Success criteria

Joseph types one everyday mission in the renter UI → picks cloud computer → Run → Utah (or next rented box) walks batches alone → UI shows matrix → Researchy only wakes on blocker/approval or final report.
