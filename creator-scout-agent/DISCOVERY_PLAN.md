# Discovery — scoping plan

**Status: Phases 0-2 built, 3-4 not started.** Written 2026-09-10; phases 0-2 built the
same night. See `HANDOVER.md` for what was verified and the two roadblocks hit —
chiefly that the YouTube adapter has never made a real call.

The app scores creators you already have. It cannot find them. Steps 2 and 3 of
`agents/creator-campaign-scout.md` — the discovery playbook and screening — are the
missing first half. This document scopes them.

Read `HANDOVER.md` first for what exists. Read `CLAUDE.md` for the constraints that
survive any of this, because discovery is the phase most likely to break them: it is the
first time the app would produce creators rather than consume them, and a system that
invents a creator is worse than one that invents a metric.

---

## 1. The finding that shapes everything else

Map what the scoring engine needs against what each class of source can honestly supply:

| Field | Weight | YouTube API (free) | Scrape APIs (~$) | Panel tools ($$$) | Human |
|---|---|---|---|---|---|
| `name` / `handle` / `platform` | gate | ✅ | ✅ | ✅ | |
| `followers` | required | ✅ `subscriberCount` | ✅ | ✅ | |
| `avg_views` | CPM model | ✅ `videos.list` | ✅ | ✅ | |
| `resonance_rate` | **D3 · 25%** | ✅ computed | ✅ computed | ✅ | |
| `comment_quality` | authenticity gate | partial — can fetch comments | partial | ✅ fraud score | ✅ |
| `current_sponsors` | D5 · 10% + exclusions | partial — description text | partial | ✅ | ✅ |
| `audience_18_24_pct` | **D1 · 30%** | ❌ | ❌ | ✅ | estimate only |
| `geo_us_pct` | **D4 · 10%** | ❌ | ❌ | ✅ | estimate only |
| `content_match_score` | D2 · 25% | evidence only | evidence only | evidence only | ✅ judgement |
| `readiness` → role | role assignment | ❌ | ❌ | ❌ | ✅ judgement |

**The free/paid line falls exactly on audience demographics, and that is 40% of the
score.** D1 (30%) and D4 (10%) both ask *who is watching* — age skew and US share.
No free API exposes that for someone else's account. Only panel-based tools
(Modash, HypeAuditor, IQFluence) model it, and modelling is what you are paying for.

Three consequences, and they drive the whole build order:

1. **Free discovery is genuinely useful and genuinely partial.** It can find creators
   and evidence D3 honestly — that is a quarter of the score on real numbers. It cannot
   evidence D1 or D4 at all.
2. **A discovered creator is not a scored creator.** Discovery output lands as
   `NEEDS_REVIEW` with sourced metrics attached, and a human closes it on the judging
   screen built on 2026-09-10. The pipeline already has the receiving end.
3. **The temptation to be resisted is inferring demographics from content.** "They say
   'dorm' so the audience is 18-24" is a guess wearing evidence's clothes. If it is
   recorded at all it is recorded as a human judgement with its reasoning, never as
   `audience_18_24_pct`.

---

## 2. Source inventory

Cheapest first, which is also most-honest first.

### Tier 0 — YouTube Data API v3 · free, real, the anchor

The only source that is free, official, permitted, and returns real audience-side
numbers. The spec already says to start with YouTube, for reasons that hold up: content
is search-indexed, has a long shelf life, and exposes a public view count.

The quota shape is the thing to design around:

| Call | Cost | Gives |
|---|---|---|
| `search.list` | **100 units** | up to 50 results per call |
| `channels.list` | **1 unit** | `subscriberCount`, `viewCount`, `videoCount` — batches up to 50 IDs |
| `videos.list` | **1 unit** | `viewCount`, `likeCount`, `commentCount` — batches up to 50 IDs |
| `commentThreads.list` | 1 unit | comment text, for the authenticity gate |

Default project quota is 10,000 units/day. So: **search is expensive (100/day),
enrichment is nearly free.** That asymmetry is the design. Run few broad searches,
harvest channel IDs from video results rather than channel results, then enrich
thousands of channels for almost nothing. A day's quota realistically supports ~80
searches plus full enrichment of everything they surface.

`resonance_rate` for YouTube is computable and reproducible from this: recent-video
median views ÷ subscribers, with both numbers sourced and dated. That is better
provenance than the current bundled data has — see the `rate_reproducible: false` rows.

⚠️ **Needs verifying before building:** the spec's "related channels" pass. YouTube has
deprecated parts of the channel-recommendation surface, and I have not confirmed what is
still exposed. Do not scope the peer-graph walk as certain until someone checks it
against a live key.

### Tier 1 — free proxies, for platforms with no free API

TikTok and Instagram expose nothing useful for free about accounts you do not own. What
is reachable free:

| Source | Yields | Honest limit |
|---|---|---|
| Reddit API (free) | creators named in r/college, r/productivity, r/nocode | mentions, not metrics |
| Google `site:tiktok.com` / `site:instagram.com` searches | candidate handles matching keywords | handles only; needs SerpAPI or manual to run at volume |
| Creator's own link-in-bio / media kit | self-reported reach, sometimes real demographics | self-reported, so flag it |
| Competitor sponsorship audit (Search Pass 2) | pre-qualified niche creators | manual reading; no API |

These produce **candidates, not metrics**. That is fine and worth building: a handle with
no numbers is still a real lead, and the app already knows how to say `NEEDS_REFRESH`.

### Tier 2 — scraping APIs · ~$40–100/mo, fills the TikTok/Instagram metric gap

This is the missing middle the original handover did not consider, and it is better
value than jumping straight to a panel tool.

| Vendor | Model | Covers |
|---|---|---|
| EnsembleData | free 50 units/day; **$100/mo** for 1,500/day | IG, TikTok, YouTube, Reddit — incl. hashtag + keyword search |
| Apify | **$39/mo** + ~$1.50–5 per 1,000 results | actor marketplace, cheapest at volume |
| ScrapeCreators | pay-as-you-go | TikTok, IG, YouTube, Reddit |

**The free tier is enough to prototype.** EnsembleData's 50 units/day would prove the
integration end to end before anyone spends anything.

What these give: follower counts and view counts for TikTok/Instagram handles, which
makes `resonance_rate` computable on those platforms — closing D3 across the whole
brief, not just YouTube. What they do **not** give: audience demographics.

### Tier 3 — panel tools · $199–299/mo, the only honest source of D1 and D4

| Vendor | Entry price | API on a published tier? | Notes |
|---|---|---|---|
| **Modash** | **$199/mo** | ✅ yes | 380M profiles; self-serve trial, no sales call |
| HypeAuditor | $299/mo billed annually | ➖ costs extra | strongest fraud / authenticity detection |
| IQFluence | quote | ✅ included | 375M profiles |
| **Favikon** | **$199/mo** Core · $299 Pro | ❌ quote-only | **best-in-class for LinkedIn / B2B** — see below |

⚠️ *Prices checked 2026-09-10 against third-party aggregators (Capterra, G2, review
sites) because `favikon.com` is unreachable from this sandbox. They disagree with each
other on detail — **confirm on the vendor's own pricing page before committing budget.***

#### The `API_PROVIDER` default

`config.API_PROVIDER` defaults to `"favikon"`, and that is the wrong default for the
**automated enrichment seam**: Favikon's API is quote-only on every source checked, with
no self-serve API product, while Modash publishes an API on its $199 tier.
**Recommend flipping the default to `modash`.**

#### But Favikon is the answer to a different, real problem

Favikon is consistently rated the strongest tool for **LinkedIn and B2B creator
intelligence** — which is precisely where this codebase is blocked:

- `config.INSTRUMENTS["linkedin"]["bands"]` is `None`, so LinkedIn returns
  `NEEDS_CALIBRATION` and cannot be scored at all.
- `data/creators.json` carries a **5-creator LinkedIn cohort with no metrics**, sitting
  there waiting for exactly this.
- "LinkedIn calibration" has been a standing open item in `HANDOVER.md` since the
  original build.

Neither Modash nor the scraping tier covers LinkedIn well. Favikon does.

**And this does not need the API.** Fitting LinkedIn bands is a *one-time data
collection task*, not an integration: collect real interaction rates for a few dozen
LinkedIn creators once, fit the bands, delete the uncalibrated branch. That is Favikon's
**UI** on the $199 Core plan, used for an afternoon — no quote, no sales call, no
adapter to build and maintain.

So the recommendation splits rather than reverses:

| Use | Tool | Why |
|---|---|---|
| Automated enrichment (`API_PROVIDER`) | **Modash** | self-serve API at a published price |
| LinkedIn band calibration, one-off | **Favikon UI** | best LinkedIn coverage; no API needed |
| Fraud / authenticity depth, if it becomes a priority | HypeAuditor | strongest on the authenticity gate |

Favikon also prices in credits ("favicoins" — enrich ≈ 3, refresh ≈ 0.5) rather than flat
calls, which is worth modelling before assuming a monthly seat covers a sourcing run.

---

## 3. Where discovery plugs in

The seam already exists. `build_shortlist(brief, creators)` has always accepted an
arbitrary list, `creator_pool.py` parks one, and the judging screen closes the human
half. Discovery becomes another way to produce a pool.

```
   brief
     │
     ▼
┌─────────────┐   query plan    ┌──────────────┐
│ discovery.py│ ──────────────► │ sources/     │  youtube · reddit · scrape · panel
└─────────────┘ ◄────────────── │  (one file   │
     │           candidates     │   per source)│
     │                          └──────────────┘
     ▼
  candidates: handle + sourced metrics + provenance, judgement absent
     │
     ▼
  creator_pool  ──►  /judge  ──►  scorer  ──►  shortlist
                    (human)
```

**Design rules for this layer**, each a restatement of an existing constraint:

- **A source adapter returns what it got, never what it inferred.** Absent field → absent,
  which becomes `NEEDS_REFRESH` downstream. Same rule as `enricher.py` already follows.
- **Every candidate carries `search_source`** — which pass and which query found it. The
  field already exists in `normalise_creator()` and is currently unused. Discovery is
  what it was for.
- **Discovery never assigns a role or a sub-score.** It produces metrics and evidence.
  Judgement stays human, routed to the screen that now exists.
- **Dedupe across passes and against the existing pool** on handle+platform. The same
  creator surfacing from three passes is a *signal*, worth recording as corroboration,
  not three rows.
- **Rate-limit and cache per source.** YouTube's 100 searches/day is the binding
  constraint; a cache that survives a restart is not optional.

---

## 4. Build order

Sized in rough half-days. Each phase is independently shippable and useful alone.

### Phase 0 — the seam · ~1 day · no external calls, no keys — ✅ **BUILT**
`discovery.py` with the candidate schema, provenance fields, dedupe, and a fake source
adapter. Fully testable offline. This is where the never-invent rules get their tests,
*before* any network code exists to blur them.

### Phase 1 — YouTube · ~1–2 days · free — ⚠️ **BUILT, UNVERIFIED** (needs a key)
Real search over the spec's Pass 1 keywords, channel and video enrichment, computed
`resonance_rate`, quota accounting with a visible budget. **This is the phase that proves
the whole thesis**: a brief in, real sourced creators out, no invented numbers, $0.

### Phase 2 — the manual and proxy bridge · ~1 day · free — ✅ **BUILT**
The honest answer to platforms with no free API, and to the spec's judgement-heavy
passes. The app generates a **click-through query plan** — real hashtag and keyword URLs
per platform, per pass — the operator runs them in a browser, and pastes handles back
into a box. The app then enriches what it can and routes the rest to judging.

This deliberately keeps a human in the loop rather than pretending an API exists. It
also makes Search Passes 2 and 4 (competitor audits, subreddit and Discord moderators)
operable, which no vendor will ever automate.

### Phase 3 — scraping tier · ~1–2 days · $0 to prototype, ~$40–100/mo at volume
One adapter behind the same interface, starting on EnsembleData's free 50/day. Closes
D3 for TikTok and Instagram.

### Phase 4 — panel tier · ~1 day · $199/mo
Modash adapter for audience demographics — the only way to evidence D1 and D4. Reuses
`enricher.py`'s existing `FIELD_MAP` seam. Build last: it is the only phase that cannot
be prototyped free, and by then everything around it is proven.

---

## 5. What stays manual, permanently

Worth stating so nobody scopes a phase to automate it:

- **Category readiness**, and therefore campaign role. No API knows whether an audience
  has *adopted* a product category. This is the judgement the whole role model rests on.
- **Competitor sponsorship audits** at any depth — reading a creator's last 60 days for
  brand collisions.
- **Discord and subreddit moderator discovery.** No endpoint exists.
- **Brand safety.** Reading content for controversy is judgement, not classification.
- **The final call.** The tool produces a defensible shortlist. A person still owns it.

The spec is right that Step 2 produces *a query plan, not creators*. Phase 2 implements
that literally rather than working around it.

---

## 6. Cost summary

| Stage | Monthly | Gets you |
|---|---|---|
| Phases 0–2 | **$0** | YouTube discovery with real metrics + operable manual passes for everything else |
| \+ Phase 3 | ~$40–100 | D3 closed across TikTok and Instagram |
| \+ Phase 4 | ~$200–300 | D1 and D4 evidenced — the full model on sourced data |

A defensible free tier exists, which is the useful finding. Phases 0–2 are worth building
before any spending decision, because they also tell you how much sourcing volume you
actually need before you buy a seat.

---

## 7. Decisions needed before Phase 1

1. **Which platform matters most for the next real campaign?** The build order assumes
   YouTube-first per the spec. If the next brief is TikTok-led, Phase 3 moves ahead of
   Phase 2 and the plan starts costing money immediately.
2. **Is a paid tool available at all?** If Modash is already budgeted, Phase 4 could run
   early and cheaply de-risk D1/D4. If nothing is budgeted, Phase 2 becomes the ceiling
   and should be built properly rather than as a stopgap.
3. **Flip `API_PROVIDER` to `modash`?** Recommend yes regardless — see §2 Tier 3.
4. **Is LinkedIn in scope for a real campaign?** If yes, a Favikon Core seat used for one
   afternoon of manual collection would unblock the uncalibrated LinkedIn instrument and
   the 5-creator cohort — cheaper and faster than any integration. If LinkedIn is not
   coming up, leave it uncalibrated and say so on screen, which the app already does.
5. **Volume target.** "15–20 shortlisted" implies sourcing maybe 200–400 candidates per
   campaign. That is comfortably inside YouTube's free quota and cheap on a scraping
   tier. Confirm, because it is the number that decides whether any of this needs a paid
   plan at all.

---

## 8. Risks

- **Terms of service.** Scraping TikTok and Instagram violates their terms. Using a
  vendor moves the risk rather than removing it. Worth a deliberate decision rather than
  a default, especially for a client-facing tool.
- **Personal data.** Discovery output is personal data about named people, and the
  repository is currently **public**. This should be settled before discovery runs at
  volume — it multiplies what is in `data/`.
- **Quota exhaustion looking like a bug.** 100 searches/day disappears fast. Budget must
  be visible on screen, in the same spirit as the empty-roster explanation.
- **Silent partial results.** A source returning 3 of 50 candidates because it hit a
  limit must say so. A short list that looks complete is the failure mode this whole
  codebase is built against.
- **Scope creep into a CRM.** Discovery ends at a scored shortlist. Outreach, contact
  enrichment and pipeline tracking are a different product.

---

## 9. Rejected

**Phantom Buster, Apollo.io and Hunter.io** — all three are connected to this workspace
and all three are the wrong shape. Apollo and Hunter are B2B contact databases: they find
employees at companies by job title, not creators by audience or content. Phantom Buster
is closer, but the connected account is on a free plan capped at 30 minutes of execution
per month with one agent slot, and all four existing phantoms are LinkedIn company
employee exports belonging to an unrelated project.

They may earn a place later in **outreach** — finding a contact address for a creator you
have already shortlisted — which is a different problem than the one this document scopes.

**LLM-generated candidate lists.** A model asked for "TikTok creators in the student
productivity niche" will produce plausible handles, some of which will not exist. This is
the single fastest way to destroy the product's credibility and is closed by the
never-fabricate rule.
