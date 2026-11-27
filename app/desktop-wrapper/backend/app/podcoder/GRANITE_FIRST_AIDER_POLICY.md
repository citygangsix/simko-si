# Granite-first / Aider-only-when-needed (locked 2026-10-28)

Canonical model for this GPU class (RTX 3090 ~24GB high-BW and equals): **`granite4.2:8b-q8_0`** on Ollama `/api/chat`.

## Order (must not invert)
1. Type A prompt (seed-aware surgical rewrite when a file exists)
2. Granite raw (`think:false`, temp 1.0, top_p 0.95, num_ctx≥8192, stream true)
3. Verify
4. Up to 2 raw FIX→RETEST
5. **Aider only if still FAIL** — one surgical round — then RUNAROUND
6. Never lead with Aider. Never invent an unrelated page (e.g. Calculator wipe).

Machine-readable copy lives in `translator-everyday-typea-master-batch.json` → `executorPolicy` + `modelPlan`.
Runner must honor: Granite first even when `allowAider: true`.
