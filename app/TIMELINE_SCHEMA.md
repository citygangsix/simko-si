# `/api/timeline` schema — `simco.timeline.v1` (FINAL for the first release)

Served by the existing Python servers (`podcoder/mission_server.py` and `local/server.py`,
both via `product_api.try_handle` -> `core_api`). Offline, local JSON; no GPU, no network.
Sample response (Demo Dana, 45 days ending 2026-10-30, words only):
`/workspace/simco-core-wt/sample_timeline.json`.

## Request

`GET /api/timeline?user=demo_dana` (or `POST /api/timeline` with the same keys as JSON)

| Param | Default | Notes |
|---|---|---|
| `user` | `default` | Use `demo_dana` for the synthetic demo. Auto-seeds on first call. |
| `token` | — | Signed-in token; wins over `user`. 401 if invalid. |
| `end` (or `day`) | last day with data | `YYYY-MM-DD` |
| `start` | `end - days + 1` | `YYYY-MM-DD` |
| `days` | `45` | Used when `start` is not given. Max range 366 days. |
| `categories` | all 13 | Comma list of Lifebook ids, e.g. `health_fitness,career`. Unknown id -> 400. |
| `details` | off | `details=1` adds the 0-100 `score` to each Lifebook cell. **Default UI must not show numbers.** |

Errors: `{ "ok": false, "error": "..." }` with 400 (bad date/category/range) or 401.

## Response

```jsonc
{
  "ok": true, "vast_calls": 0, "destroyed": false,
  "schema": "simco.timeline.v1",
  "user": "demo_dana",
  "display_name": "Demo Dana (fictional, synthetic)",
  "synthetic": true,                    // show a "synthetic demo data" badge when true
  "details": false,
  "range": { "start": "2026-09-16", "end": "2026-10-30", "days": 45 },
  "levels": ["Needs care", "Steady", "Growing", "Thriving"],   // ascending; index == cell.level
  "no_data_word": "Not discussed",                              // cell.level is null for this word
  "categories": [ { "id": "health_fitness", "label": "Health and Fitness" }, ... ],  // display order
  "metrics": [ { "key": "sleep_hours", "label": "Sleep", "unit": "h", "min": 3, "max": 11 }, ... ],
  "event_kinds": ["milestone", "life_event", "workout", "gap"],
  "display_rule": "Words first. Numbers (0-100) only in the details view: add details=1.",
  "days": [                              // one entry per calendar day, oldest first, no holes
    {
      "day": "2026-10-30",               // ISO date (local calendar day, no time zone)
      "weekday": "Fri",
      "lifebook": {                      // key = category id, one per requested category
        "health_fitness": { "word": "Growing", "level": 2 },          // + "score": 67 with details=1
        "sex_and_sensuality": { "word": "Not discussed", "level": null } // + "score": null
      },
      "metrics": {                       // key = metrics[].key; null = missing reading (draw a gap)
        "sleep_hours": 6.4, "sleep_quality": 5.0, "steps": 5250, "exercise_min": null,
        "mood": 5.7, "focus": 5.0, "stress": 4.9, "spending": 23.82
      },
      "events": [                        // starting on this day; may be empty (example from 2026-10-27)
        { "id": "ev-2026-10-27-life_vision", "kind": "milestone", "category": "life_vision",
          "title": "Wrote the one-year vision", "detail": "", "day": "2026-10-27",
          "end_day": "2026-10-27", "synthetic": true }
      ],
      "milestone": null,                 // convenience: first milestone/life_event title, else null
      "workout": null,                   // convenience: workout title (e.g. "Run 5 km"), else null
      "chats": 2,                        // memory entries (chat lines) logged that day
      "gap": false                       // true inside a "gap" event (e.g. vacation, no tracking)
    }
  ]
}
```

### Field rules (stable for v1)
- `days` always covers `range` exactly, one item per day in order, even when a day has no data.
- `lifebook[cat].word` is one of `levels` or `no_data_word`. `level` is the word's index
  (0..3) or `null`; use it to place lane colours. It is **not** a score.
- `lifebook[cat].score` (integer 0-100 or null) appears **only** when `details=1`.
- `metrics` values are raw readings (hours, steps, minutes, 1-10 check-ins, USD); `null` means missing.
  Exercise `0` means a logged rest day, `null` means no reading.
- Multi-day events (`kind: "gap"`) appear once, on their start `day`, with `end_day`; every covered
  day has `gap: true`.
- Additive changes only within v1 (new keys may appear; existing keys keep their meaning).

## Mapping from the mockup's `TIMELINE_DEMO` shape

| Mockup (`timeline-data.js`) | v1 |
|---|---|
| `date` (Date) | `new Date(day + "T00:00")` |
| `sleep` | `metrics.sleep_hours` |
| `steps` | `metrics.steps` |
| `workout` | `workout` |
| `mood` (word) | `metrics.mood` (1-10) — bucket for display if needed |
| `milestone` | `milestone` |
| `lifebook[label]` (word) | `lifebook[id].word` (labels from `categories`) |
| `levels` | `levels` (same order) |

## Related endpoints
- `GET /api/lifebook/today?user=demo_dana[&details=1]` — 13 categories: word, level, trend word, summary.
- `GET /api/lifebook/category/<id>?user=demo_dana[&days=30][&details=1]` — history, recent memories, goals, patterns.
- `GET /api/recs/today?user=demo_dana` — up to 3 actions with evidence, effort and measurement plan.
- `POST /api/recs/feedback` `{ "user": "demo_dana", "rec_id": "...", "action": "accept|ignore|complete" }`.
