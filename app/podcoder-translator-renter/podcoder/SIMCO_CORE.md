# Simco SI core: memory + scoring + recommendations (offline)

Stdlib-only Python, local JSON per user at `<state>/core/<user>.json`. No GPU, no network,
no live database writes. All demo data is synthetic ("Demo Dana", `user=demo_dana`).

| Piece | Where | What |
|---|---|---|
| Store | `core_store.py` | Load/save the per-user core doc; auto-seeds `demo_dana` on first read. |
| Seed | `seed/seed_demo.py` | 45+ days of synthetic metrics, Lifebook-tagged chats, goals, timeline events; planted lagged effects + gaps; mirrors chats into `lifebook_memory` JSON and the `local_db` `memories` table. `python3 seed/seed_demo.py --state DIR --end 2026-10-30` |
| Scoring | `scoring/engine.py`, `scoring/RUBRIC.md` | 0-100 per category per day from memory tone, metrics and goals; words Thriving / Growing / Steady / Needs care (Not discussed when no data); trend words. |
| Analytics | `analytics/correlate.py` | Spearman on detrended series, lags 0-3, n>=14 to run, missing-data gate, BH-FDR, Fisher-z CI, "finding" vs "early signal", correlation-not-causation caveat. |
| Recs | `recs/engine.py` | Rules -> evidence-linked candidates -> Beta-Bernoulli Thompson sampling; max 3/day, one per category, cooldown; feedback accept/ignore/complete updates arms. |
| API | `core_api.py` (wired in `product_api.try_handle`) | `/api/lifebook/today`, `/api/lifebook/category/<id>`, `/api/timeline`, `/api/recs/today`, `POST /api/recs/feedback`. GET query strings are parsed by both `mission_server.py` and `local/server.py`. |
| SQL | `sql/002_simco_core.sql` | Supabase shape for project wxvjajecvklfjxppawdx with RLS. File only, not applied. |
| Tests | `test_simco_core.py` | `python3 -m pytest -q test_simco_core.py` |

Display rule: words first; `details=1` adds the 0-100 numbers. Timeline contract: `TIMELINE_SCHEMA.md` at the worktree root.

Deferred: threat model, backlog, CI, Supabase sync of the core tables, real wearable imports, crisis-content handling.
