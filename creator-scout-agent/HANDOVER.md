# Handover — Creator Campaign Scout Agent

**Status: handed over 2026-09-10.** Feature-complete, merged to `main`, and **deployed
on Render** from `render.yaml` — engine, web app, scheduler and enrichment stub all built
and exercised in a real browser.
**Test suite:** `python -m pytest tests/` — 89 passing.

The build was paused deliberately partway and has since been finished. Nothing in this
file is a blocker on running the app. What remains is listed under **Still open**; the
one item that gates real improvement rather than polish is **per-platform follower
counts**, which is a data-sourcing task, not a code task.

**Read this before the first real brief:** a brief in a category the pool was not judged
against returns an empty roster on purpose. See *Readiness is category-relative* below —
it is the single most likely thing to be mistaken for a bug.

---

## What is built and verified

| Component | File | State |
|---|---|---|
| Agent spec | `agents/creator-campaign-scout.md` | ✅ checked in; role section **amended** 2026-09-10, rest verbatim |
| Spec loader | `agent_spec.py` | ✅ parses campaign slot, hard rules, guards weight drift |
| Campaign config | `config.py` | ✅ weights locked, **instruments**, gates, readiness roles |
| Scoring engine | `scorer.py` | ✅ 5 dimensions, instrument-based D3, gates, readiness roles |
| **Real creator data** | `data/creators.json` | ✅ 20 sourced creators + 5 LinkedIn calibration cohort |
| Flask API + UI | `app.py` | ✅ both screens, CSV export, schedule console, JSON surfaces |
| Screen 1 — brief | `templates/index.html` | ✅ every field; verified in a real browser |
| Screen 2 — shortlist | `templates/results.html` | ✅ all 25 rows, all five statuses, provenance |
| Schedule console | `templates/schedule.html` | ✅ cadence, last/next run, Run Now, pipeline |
| Stylesheet | `static/styles.css` | ✅ plain CSS, no framework |
| Scheduler | `scheduler.py` | ✅ `--once` and blocking loop; writes dated soft rosters |
| Enrichment stub | `enricher.py` | ✅ inert by default; gaps-only merge; UNVERIFIED on failure |
| Pipeline intel | `data/pipeline_intel.json` | ✅ live campaigns only; test briefs live in `tests/fixtures/` |
| Empty-roster explanation | `templates/results.html` | ✅ Screen 2 leads with why a roster is empty, not just per-row |
| READMEs | `README.md`, `../README.md` | ✅ project and repo root, with a usage walkthrough |
| Deployment | `../render.yaml` | ✅ Render blueprint; gunicorn, `/healthz` check, debug off |
| Tests | `tests/` | ✅ 89 passing |

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

## Readiness is category-relative — added while wiring the scheduler

The scheduler runs several campaign categories against one creator pool, which exposed a
hole: every `readiness` value in `data/creators.json` was judged against **Craftly's**
category, and role comes from readiness. Reusing those judgements for a campaign in
another category would have produced confident roles from evidence about something else
— inventing judgement, which is the same rule as never inventing a metric.

Rows now carry `readiness_category`, and `score_creator()` returns `NEEDS_REVIEW` when it
does not match `brief["category"]`. Absence of the tag is not a mismatch: an untagged row
still scores, so the guard fires only on a **known** mismatch.

The visible effect, from `tests/fixtures/pipeline_intel.json`: a brief in another
category shortlists **0 of 25** and reports 18 rows for re-judgement. That is the guard
working, not a broken run — and it is the first thing to explain to anyone who adds a
brief outside `AI app-building tools` and sees an empty roster.

## What the UI is for

The screens exist to make the engine's refusals legible. All 25 evaluated creators render
on Screen 2 — Keep, Drop, NEEDS_REFRESH, NEEDS_REVIEW, NEEDS_CALIBRATION — each with its
reason, its provenance (`sourced_from`, `sourced_date`) and, where it applies, the
`rate not reproducible` flag. A row that disappears is indistinguishable from a creator
nobody sourced, so nothing is filtered out of the table.

CSV export re-runs the same brief through the same engine rather than serialising a
cached result, so the file and the screen cannot drift apart. A test asserts the row
counts match.

**An empty roster explains itself.** The engine's most defensible refusal was also its
most bug-looking output: a brief in an unjudged category returned zero shortlisted, and
the only explanation sat per-row in a greyed table below an empty composition panel.
Screen 2 now leads with it — how many creators are held back, which category they were
judged against, which one the brief scores against, and the two fields to set to score
the new one. A second, separate banner covers emptiness from any other cause (a
LinkedIn-only brief drops the whole pool on the platform check), so an unrelated empty
result is never blamed on the readiness guard. `build_shortlist()` returns
`readiness_mismatch` and `judged_categories` for this, so the UI reads a flag rather
than parsing a reason string.

### Verification — all six checks now pass

From the original brief, verified by driving the real app in Chromium (not only the
Flask test client, which proves routes answer but not that pages render):

1. `python app.py` starts without errors — **verified**
2. `localhost:5000` renders Screen 1 with all fields — **verified**, 13 inputs present
3. Form submit renders Screen 2 with a scored table — **verified**, 25 rows, 17 shortlisted
4. Weighted scores correct for 3+ creators — **verified** via pytest, and 16/17 reproduce
   the hand-scored sheet exactly
5. Export to CSV downloads a valid file — **verified**, `attachment` header, 26 lines
   (1 header + 25 rows)
6. `/schedule` returns valid JSON — **verified** on `/api/schedule`, `?format=json` and
   an `Accept: application/json` header; the same route serves HTML to a browser

The only console error in the browser run was a 404 for `/favicon.ico`. No JS errors —
there is no JavaScript.

## Deployment

Live on Render's free tier, built from `render.yaml` at the repository root. Render
installs from `creator-scout-agent/`, serves the app under
`gunicorn app:app --bind 0.0.0.0:$PORT --workers 2`, and health-checks `/healthz`.
Pushes to the default branch redeploy automatically.

Verified locally under that exact gunicorn command — both screens, static assets, CSV
export, the schedule console and Run Now behave identically to the development server.
Three tests pin the deploy surface so it cannot rot silently: the gunicorn entry point
resolves, debug is off unless `FLASK_DEBUG` asks for it, and the blueprint's start
command, root directory and health check still match the code.

**`debug=True` was removed as a default.** Harmless on loopback, a remote shell on a
public URL — the Werkzeug debugger executes arbitrary code from the browser. Never set
`FLASK_DEBUG` on a deployed service.

What the free tier does, all of it expected rather than broken:

| Behaviour | Consequence |
|---|---|
| Sleeps after ~15 min idle | First request takes ~50s to wake. Open the link yourself before sharing it. |
| No background worker | The scheduler's blocking loop never fires. **Run Now** works and writes a roster. |
| Ephemeral filesystem | Generated rosters, logs and schedule state reset on every deploy. Creator data is read from the repo, so it always survives. |
| No authentication | Anyone with the URL sees the full shortlist, notes included. |

The last row is a deliberate trade for a demo, not an oversight. Before this is used in
anger it needs auth, and the repository — which carries the sourced creator data — should
be private.

---

## Still open

Nothing here blocks running the app, and the app is deployed.

| Item | Why it is still open |
|---|---|
| **Per-platform follower counts** | The real fix for D3 saturation, and for the three `rate_reproducible: false` rows. Needs a schema change plus re-sourcing, not a code change. See the D3 section above. |
| **LinkedIn calibration** | `config.INSTRUMENTS["linkedin"]["bands"]` is `None`, so LinkedIn returns `NEEDS_CALIBRATION`. The 5-creator cohort in `data/creators.json` has no metrics yet — collect interaction rates for it, fit bands, then delete the uncalibrated branch. |
| **Live enrichment** | `enricher.py` is wired and tested against a patched transport, but has never made a real call. Set `ENRICHMENT_ENABLED`, `API_PROVIDER` and `API_KEY`, then check the provider's real payload shape against `FIELD_MAP`. Never commit a key. |
| **Judging the pool for a second category** | `data/pipeline_intel.json` holds live campaigns only, and every readiness judgement in `data/creators.json` is against `AI app-building tools`. A brief in any other category needs the pool judged against it (`readiness` + `readiness_category` per row) before it can score. |
| **Scheduler under a real clock** | `--once` and the next-run arithmetic are tested; the blocking loop has not been left running across an actual scheduled fire. On Render's free tier it never will — that needs a background worker or a cron job on a paid plan. |
| **Authentication** | There is none. Anyone with the deployed URL sees the full shortlist, including the commercial notes on named creators. Fine for a demo, not for real use. |
| **End-to-end check of the live deploy** | The build and the gunicorn command are verified locally; the deployed URL itself has not been walked through screen by screen. |
| **Spec role thresholds** | The spec cuts roles at 3.67/3.6, the brief at 4.0. Moot for role assignment now that readiness drives it (`config.ROLE_THRESHOLD` is unused), but the spec still says something the code does not do. Worth correcting at the source. |

---

## Constraints that must survive any further work

Read `CLAUDE.md` in full, but these break the product if violated:

1. **Never fabricate creator metrics — or judgement.** Missing metric → `NEEDS_REFRESH`.
   Missing human judgement → `NEEDS_REVIEW`. Uncalibrated instrument → `NEEDS_CALIBRATION`.
   The engine returns a gap, never a guess. `data/creators.json` is now genuinely sourced,
   but three rows carry `rate_reproducible: false` and any UI showing them should say so.
2. **Do not modify the scoring weights** (.30/.25/.25/.10/.10). `test_weights_are_locked`
   and `check_weights_documented()` both guard this.
3. **Campaign role comes from Category Readiness, not the total score.** Role and tier
   are independent dimensions. The D1/D2 rule it replaced mislabelled 7 of 18 creators.
4. **A readiness judgement is evidence about one named category only.** Do not let it
   transfer to another brief — `readiness_category` exists to stop exactly that.
5. **Every evaluated creator stays on screen.** Filtering unscored rows out of the table
   would hide the gaps the engine exists to report.

## Open questions for the product owner

- **Per-platform follower counts.** The single blocker on a real D3 refit, and on the
  three `rate_reproducible: false` rows. Can the sheet carry a follower count per
  platform rather than one blended number?
- **Which categories the roster should cover.** Readiness is judged per category, so a
  second live campaign in a different category needs its own pass over the pool. Worth
  knowing which categories are coming before that judging work is scheduled.
- Spec vs. brief disagree on role thresholds (3.67/3.6 vs 4.0/4.0). The brief won. If
  the spec is authoritative, `config.ROLE_THRESHOLD` is the single value to change.
- The D1 30-vs-25 point discrepancy in the spec looks like a typo worth correcting at
  the source, which would let `score_audience_match()` drop its normalisation.
