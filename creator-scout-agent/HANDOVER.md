# Handover — Creator Campaign Scout Agent

**Point reached:** scoring engine complete and verified; web app not started.
**Branch:** `claude/sweet-faraday-hpygoj`
**Test suite:** `python -m pytest tests/` — 20 passing.

The build was paused deliberately partway. This file is the resume point.

---

## What is built and verified

| Component | File | State |
|---|---|---|
| Agent spec (verbatim skill) | `agents/creator-campaign-scout.md` | ✅ checked in, byte-identical to source |
| Spec loader | `agent_spec.py` | ✅ parses campaign slot, hard rules, guards weight drift |
| Campaign config | `config.py` | ✅ weights locked, floors, CPM model, enrichment toggles |
| Scoring engine | `scorer.py` | ✅ 5-dimension formula, D1/D2 roles, NEEDS_REFRESH, CPM, CSV export |
| Sample data | `data/sample_creators.csv` | ✅ 10 Craftly creators, all `source=manual` |
| Tests | `tests/` | ✅ 20 passing |
| Project docs | `CLAUDE.md` | ✅ constraints, commands, known deviations |

### Verified behaviour on the sample set

Run `python -m pytest tests/ -q` to confirm. Scoring the 10 sample creators against the
default Craftly brief produces:

```
CREATOR           ROLE           D1   D2   D3   D4   D5   WTD    /100  STATUS
Harper Carroll    Credibility  5.00 5.00 3.80 5.00 5.00  4.70   94.0  Keep     Tier 1
askcatgpt         Credibility  5.00 5.00 5.00 3.50 3.00  4.65   93.0  Keep     Tier 1
soojintech        Awareness    5.00 3.80 3.80 5.00 5.00  4.40   88.0  Keep     Tier 1
Joshua La Rosa    Awareness    5.00 3.20 5.00 5.00 3.00  4.35   87.0  Keep     Tier 1
Riley Brown       Conversion   3.00 5.00 3.80 5.00 5.00  4.10   82.0  Keep     Tier 1
Parker Prompts    Conversion   3.40 5.00 3.80 2.00 5.00  3.92   78.4  Keep     Tier 1
Andrew Kim        Conversion   2.00 5.00 3.80 3.50 5.00  3.65   73.0  Keep     Tier 2
Mia Yilin         Awareness    2.60 1.80 2.60 1.00 5.00  2.48   49.6  Keep     Tier 3
Robo Nuggets      —               —    —    —    —    —     —       —  NEEDS_REFRESH
Mikey No Code     Conversion   0.60 5.00 0.00 1.00 3.00  1.83   36.6  Drop
```

Three checked by hand against the formula:
- Harper Carroll: `(5.00×.30)+(5.00×.25)+(3.80×.25)+(5.00×.10)+(5.00×.10) = 4.700` ✓
- askcatgpt: `(5.00×.30)+(5.00×.25)+(5.00×.25)+(3.50×.10)+(3.00×.10) = 4.650` ✓
- Riley Brown: `(3.00×.30)+(5.00×.25)+(3.80×.25)+(5.00×.10)+(5.00×.10) = 4.100` ✓

Three engine behaviours the sample set is designed to exercise:
- **Robo Nuggets** has no `avg_views` → `NEEDS_REFRESH`, no score invented, excluded
  from the ranked shortlist but still visible in the table.
- **Mikey No Code** scores a perfect 5.00 on Content Match and is still dropped — 3.2%
  engagement is under the 3.5% TikTok floor. The gate is not a tiebreaker.
- **Role is independent of rank.** soojintech is 3rd overall and Awareness; Andrew Kim
  is Tier 2 and Conversion. Role reads D1/D2 only.

---

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

1. **Never fabricate creator metrics.** Missing data → `NEEDS_REFRESH`, never a guess.
   Note that every metric in `data/sample_creators.csv` is a *placeholder* carrying
   `source=manual` — none of it is verified against a real platform or API. Any UI that
   displays it should say so.
2. **Do not modify the scoring weights** (.30/.25/.25/.10/.10). `test_weights_are_locked`
   and `check_weights_documented()` both guard this.
3. **Campaign role comes from the D1/D2 relationship, not the total score.** Role and
   tier are independent dimensions.

## Open questions for the product owner

- The sample metrics are invented placeholders. Before this is shown to a real Creator
  Partnership Manager, either wire the enrichment API or replace the CSV with sourced
  numbers — otherwise the app's own top constraint is being violated by its demo data.
- Spec vs. brief disagree on role thresholds (3.67/3.6 vs 4.0/4.0). The brief won. If
  the spec is authoritative, `config.ROLE_THRESHOLD` is the single value to change.
- The D1 30-vs-25 point discrepancy in the spec looks like a typo worth correcting at
  the source, which would let `score_audience_match()` drop its normalisation.
