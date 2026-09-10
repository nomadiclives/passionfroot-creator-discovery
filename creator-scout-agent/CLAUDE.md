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
templates/      index.html (Screen 1 brief), results.html (Screen 2 shortlist),
                schedule.html (schedule console)
static/         styles.css
data/           sample_creators.csv, pipeline_intel.json
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

`python -m pytest tests/` covers 1, 3, 4, 6, the formula identity, and spec/config
agreement; the browser checks still matter for 2 and 5.

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
