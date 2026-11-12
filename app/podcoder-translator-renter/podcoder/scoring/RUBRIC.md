# Simco SI Lifebook scoring rubric (v1)

Words come first. A 0-100 number exists for every category on every day, but the
API returns it only with `?details=1` (the "details view"). Nothing here is
medical advice. All demo data is synthetic.

## Score per category per day

```
score = clamp(50 + 25*M + 25*X + 10*G, 0, 100)    rounded to an integer
```

| Part | Range | What it is |
|---|---|---|
| Base | 50 | Neutral starting point, maps to "Steady". |
| **M**: memory tone | -1..+1 | Chats tagged with this category in the last 7 days. Each tag counts +1 when its tone is *doing well*, 0 when *in play*, -1 when *strained*. Weighted by recency (0.85^days_ago) and shrunk toward 0: `sum(w*tone) / (sum(w) + 0.5)`, so one chat cannot swing a score fully. |
| **X**: metrics | -1..+1 | Mean over this category's metrics (table below) of the 7-day average of each metric's normalized value. A metric needs at least 3 readings in the window, otherwise it is left out. |
| **G**: goals | -1..+1 | For each goal in this category: `clamp(2*(progress - expected), -1, 1)`, where `expected` is the share of the goal's time window that has passed. Averaged across goals. |

A part with no data contributes 0 and is listed under `missing` in the details.
When a category has **no** memory tags in the last 14 days, no metrics and no goals,
the score is `null` and the word is **Not discussed** (the existing Lifebook status word).

### Metric normalization (each to -1..+1)

| Metric | Categories | Normalization |
|---|---|---|
| sleep_hours | Health and Fitness | +1 inside 7-9 h; falls linearly to -1 at 5 h or 11 h |
| steps | Health and Fitness | (steps - 6000) / 4000 |
| exercise_min | Health and Fitness | (minutes - 20) / 20 |
| sleep_quality (1-10) | Health and Fitness, Quality of Life | (x - 5.5) / 4.5 |
| mood (1-10) | Emotional Life | (x - 5.5) / 4.5 |
| stress (1-10, inverted) | Emotional Life, Quality of Life | (5.5 - x) / 4.5 |
| focus (1-10) | Career, Intellectual Life | (x - 5.5) / 4.5 |
| spending (inverted) | Financial Life | (30-day median - x) / 30-day median |

All are clamped to -1..+1. Categories without metrics (Character, Spiritual Life,
Love Relationship, Parenting, Social Life, Life Vision, Sex and Sensuality) are
scored from memory tone and goals only.

## Words

| Score | Word |
|---|---|
| 75-100 | **Thriving** |
| 60-74 | **Growing** |
| 45-59 | **Steady** |
| 0-44 | **Needs care** |
| no data | **Not discussed** |

`level` is the word's position (0 = Needs care ... 3 = Thriving) for charts that
plot words as lanes; it is not a score.

## Trend word

Mean score of the last 7 days vs the 7 days before: up by 5+ is **rising**, down by
5+ is **slipping**, otherwise **holding**. Fewer than 3 scored days in either window: **new**. No data today: **quiet**.
