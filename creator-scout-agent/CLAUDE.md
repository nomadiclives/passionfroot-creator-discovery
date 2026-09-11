# Creator Campaign Scout Agent

Campaign-configurable creator discovery, scoring, and shortlisting app. Implements the
`creator-campaign-scout` skill (Steps 1, 4, 5, 5a, 6) as a working web app.

**The spec of record is `agents/creator-campaign-scout.md`** — a verbatim copy of the
skill, checked in so the code and the spec it implements live together. `agent_spec.py`
loads it at runtime, so the app can show a Creator Partnership Manager the exact criteria
and rubric behind a shortlist. Read it before changing anything in `scorer.py`. If you
edit the weights or rubric, edit the spec too — `agent_spec.check_weights_documented()`
fails the test suite when the two drift apart.

## Stack

- **Backend:** Python 3.11 + Flask (`app.py`)
- **Frontend:** Plain HTML + vanilla JS, server-rendered via Jinja2. **No framework** —
  no React, no Vue, no build step. One stylesheet (`static/styles.css`).
- **Data:** CSV in / CSV out. No database.

## Commands

```bash
python app.py                 # starts Flask on http://localhost:5000
python -m pytest tests/       # run the test suite
python scheduler.py --once    # run one discovery pass immediately
python scheduler.py           # run the blocking scheduler loop
```

Install deps with `pip install -r requirements.txt`.

## Hard constraints

### 1. Never fabricate creator metrics
This is the top rule of the skill and the top rule of this codebase. LLMs hallucinate
follower counts, engagement rates, and handles. If a metric is not present in the input
data or returned by a verified enrichment call:

- Do **not** guess, interpolate, or fill with a plausible-looking number.
- Emit `None` / empty, and flag the row `NEEDS_REFRESH`.
- A shortlist with honest gaps is more useful than a clean one with invented numbers.

`scorer.py` enforces this: any creator missing a field in `REQUIRED_FIELDS` is scored
`NEEDS_REFRESH` and excluded from the ranked shortlist. Never "fix" a `NEEDS_REFRESH`
row by inventing data — refresh it from a real source.

Every metric carries a `source` field (`manual`, `favikon`, `modash`). Rows falling back
to manual values after a failed API call are additionally flagged `UNVERIFIED`.

### 2. The scoring formula must match `creator-campaign-scout.md` exactly
Do **not** modify the weights.

```
score = (audience_match   * 0.30)
      + (content_match    * 0.25)
      + (engagement_score * 0.25)
      + (geo_score        * 0.10)
      + (commercial_maturity * 0.10)
```

Sub-scores are 1-5. The skill states its rubric in points out of 100
(D1 30 / D2 25 / D3 25 / D4 10 / D5 10); the two are the same model at different
scales, and `score_100 == weighted_score * 20` exactly. `scorer.py` asserts this
identity. Tier bands (Tier 1 75-100, Tier 2 55-74, Tier 3 35-54) read off `score_100`.

### 3. Campaign role is assigned from Category Readiness, not from total score
Role and tier are independent dimensions. A Tier 1 creator can be an Awareness
candidate; a Tier 2 creator can be a Credibility anchor.

Role reads the **audience's relationship to the campaign's product category** — not
the creator's sub-scores, and never the total.

```
unexposed  -> Awareness    audience has little exposure to the category
exposed    -> Credibility  audience consumes category content, adoption unproven
adopted    -> Conversion   audience demonstrably uses the category
```

The three levels are invariant; the **category** they are judged against is a campaign
parameter (`brief["category"]`). Readiness is a human judgement: absent, the creator is
`NEEDS_REVIEW` and is never given a guessed role.

**Readiness does not transfer between categories.** A judgement is recorded against a
named category (`readiness_category` on the row) and is only evidence about that one.
Run a brief in a different category and those rows come back `NEEDS_REVIEW` — reusing
the judgement would be inventing judgement, which is the same rule as never inventing a
metric. This matters most to `scheduler.py`, which runs several categories against one
pool. A row with no `readiness_category` predates the field and still scores: the guard
fires on a known mismatch, never on absence.

**This replaced the D1/D2 rule** (`D1 >= 4 AND D2 >= 4 -> Credibility`, etc.). That rule
was a lossy proxy: it measures who the audience is and what the creator makes, then
infers adoption. Against the hand-scored Craftly set it mislabelled **7 of 18** creators —
genzbestie scores 5/4 and is still Awareness, because scoring well on audience and
content says nothing about whether that audience has ever opened a tool in the category.
It also left a fourth quadrant (both below threshold) undefined. Changed 2026-09-10 with
the product owner's sign-off; `config.ROLE_THRESHOLD` is now unused by role assignment.

The **student-AI gap** is a structural constraint, not a sourcing failure. If the
shortlist skews to Awareness and Conversion with few Credibility anchors, report that
plainly — never rebalance by forcing creators into roles they don't fit.

### 4. D3 is one construct measured by many instruments
Dimension 3 is **Audience Resonance**: does this creator's audience show up for their
content? The construct is invariant. The instrument is not — it varies by platform and
format, because the platforms are not commensurable:

- **Feed video** (TikTok, Reels, Shorts, YouTube) exposes a view count -> `views / followers`
- **Static and text** (Instagram carousels, LinkedIn posts) expose none -> `interactions / followers`

A raw rate is therefore **meaningless across instruments**. 30% view rate on TikTok, 30%
on YouTube and 30% interaction rate on LinkedIn are three different events. Each
instrument carries its own bands and normalises to the same 1-5 scale. **Only the
normalised score is comparable — never the raw rate.** See `config.INSTRUMENTS`.

An instrument with `bands: None` is **not calibrated**: the engine returns
`NEEDS_CALIBRATION` rather than inventing a band boundary. LinkedIn is uncalibrated today.

Gates are separate from, and beat, the D3 score:

- **Deliverable fit** — can the creator physically produce the asset? A newsletter is not
  a weak video candidate, it is not a candidate. This is what excludes No-Code Exits.
- **Authenticity** — suspected inauthentic comments drop a creator regardless of rate.
  A high rate on fake comments is worse than a low rate on real ones. This is what
  excludes sofieestudies despite a 4.05.

### 5. CPM is calculated from views, not followers
`avg_views * SPONSOR_DECAY (0.85)` is the reach denominator. Never use follower count.

### 5a. A competitor sponsorship flags. Only a recorded clause drops.
Changed 2026-09-11 with the product owner's sign-off, because the code was stricter
than the spec it implements. `creator-campaign-scout.md` is soft on this in all three
places it appears — Pass 2 says competitor-sponsored creators are "pre-qualified as
being in the right niche, even if competitor exclusivity makes **some** ineligible",
its output line says "**flag** any competitor exclusivity", and Step 3 asks whether
they are "**currently** sponsored by" a rival. The engine dropped them all.

It was also wrong on the merits. A creator a rival has already paid is a *qualified*
lead: they take sponsorships, they can execute a brief, and their audience tolerates
paid content in this category. That is the whole premise of Search Pass 2, which exists
to go and find them.

Note which brands sit in which list — the spec is making a distinction worth keeping.
Pass 2 audits **adjacent** tools (Notion, Canva, Grammarly) to *source* creators;
`brief["exclusions"]` names **head-to-head** rivals (Bubble, Glide, Adalo, FlutterFlow,
Softr). Adjacent is a recruiting ground; head-to-head is worth a second look. Neither is
a disqualification.

So there are now three distinct signals, and they must not be collapsed:

| Signal | Where it is read | Effect |
|---|---|---|
| Rival named in `current_sponsors` | a record of who pays them | **Flag** — check for a clause |
| Rival named in `notes` | prose about them | **Flag**, worded as a *mention* |
| `exclusivity` records an active clause | a contract term someone read | **Drop** |

The notes case is the one that proves the rule. On the bundled data the only mention of
a rival is soojintech's note — *"confirmed Cursor as a brand partner - already
comfortable sponsoring AI coding tools"* — written by the sourcer as a **reason to want
them**. The old gate read it as a disqualification and silently removed a 91-point
creator from the shortlist. Prose does not say what it means: a stale credit, a
comparison ("much better than Bubble") and a recommendation all look identical to a
substring match, so notes raise a flag for a person to read and never reject anyone.

`exclusivity` is a recorded judgement, exactly like `readiness` and `brand_safety`:
absent means nobody checked, never "no clause". `scorer.commercial_flags()` produces the
warnings, `results.html` renders them per row, and `screening.check_competitor` returns
the matching verdict so the triage screen and the shortlist cannot disagree.

### 6. Judgement can be typed. A metric must be sourced.
The judging screen (`/judge`) lets a human supply the four judged sub-scores and the
readiness call in the browser instead of hand-editing CSV columns. This does **not**
weaken rule 1 — it is the same human judgement arriving through a better door.

The boundary is what matters, and it must hold exactly:

- The form offers the four `JUDGED_FIELDS` and `readiness`. It must **never** offer an
  input for `followers`, `resonance_rate`, `avg_views` or any other metric. Adding one
  would invite the invention the engine exists to prevent.
- A row that is `NEEDS_REFRESH` is **locked**, not judgeable. Judging cannot rescue a
  metric gap, and a form that implied otherwise would be lying about what is wrong.
- Saving readiness also writes `readiness_category` from the brief. An in-app judgement
  is bound by the non-transfer rule (rule 4 of `HANDOVER.md`) exactly like a sourced one.
- Judging **forks** the bundled pool rather than editing `data/creators.json`, which
  carries provenance a browser form cannot supply. Rows judged in-app carry
  `judged_in_app` and `judged_date` so the two are always distinguishable.
- Out-of-range input is refused, not clamped. `scorer._judged()` clamps values arriving
  from sourced data; accepting form input is a different job, because the operator is
  present to be told. A refused save writes nothing rather than half-updating the pool.

`tests/test_judging.py` pins all of the above.

### 7. Discovery produces candidates, never creators
`discovery.py` and `sources/` are the front half — Steps 2 and 3 of the spec. They are
the first code in this project that *produces* creators rather than consuming them, which
makes them the likeliest place to break rule 1. A system that invents a creator is worse
than one that invents a metric: the metric is at least attached to someone real.

A source adapter must:

- **Return what it got, never what it inferred.** No estimating followers from views, no
  inferring audience age from content. An absent field stays absent and becomes
  `NEEDS_REFRESH`. A hidden subscriber count is **not** zero.
- **Carry provenance.** `search_source` (which pass and query found them), `sourced_date`,
  and `source_confidence` — `measured` (an API returned it), `reported` (self-reported),
  or `candidate` (a handle with no metrics yet).
- **Report a cap it hit.** `SourceResult.truncated` plus a note. A short list that looks
  complete is the failure this codebase exists to prevent, so a YouTube run budgets its
  quota up front and stops itself rather than being cut off mid-run.
- **Never write judgement.** No sub-scores, no `readiness`, no role. Discovery is
  mechanical and wide; judgement is human and narrow. Candidates flow to `/judge`.

Two merge rules in `discovery.merge()`:

- **Corroboration is evidence.** The same creator from three passes is the strongest free
  signal discovery produces — keep it in `corroborated_by`, do not collapse it away.
- **Conflicting metrics are never averaged.** The more confident source wins and the
  disagreement goes in `metric_conflicts`. An average is a number no source reported.

The spec's seed hashtags belong to the campaign they were written for and are used only
when the brief names that brand — the same non-transfer rule as `readiness_category`.

### 8. A screening check nobody answered is not a pass
`screening.py` is Step 3 — the red-flag triage between discovery and judging. The spec
asks for PASS / FLAG / FAIL per check. This implementation adds a fourth answer,
**`UNKNOWN`**, and it is the reason the module earns its place.

A triage that reports PASS on a creator nobody looked at launders an absence of evidence
into a clean bill of health. That is rule 1 one level up: not a number nobody measured,
but a **judgement nobody made**. So:

- A check with no data returns `UNKNOWN`, never `PASS`.
- An `UNKNOWN` on a **blocking** check holds the row at `NEEDS_SCREENING`, and it
  **outranks `FLAG`** — a concern somebody weighed is a better position than a gap
  nobody looked at. Precedence is `FAIL` > unanswered-blocking > `FLAG` > `PASS`.
- An empty field is not good news. A creator with no sourced sponsors has not been
  cleared of a competitor conflict, so `check_competitor` returns `UNKNOWN`, not `PASS`.
- A value the module does not recognise is `UNKNOWN`, not the nearest verdict.

Every check records a `basis`: `computed` (arithmetic over sourced data), `recorded` (a
human or an API wrote the field), or `human` (no source in this app can ever supply it —
brand safety and the follower growth curve, per `DISCOVERY_PLAN.md` §5). The consequence
is deliberate: **the bundled pool screens as all `NEEDS_SCREENING`**, because nobody has
recorded a brand-safety review. `screen_all()` reports which checks are unanswered most
often, which is the sourcing backlog in priority order.

Two boundaries that must hold exactly:

- **Screening never conflates `engagement_rate` with `resonance_rate`.** The spec's Step 3
  suspect thresholds read an engagement ratio; `resonance_rate` is a view rate on a
  different denominator. Substituting one for the other collapses the instrument
  distinction rule 4 is built on, so an absent `engagement_rate` is `UNKNOWN`.
- **Screening never infers demographics from content.** `audience_evidence()` gathers the
  signals the spec's Audience Fit block asks a human to weigh and attaches **no verdict**.
  It never writes `audience_18_24_pct` or `geo_us_pct` — D1 and D4, 40% of the score.

Screening is also **read-only**: it writes no status, score or role, and `/screen` has no
form. Clearing a check means sourcing evidence onto the row, not ticking a box. The Step 3
gates it shares with the scorer (`can_deliver`, `competitor_hit`) are *called*, not
reimplemented, and `tests/test_screening.py` pins that screening FAILs exactly the
creators the scorer drops.

## Enrichment toggle

`config.py` -> `ENRICHMENT_ENABLED` (default `False`).
Also `API_PROVIDER` (`"favikon"` or `"modash"`) and `API_KEY` (empty).
`enricher.py` is a wired-but-inert stub: with the toggle off it returns input data
unchanged with `source='manual'`. Never commit a real API key.

## Layout

```
agents/         creator-campaign-scout.md — the skill spec, verbatim, spec of record
agent_spec.py   loads and parses that spec (campaign slot, hard rules, weight check)
config.py       campaign defaults, weights, rubric thresholds, toggles
scorer.py       the scoring engine — Steps 1, 4, 5, 5a of the skill
enricher.py     API enrichment stub (Favikon / Modash), off by default
scheduler.py    weekly soft-roster discovery loop
app.py          Flask API + server-rendered UI
creator_pool.py uploaded-pool parsing/parking, and the judging write-back
discovery.py    the discovery seam — candidates, provenance, dedupe (Step 2)
screening.py    Step 3 red-flag triage — PASS/FLAG/FAIL/UNKNOWN, read-only
sources/        discovery adapters: query_plan.py (free), youtube.py (needs a key)
templates/      base.html (shell), index.html (Screen 1 brief),
                results.html (Screen 2 shortlist), judge.html (judging screen),
                discover.html (Screen 0 discovery), screen.html (Step 3 triage),
                schedule.html (schedule console)
static/         styles.css
data/           creators.json (sourced), pipeline_intel.json
reports/        soft_roster_YYYY-MM-DD.csv output (auto-created)
logs/           scheduler.log (auto-created)
```

## Verification after each build step

After any change, actually run the app and confirm the UI renders — do not assume:

1. `python app.py` starts with no traceback.
2. `GET localhost:5000` renders Screen 1 with every form field present.
3. Submitting the brief renders Screen 2 with a populated, scored table.
4. Spot-check the weighted score of at least 3 creators by hand against the formula.
5. Export to CSV downloads a valid file with a header row.
6. `GET /schedule` (and `/api/schedule`) returns a valid JSON response.
7. `GET /screen` renders the triage matrix and the "what to source next" backlog,
   and `/api/screen` answers the same as JSON.

`python -m pytest tests/` covers all six against the Flask test client, plus the formula
identity and spec/config agreement. **The test client is not a browser**: it proves the
routes answer and the HTML contains what it should, not that the page renders. Drive the
real app for anything that changes a template or the stylesheet.

`/schedule` answers HTML to a browser and JSON to `?format=json` or an
`Accept: application/json` header; `/api/schedule` is always JSON.

## Known deviations from the spec

Two places where this implementation knowingly differs from
`agents/creator-campaign-scout.md`. Both are deliberate — do not "fix" them without
reading this first.

1. **Dimension 1 normalisation.** The spec declares Audience Match as 30 pts but its
   sub-rubric sums to 25 (age skew 15 + US geography 10). `score_audience_match()`
   scales the components by 30/25 so the dimension's ceiling is reachable and the
   spec's own `D1 >= 22/30` role rule stays meaningful. Likely a typo in the spec.

2. **Role thresholds.** The spec cuts roles at `D1 >= 22/30` (~3.67 on the 1-5 scale)
   and `D2 >= 18/25` (3.6). This app cuts at 4.0 on both, per the build brief. The
   fourth quadrant (both below 4) is unspecified in either; `assign_role()` falls to
   the stronger dimension and never to Credibility, since Credibility is the one role
   the spec calls scarce and evidence-gated.
