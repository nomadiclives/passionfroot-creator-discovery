# Creator Campaign Scout Agent

Give it a campaign brief; it returns a scored, role-assigned creator shortlist you can
take to outreach — with its gaps labelled rather than filled in.

It implements the `creator-campaign-scout` skill (Steps 1, 4, 5, 5a, 6) as a small Flask
app. The skill itself is checked in at [`agents/creator-campaign-scout.md`](agents/creator-campaign-scout.md)
and loaded at runtime, so the app can show a Creator Partnership Manager the exact
rubric behind every number on screen.

## Quickstart

```bash
pip install -r requirements.txt
python app.py                 # then open http://localhost:5000
```

Debug is off by default; `FLASK_DEBUG=1 python app.py` turns on the reloader for local
work. Never set it on a deployed service — the Werkzeug debugger executes arbitrary code
from the browser.

To deploy, the repository root carries a Render blueprint — see
[Deploying](../README.md#deploying). In production the app is served by gunicorn against
the `app` object; the `__main__` block is local-only. There is **no authentication**, so
anyone with the URL sees the full shortlist.

A usage walkthrough — scoring a brief, reading Screen 2, adding a creator, scoring a new
category — is in the [repository README](../README.md#how-to-use-it). This file is the
reference.

| Command | What it does |
|---|---|
| `python app.py` | Serves both screens and the schedule console |
| `python -m pytest tests/` | The test suite — 89 tests |
| `python scheduler.py --once` | One discovery pass now, then exit |
| `python scheduler.py` | The blocking loop (default Monday 09:00) |
| `python scheduler.py --status` | Print schedule state as JSON |

## The two screens

**Screen 1 — the brief.** Brand, product, category, goal, audience, platforms, CPM,
follower band, shortlist size, exclusions. Category is the field that does the most
work: campaign role is assigned from the audience's readiness *for that category*.

**Screen 2 — the shortlist.** The locked criteria set, a campaign-composition panel, and
every creator that was evaluated — including the ones the engine refused to score, each
with its reason. Export CSV re-runs the same brief through the same engine, so the file
and the screen cannot disagree.

## Routes

| Route | Method | Returns |
|---|---|---|
| `/` | GET | Screen 1 — the brief form |
| `/shortlist` | GET, POST | Screen 2 — the scored shortlist |
| `/export.csv` | GET, POST | The shortlist as a CSV download |
| `/api/shortlist` | GET | The same result as JSON |
| `/schedule` | GET | The schedule console (JSON on `?format=json` or an `Accept: application/json` header) |
| `/api/schedule` | GET | Schedule state as JSON, always |
| `/schedule/run` | POST | Runs one discovery pass now |
| `/schedule/cadence` | POST | Sets daily / weekly / biweekly |
| `/healthz` | GET | Liveness, plus whether config and spec still agree on the weights |

## The scoring model

Five dimensions, each scored 1–5, combined under weights fixed by the spec:

```
score = audience_match      * 0.30      D1  who the audience is
      + content_match       * 0.25      D2  what the creator makes
      + engagement_score    * 0.25      D3  does that audience show up
      + geo_score           * 0.10      D4  strength of US confirmation
      + commercial_maturity * 0.10      D5  can they run a paid brief
```

`score_100 == weighted_score * 20` exactly, and tiers read off it (Tier 1 ≥ 75,
Tier 2 ≥ 55, Tier 3 ≥ 35). The weights are locked in two directions: a test pins the
values, and `agent_spec.check_weights_documented()` fails the suite if `config.py` and
the spec drift apart. `/healthz` reports that agreement at runtime.

The model is not asserted, it is corroborated: all 20 hand-scored weighted totals in the
product owner's sheet reconcile against these weights to three decimals, and the engine
reproduces **16 of 17** scored rows exactly. The one divergence is the sheet applying its
own ladder inconsistently, pinned in a test rather than papered over.

## What it refuses to do

The point of the app is the refusals. Four of the five statuses a creator can carry are
the engine declining to produce a number it does not have:

| Status | Meaning |
|---|---|
| `Keep` | Scored and shortlisted |
| `Drop` | Failed a gate or an exclusion — the reason is named |
| `NEEDS_REFRESH` | A required metric is missing. Never estimated |
| `NEEDS_REVIEW` | A human judgement is missing, or was made about a different category |
| `NEEDS_CALIBRATION` | The platform's instrument has no fitted bands yet |

Every one of them is rendered on Screen 2 with its reason. A creator never silently
disappears — a row that vanishes is indistinguishable from a creator nobody sourced.

When a refusal empties the roster entirely, Screen 2 says so at the top rather than
leaving a blank panel: how many creators were held back, why, and what to do about it.

**Gates run before scoring and beat it.** A newsletter is not a weak candidate for a
video brief, it is not a candidate; a high engagement rate on suspected fake comments is
worse than a low one on real comments.

**Role is not rank.** Campaign role comes from Category Readiness — the audience's
relationship to the product category — not from the total score or the sub-scores. A
Tier 1 creator can be an Awareness candidate. Readiness is a human judgement recorded
against a *named* category, and it does not transfer: run a brief in another category
and those rows come back `NEEDS_REVIEW` rather than carrying a role across.

## Supplying the judgement

Four of the five dimensions and the readiness call are human judgements, so a freshly
sourced list scores as `NEEDS_REVIEW` on every row. `/judge` is where you supply them:
the four sub-scores and readiness per creator, saved against the pool and re-scored.

The boundary the screen holds is exact, and it is the project's central rule restated:

> **Judgement can be typed. A metric must be sourced.**

So the form offers the four sub-scores and readiness, and offers *no* input for
followers, resonance rate or any other metric. A row missing a metric is **locked** with
its reason rather than presented as something you could judge your way out of — judging
cannot rescue a `NEEDS_REFRESH` row, and pretending otherwise would invite exactly the
invention the engine exists to prevent.

Three further properties, each pinned by a test:

- **A judgement is recorded against the category it was made for.** Saving readiness also
  writes `readiness_category` from the brief, so an in-app judgement is bound by the same
  non-transfer rule as a sourced one.
- **The checked-in creator data is never edited.** Judging the bundled pool forks it into
  a temporary working copy. `data/creators.json` carries `source`, `sourced_from` and
  `sourced_date` — provenance a browser form cannot honestly supply — and is read-only in
  practice on a deployed host anyway. To record a judgement permanently, edit the row.
- **A judgement typed in the app is distinguishable from a sourced one.** Rows gain
  `judged_in_app` and `judged_date`.

Out-of-range input is **refused, not clamped** — clamping turns a typo into a judgement
nobody made — and a refused save writes nothing at all rather than leaving the pool half
updated. The working copy is temporary (see `UPLOAD_RETENTION_HOURS`), so export the
shortlist to keep a result.

## Data

`data/creators.json` holds 20 creators sourced from the product owner's sheet plus a
5-creator LinkedIn cohort with no metrics yet. Every row records `source`,
`sourced_from` and `sourced_date`, and three rows are marked
`rate_reproducible: false` — the rate is real, but it cannot be recomputed from the
recorded columns, and the UI says so on the row.

Enrichment (`enricher.py`) is wired but inert: `config.ENRICHMENT_ENABLED` is `False`
and there is no key. Turned on, it fills *gaps only* — it never overwrites an audited
value, and a failed call flags the row `UNVERIFIED` rather than substituting a plausible
number.

## The scheduler

`scheduler.py` reads `data/pipeline_intel.json`, runs each upcoming campaign through the
same engine the UI uses, and writes `reports/soft_roster_YYYY-MM-DD.csv`, logging to
`logs/scheduler.log`. A scheduled roster and a hand-built one are the same artifact — a
test asserts it row for row.

The checked-in pipeline carries live campaigns only. Add a brief as a campaign block —
`id`, `brand_name` and `category` are required, everything else falls back to the
campaign slot in `config.DEFAULT_BRIEF`.

**Adding a brief in a new category is not a one-line change.** Role comes from Category
Readiness, and a readiness judgement is evidence about one named category, so a brief
outside `AI app-building tools` returns the pool as `NEEDS_REVIEW` until someone judges
it against the new category (`readiness` + `readiness_category` per row). That is the
guard working, not an empty result. A brief in the *same* category — different brand,
audience, platform mix or budget — scores immediately.

Test briefs that exercise the guard live in `tests/fixtures/pipeline_intel.json`, not in
the operator's pipeline file.

## Known limitation — D3 saturates

Dimension 3's TikTok/Instagram ladder is an *engagement-rate* ladder being fed
*view-rate* data, so 14 of 20 creators score 5/5 and a quarter of the total weight does
little discriminating work. A refit was attempted and reverted: the sheet's rates use
inconsistent denominators (8 rows divide one platform's views by followers summed across
all platforms), so they cannot be ranked against fitted bands.

The fix is per-platform follower counts, not new bands. Until the schema carries them,
`test_d3_saturation_is_a_known_limitation_not_a_surprise` keeps the weakness visible.
See [`HANDOVER.md`](HANDOVER.md).

## Discovery — the front half

`/discover` builds a click-through **query plan** from the brief: ~100 real searches
across the spec's passes, on every briefed platform. You run the ones worth running and
paste handles or profile URLs back; they become candidates in the same pool an upload
produces, and flow on to judging and scoring.

It needs no key and costs nothing, because it does not call anything. The spec says
Step 2 "produces a query plan and candidate pool, not verified metrics" — on TikTok and
Instagram that is simply true, so the app builds the searches and a person runs them.

**A pasted handle is a lead, not a measurement.** Collected rows arrive `NEEDS_REFRESH`
until real metrics are attached. The app will not fill them in.

`sources/youtube.py` adds real search and measured metrics on the free YouTube Data API
— built and tested, but it needs `YOUTUBE_API_KEY` set and **has never made a real
call**. See `HANDOVER.md`.

[`DISCOVERY_PLAN.md`](DISCOVERY_PLAN.md) scopes the rest: a tiered source inventory from
free to paid, where discovery plugs into the existing engine, a four-phase build order
with a genuinely useful **$0 tier**, and what stays manual permanently. The headline
finding is that the free/paid line falls exactly on audience demographics — D1 and D4,
40% of the score — which no free API exposes.

## Layout

```
app.py           Flask routes + server-rendered UI
creator_pool.py  uploaded-pool parsing, parking, and the judging write-back
scorer.py        the scoring engine — Steps 1, 4, 5, 5a, 6
config.py        campaign defaults, locked weights, instruments, gates, toggles
agent_spec.py    loads the checked-in skill spec and guards weight drift
enricher.py      Favikon / Modash enrichment stub, off by default
scheduler.py     soft-roster discovery loop
agents/          the skill spec — the spec of record
templates/       index.html, results.html, judge.html, schedule.html, base.html
static/          styles.css
data/            creators.json, pipeline_intel.json
reports/         soft_roster_YYYY-MM-DD.csv (generated)
logs/            scheduler.log (generated)
tests/           201 tests
../render.yaml   Render blueprint (repo root)
```

Contributor rules — the constraints that break the product if violated — are in
[`CLAUDE.md`](CLAUDE.md). Read it before changing `scorer.py` or `config.py`.
