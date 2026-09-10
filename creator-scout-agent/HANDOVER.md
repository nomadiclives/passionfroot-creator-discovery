# Handover — Creator Campaign Scout Agent

**Point reached:** scoring engine complete on **real sourced data**; web app not started.
**Branch:** `claude/sweet-faraday-hpygoj`
**Test suite:** `python -m pytest tests/` — 26 passing.

The build was paused deliberately partway. This file is the resume point.

---

## What is built and verified

| Component | File | State |
|---|---|---|
| Agent spec | `agents/creator-campaign-scout.md` | ✅ checked in; role section **amended** 2026-09-10, rest verbatim |
| Spec loader | `agent_spec.py` | ✅ parses campaign slot, hard rules, guards weight drift |
| Campaign config | `config.py` | ✅ weights locked, **instruments**, gates, readiness roles |
| Scoring engine | `scorer.py` | ✅ 5 dimensions, instrument-based D3, gates, readiness roles |
| **Real creator data** | `data/creators.json` | ✅ 20 sourced creators + 5 LinkedIn calibration cohort |
| Tests | `tests/` | ✅ 26 passing |

### The data is real now

`data/sample_creators.csv` **has been deleted.** Every metric in it was an invented
placeholder attached to a real named person, and several were materially wrong (it had
Mikey No Code below the engagement floor at 3.2%; his actual view rate is 20.76%).

`data/creators.json` is sourced from the product owner's Google Sheet
("Creator Sheet for Craftly", exported 2026-09-10). Every row carries `source`,
`sourced_from` and `sourced_date`.

**Three rows are flagged `rate_reproducible: false`** — Joshua La Rosa, Kyle Balmer and
Robo Nuggets. The sheet stores one blended cross-platform follower count but computed the
rate against a single platform's followers, so the recorded rate cannot be reproduced
from the recorded columns. The rate is real; the audit trail is not. Fixing this needs
**per-platform follower counts**, which the schema should carry.

### The scoring model was corroborated, not just asserted

All **20/20** hand-scored weighted totals in the sheet reconcile exactly against the
locked weights (.30/.25/.25/.10/.10). The weights are no longer locked by fiat alone —
an independently produced human set agrees with them to three decimals.

### Current output on the real set

```
Joshua La Rosa        Credibility    98.0  Keep
soojintech            Credibility    91.0  Keep
Riley Brown           Conversion     88.0  Keep
Robo Nuggets          Conversion     87.0  Keep
Parker Prompts        Credibility    86.0  Keep
askcatgpt             Credibility    84.0  Keep
Mikey No Code         Conversion     81.0  Keep
Andrew Kim            Awareness      79.0  Keep
genzbestie            Awareness      79.0  Keep
Harper Carroll        Credibility    79.0  Keep
Chams Eldin           Credibility    77.5  Keep
Kyle Balmer           Credibility    77.0  Keep
Roberto Nickson       Credibility    73.0  Keep
Maitri Mangal         Credibility    73.0  Keep
The Tech Girl         Conversion     70.0  Keep
Mia Yilin             Awareness      64.0  Keep
isabellagerli         Awareness      60.0  Keep
Andy Stapleton        -                 -  NEEDS_REVIEW - category readiness not judged
Lara Acosta           -                 -  NEEDS_REFRESH - Missing: followers, resonance_rate
Dara Denney           -                 -  NEEDS_REFRESH - Missing: followers, resonance_rate
Daniel Priestley      -                 -  NEEDS_REFRESH - Missing: followers, resonance_rate
Milly Tamati          -                 -  NEEDS_REFRESH - Missing: followers, resonance_rate
Richard Foster-Fletc  -                 -  NEEDS_REFRESH - Missing: followers, resonance_rate
No-Code Exits         -                 -  Drop - cannot produce the deliverable (long_vid
sofieestudies         -                 -  Drop - View rate 28.1% on Instagram -> 3/5; com
```

Composition: Awareness 4 (target 5-7), Credibility 9 (target 2-4), Conversion 4 (target
5-7). **Credibility is over target** — most of this pool's audiences have category
exposure without adoption. That is a real finding about the pool, not a bug.

### What the engine caught that the sheet did not

- **No-Code Exits** was scored 3.0 and ranked. It is a newsletter, and the brief asks for
  2 original videos. It is now dropped by the **deliverable gate** before scoring.
- **sofieestudies** scored 4.05 with a written note that it might be a fake account. Now
  dropped by the **authenticity gate**, which beats the score.
- **No-Code Exits** was also given 5/5 on engagement with `N/A` view data.
- **D3 saturation.** The sheet's TikTok/IG ladder (8%+ = 5) is calibrated for engagement
  rate but was fed view rate, so 14 of 20 creators scored exactly 5.0 on a dimension
  worth 25% of the total. Under the provisional bands, 4 creators move by 0.5+ weighted
  points — Harper Carroll drops from 4.70 to 3.95 and is no longer top of the list.

## What is NOT built

| Component | File | Notes for whoever picks this up |
|---|---|---|
| Flask API | `app.py` | Routes needed: `GET /` (Screen 1), `POST /shortlist` (Screen 2), `POST /api/score`, `POST /export.csv`, `GET+POST /api/schedule`, `POST /api/schedule/run`. `scorer.build_shortlist(brief, csv)` already returns everything the templates need — see its return dict. |
| Screen 1 — brief input | `templates/index.html` | Fields per brief: brand, product, goal (awareness/conversion/UGC), audience, platform checkboxes, CPM (default 50), follower band dropdown, shortlist slider 15-20, exclusions, submit. |
| Screen 2 — shortlist | `templates/results.html` | Locked-criteria summary (`result["criteria"]`), scored table (`result["table"]`), composition panel (`result["composition"]`), Export CSV button. Role colours: Awareness=blue, Credibility=green, Conversion=orange — already on each row as `role_colour`. |
| Stylesheet | `static/styles.css` | Plain CSS, no framework. |
| Schedule console | `templates/schedule.html` | Cadence daily/weekly/biweekly, last run, next run, Run Now. |
| Scheduler | `scheduler.py` | `schedule` lib, default Mon 09:00, reads `data/pipeline_intel.json`, writes `reports/soft_roster_YYYY-MM-DD.csv`, logs to `logs/scheduler.log`. Config constants already exist in `config.py`. |
| Enrichment stub | `enricher.py` | `enrich_creator(handle, platform) -> dict`, inert while `ENRICHMENT_ENABLED=False`, returns input unchanged with `source='manual'`, flags `UNVERIFIED` on API fallback. **`scorer.build_shortlist()` already calls `enricher.apply_enrichment()` when the toggle is on** — that import will fail until this file exists, so build it before flipping the toggle. |
| Sample pipeline intel | `data/pipeline_intel.json` | Upcoming brand brief categories for the scheduler loop. |
| README | `README.md` | Not written. `CLAUDE.md` currently carries the run instructions. |

### Verification still owed

From the original brief, these could not be checked because the app does not exist yet:

1. `python app.py` starts without errors — **not verified**
2. `localhost:5000` renders Screen 1 with all fields — **not verified**
3. Form submit renders Screen 2 with a scored table — **not verified**
4. Weighted scores correct for 3+ creators — **verified** (above, via pytest)
5. Export to CSV downloads a valid file — **partially**: `scorer.to_csv()` is tested for
   header and row count; the browser download path is not built
6. `/schedule` returns valid JSON — **not verified**

---

## Constraints that must survive the rest of the build

Read `CLAUDE.md` in full, but these three break the product if violated:

1. **Never fabricate creator metrics — or judgement.** Missing metric → `NEEDS_REFRESH`.
   Missing human judgement → `NEEDS_REVIEW`. Uncalibrated instrument → `NEEDS_CALIBRATION`.
   The engine returns a gap, never a guess. `data/creators.json` is now genuinely sourced,
   but three rows carry `rate_reproducible: false` and any UI showing them should say so.
2. **Do not modify the scoring weights** (.30/.25/.25/.10/.10). `test_weights_are_locked`
   and `check_weights_documented()` both guard this.
3. **Campaign role comes from Category Readiness, not the total score.** Role and tier
   are independent dimensions. The D1/D2 rule it replaced mislabelled 7 of 18 creators.

## Open questions for the product owner

- The sample metrics are invented placeholders. Before this is shown to a real Creator
  Partnership Manager, either wire the enrichment API or replace the CSV with sourced
  numbers — otherwise the app's own top constraint is being violated by its demo data.
- Spec vs. brief disagree on role thresholds (3.67/3.6 vs 4.0/4.0). The brief won. If
  the spec is authoritative, `config.ROLE_THRESHOLD` is the single value to change.
- The D1 30-vs-25 point discrepancy in the spec looks like a typo worth correcting at
  the source, which would let `score_audience_match()` drop its normalisation.
