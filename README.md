# passionfroot-creator-discovery

A scoring engine for creator shortlists — it ranks and role-assigns creators you've already sourced. It does not find them. Give it a campaign
brief; it returns a scored, role-assigned creator shortlist ready for outreach — with its
gaps labelled rather than filled in.

Phase 2 includes discovery too, but this requires API access to paid tools.

The working project lives in **[`creator-scout-agent/`](creator-scout-agent/)**.

```bash
cd creator-scout-agent
pip install -r requirements.txt
python app.py                 # then open http://localhost:5000
```

**Live:** https://creator-campaign-scout.onrender.com/

A free-tier service sleeps after ~15 minutes idle, so the first request takes about 50
seconds to wake. See [Deploying](#deploying) for how it is built and what the free tier
does.

---

## How to use it

### Score a campaign brief

1. **Start it.** `python app.py`, then open <http://localhost:5000>.
2. **Fill in the brief** (Screen 1). It is pre-filled with the Craftly campaign, so you
   can change one field and go. The field that matters most is **Product category** —
   campaign role is assigned from how ready an audience is *for that category*, so
   changing it changes the roles, not just the heading.
3. **Build shortlist** → Screen 2.
4. **Export CSV** when you are happy with it. The export re-runs the same brief through
   the same engine, so the file always matches what you just read.

### Reading Screen 2

| Panel | What it tells you |
|---|---|
| **Count strip** | Five counts at a glance: shortlisted, needs review, needs refresh, needs calibration, dropped |
| **Locked criteria** | Exactly what the brief was interpreted as — check this first if the output surprises you |
| **Dimension 3 instruments** | Which resonance instrument each platform is scored on, and whether its bands are fitted |
| **Campaign composition** | Role counts against target, total reach, modelled budget |
| **Every creator evaluated** | Every row, scored or not, with its reason and its source |
| **Outreach angles** | A per-creator pitch angle, keyed to the assigned role |

Every creator carries a status. `Keep` and `Drop` are decisions the engine made; the
other three are refusals — *the engine declining to produce a number or a judgement it
did not have*:

| Status | What it means | What to do |
|---|---|---|
| `Keep` | Scored and shortlisted | Take it to outreach |
| `Drop` | Failed a gate or an exclusion | Read the reason; usually correct and final |
| `NEEDS_REFRESH` | A required metric is missing | Source the metric — never estimate it |
| `NEEDS_REVIEW` | A human judgement is missing, or was made about a different category | Judge it (see below) |
| `NEEDS_CALIBRATION` | That platform's scoring bands have not been fitted yet | Collect real rates for that platform and fit bands |

**An empty shortlist is usually not a bug.** The most common cause is a brief in a
category the creator pool was never judged against — Screen 2 says so at the top when it
happens, and names both categories.

### Score your own creator list

Screen 1 has a **Creator list** field: upload a CSV or JSON and the brief scores those
creators instead of the bundled sample. Leave it empty to score the bundled pool.
[Download the template CSV](http://localhost:5000/creator-template.csv) from the running
app for every column the engine reads.

An uploaded list without the four judged sub-scores and a `readiness` call scores as
`NEEDS_REVIEW` on every row — the engine will not invent judgement. Supply it on the
**judging screen** (next section) rather than hand-editing columns.

**What this tool does not do: find creators.** There is no search, no platform API. You
bring the list; it scores it. That half is now scoped in
[`DISCOVERY_PLAN.md`](creator-scout-agent/DISCOVERY_PLAN.md) — a tiered source inventory,
a four-phase build order with a working $0 tier, and an honest account of what stays
manual.

### Judge a list so it can be scored

Four of the five dimensions, and the readiness call that assigns campaign role, are
human judgements. A freshly sourced list therefore scores nothing until a person supplies
them. Screen 2 offers **Judge N creators** whenever rows need it, which opens a form with
the four sub-scores and readiness per creator, then re-scores the pool.

The rule the screen holds is the project's central one, restated:

> **Judgement can be typed. A metric must be sourced.**

So there is no input for followers or resonance rate anywhere on it, and a row missing a
metric is *locked* with its reason instead of being offered as something you could judge
your way out of. Judging cannot rescue a `NEEDS_REFRESH` row.

Three things worth knowing:

- Readiness is saved **against the brief's category**, so an in-app judgement does not
  transfer to a brief about something else — the same rule as a sourced one.
- Judging the bundled pool **forks it into a temporary working copy**; it never edits
  `data/creators.json`, which carries provenance a browser form cannot supply. To record
  a judgement permanently, edit the row (below).
- An out-of-range score is refused rather than clamped, and a refused save writes
  nothing — clamping would turn a typo into a judgement nobody made.

The working copy is temporary, so **export the shortlist** to keep a result.

### Add a creator to the bundled pool

Add a row to `creator-scout-agent/data/creators.json`. Required: `name`, `platform`,
`followers`, `resonance_rate`. Also record `source`, `sourced_from` and `sourced_date` —
provenance is shown in the UI, and a row without it cannot be audited later.

A creator will come back `NEEDS_REVIEW` until it also carries the four human-judged
sub-scores (`audience_match_score`, `content_match_score`, `geo_match_score`,
`commercial_maturity_score`, each 1–5) and a readiness call. That is deliberate: the
engine will not invent judgement any more than it will invent a metric.

### Score a new product category

Readiness is judged against one named category, so a brief outside
`AI app-building tools` will return the whole pool for re-judgement. The fastest way
through is the judging screen above, which writes both fields for you against the brief's
category. To record the judgement permanently instead, set both fields on each creator
row:

```json
"readiness": "exposed",
"readiness_category": "your new category"
```

`unexposed` → Awareness · `exposed` → Credibility · `adopted` → Conversion.

Everything else about a creator — metrics, sub-scores, gates — is unaffected, so this is
the only work a new category requires.

### Pre-build rosters on a schedule

Add upcoming briefs to `creator-scout-agent/data/pipeline_intel.json` (`id`,
`brand_name` and `category` are required; the rest falls back to the campaign defaults),
then:

```bash
cd creator-scout-agent
python scheduler.py --once      # one pass now, then exit
python scheduler.py             # blocking loop, default Monday 09:00
python scheduler.py --status    # print schedule state as JSON
python scheduler.py --cadence daily   # override the cadence for this run
```

Rosters land in `creator-scout-agent/reports/soft_roster_YYYY-MM-DD.csv`, and the
`/schedule` console shows cadence, last run, next run and a Run Now button.

## Deploying

Deployed on [Render](https://render.com) from the blueprint at
([`render.yaml`](render.yaml)) — no CLI, no local setup. To deploy it again from a fork:

1. Sign in at [render.com](https://render.com) with the GitHub account that owns the
   repository.
2. **New → Blueprint**, pick `passionfroot-creator-discovery`, and **Apply**.
3. Render reads `render.yaml`, installs the dependencies, starts the app under gunicorn,
   and gives you a public `https://<name>.onrender.com` URL. First build takes a few
   minutes; after that, pushes to the default branch redeploy automatically.

Render deploys the repository's **default branch** — check that it is the branch you
expect before wondering why a push did not appear.

Verified locally under the exact command Render runs
(`gunicorn app:app --bind 0.0.0.0:$PORT --workers 2`): both screens, the CSV export, the
schedule console and Run Now all behave identically to the development server.

### Four things to know about the free tier

- **It sleeps.** After ~15 minutes idle the service spins down, and the next request
  takes roughly 50 seconds to wake it. If you are sending the link to someone, open it
  yourself a minute beforehand.
- **Scheduled runs do not fire.** The web service serves requests; nothing runs the
  blocking scheduler loop. **Run Now** on `/schedule` works, and writes a roster. Actual
  cadence needs a background worker or a cron job, which the free plan does not include.
- **The filesystem is ephemeral.** Generated rosters, logs and schedule state reset on
  every deploy and restart. The creator data is read from the repository, so it always
  survives; anything the app writes does not.
- **There is no authentication.** Anyone with the URL sees the full shortlist, including
  the notes. `/healthz` is public too, though it exposes nothing beyond whether the spec
  and config still agree.

### Running it in debug

`FLASK_DEBUG=1 python app.py` enables the reloader locally. Debug is **off by default**
and must be asked for, because the Werkzeug debugger executes arbitrary code from the
browser — a debug default that survived to a public host would be a remote shell. Never
set `FLASK_DEBUG` on a deployed service.

Full documentation: [`creator-scout-agent/README.md`](creator-scout-agent/README.md).

## What it does

Five scored dimensions (audience, content, resonance, geography, commercial maturity),
combined under weights fixed by the skill spec, plus eligibility gates that run *before*
scoring and override it. Output is a ranked shortlist with a campaign role per creator,
a composition panel against target, CPM-modelled budget, and a CSV export.

It ships with a real campaign — **Craftly for Students** — and 20 creators sourced from
the product owner's sheet, plus a 5-creator LinkedIn cohort awaiting metrics.

## The idea it is built around

Most shortlisting tools optimise for looking complete. This one optimises for being
trustworthy, which means it is built to **refuse**:

- **It never invents a metric.** A missing number is reported as a gap (`NEEDS_REFRESH`),
  never estimated. Every metric carries its source and sourced date.
- **It never invents a judgement.** Dimensions a human must score, and the category
  readiness that assigns campaign role, come back `NEEDS_REVIEW` when absent — and a
  readiness judgement is evidence about *one named category*, so it does not transfer to
  a brief about something else.
- **It never invents a scale.** A platform whose resonance instrument has no fitted bands
  returns `NEEDS_CALIBRATION` rather than a guessed band. LinkedIn is uncalibrated today.
- **It never hides a refusal.** Every evaluated creator stays on screen with its reason.
  A row that disappears is indistinguishable from a creator nobody sourced.

The corollary is that an empty result can be the correct answer, and the app is built to
say so on screen instead of looking broken.

It also agrees with expert judgement rather than quietly re-ranking: the engine
reproduces **16 of 17** hand-scored rows from the product owner's sheet exactly, and adds
gates on top. The one divergence is the sheet applying its own ladder inconsistently,
pinned in a test rather than papered over.

## Repository layout

| Path | What it is |
|---|---|
| [`creator-scout-agent/`](creator-scout-agent/) | The app — engine, web UI, scheduler, tests |
| [`creator-scout-agent/agents/`](creator-scout-agent/agents/) | The skill spec of record, checked in and loaded at runtime |
| [`creator-scout-agent/HANDOVER.md`](creator-scout-agent/HANDOVER.md) | Build state, what is verified, what is still open |
| [`.claude/agents/`](.claude/agents/) | Subagents used to build this, vendored from [agency-agents](https://github.com/msitarzewski/agency-agents) (MIT) |
| [`CLAUDE.md`](CLAUDE.md) | Contributor rules — read before changing scoring |

⚠️ Note the naming collision: `.claude/agents/` holds **subagents you can invoke**, while
`creator-scout-agent/agents/` holds the **scoring spec of record**. Different things — do
not merge them.

## Before you change anything

Two rules break the product if violated, and both are guarded by tests:

1. **Never fabricate creator metrics.** Emit a gap and flag the row.
2. **Never modify the scoring weights** (.30 / .25 / .25 / .10 / .10). They are locked in
   two directions — a test pins the values, and the app fails its suite if `config.py`
   and the spec drift apart.

The full set is in [`CLAUDE.md`](CLAUDE.md) and
[`creator-scout-agent/CLAUDE.md`](creator-scout-agent/CLAUDE.md).

## Known limitation

Dimension 3's TikTok/Instagram ladder saturates — it is an engagement-rate ladder being
fed view-rate data, so 14 of 20 creators score 5/5. A refit was attempted and reverted
because the source rates use inconsistent denominators. The fix is per-platform follower
counts, not new bands; a test keeps the weakness visible until then. See
[`HANDOVER.md`](creator-scout-agent/HANDOVER.md).
