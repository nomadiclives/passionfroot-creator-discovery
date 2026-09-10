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

### The engine reproduces the hand-scored sheet

**16 of 17 scored creators match the sheet's weighted score exactly** (`test_engine_
reproduces_the_hand_scored_sheet`). The app agrees with expert judgement and adds gates
on top — it does not quietly re-rank.

The one divergence is **Roberto Nickson**, and it is the sheet's slip, not the engine's:
his 24.66% view rate scores 5/5 under the sheet's own ladder (anything above 8%), but the
sheet records 4. The engine applies the stated rule, giving 4.15 rather than 3.90.
Recorded in `test_roberto_nickson_is_the_one_sheet_row_that_breaks_its_own_ladder`.

### What the engine catches that the sheet did not

- **No-Code Exits** was scored 3.0 and ranked. It is a newsletter and the brief asks for
  2 original videos — now dropped by the **deliverable gate** before scoring. It was also
  given 5/5 on engagement with `N/A` view data.
- **sofieestudies** scored 4.05 alongside a written note that it might be a fake account.
  Now dropped by the **authenticity gate**, which beats the score.

### ⚠️ D3 is a known limitation — do not "fix" it without per-platform followers

The TikTok/Instagram ladder (`8% = 5`) is an **engagement-rate** ladder being fed
**view-rate** data, so **14 of 20 creators score 5/5** and a quarter of the total weight
does little discriminating work. `test_d3_saturation_is_a_known_limitation_not_a_surprise`
pins this so it cannot be forgotten.

**A refit was attempted and reverted.** The blocker is that the sheet's rates use
**inconsistent denominators**:

| | Rows | Denominator |
|---|---|---|
| Blended | 8 | one platform's views ÷ followers summed across **all** platforms |
| Single | 11 | one platform's views ÷ **that platform's** followers |

Harper Carroll's 14.8% divides one platform's views by three platforms' followers, so it
is structurally understated. Refitting demoted her from 1st to 10th on that artifact.
The rates are not comparable to each other and must not be ranked against fitted bands.

**The fix is per-platform follower counts**, not new bands. Once the schema carries them,
refit and delete the saturation test.

## What is NOT built

| Component | File | Notes for whoever picks this up |
|---|---|---|
| Flask API | `app.py` | `GET /` -> Screen 1. `POST /shortlist` -> Screen 2. `POST /export.csv` -> `scorer.to_csv(result)`. Build the brief dict from the form, pass to `scorer.build_shortlist(brief, config.CREATOR_DATA)`. |
| Screen 1 — brief input | `templates/index.html` | Fields: brand, product, **category** (drives readiness), goal, audience, platform checkboxes (tiktok/instagram/youtube/**linkedin**), CPM (default 50), follower band, shortlist size 15-20, exclusions. |
| Screen 2 — shortlist | `templates/results.html` | `result["criteria"]` locked-criteria panel; `result["table"]` scored rows; `result["composition"]` role panel; Export CSV. Each row has `role_colour` (Awareness=blue, Credibility=green, Conversion=orange). **Render all five statuses** — Keep / Drop / NEEDS_REFRESH / NEEDS_REVIEW / NEEDS_CALIBRATION — with `status_reason` visible; a creator must never disappear. Show `sourced_from` + `sourced_date`, and flag `rate_reproducible: false` rows. |
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
