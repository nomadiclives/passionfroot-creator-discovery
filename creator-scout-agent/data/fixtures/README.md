# Engine check fixture

`engine_check.csv` — 13 synthetic creators, each one written to prove a single
engine behaviour. Nobody in it is real; every row is labelled `source=fixture`.

**Use it like this.** Upload `engine_check.csv` on the Brief screen with the default
Craftly brief (category `AI app-building tools`, all platforms, band `all`). Then check
each row against the table below. If all thirteen behave, the engine is applying the
rubric correctly — and since nothing in the engine is brand-specific, that holds for any
brand's list, not just this one.

This tests **the machine**, not the judgement. Whether the 1–5 scores you typed are
*good* is a separate question, and no fixture can answer it. See "What this cannot
tell you" below.

## Expected outcomes

| Row | Proves | Expected |
|---|---|---|
| 01 Perfect Score | The weights are applied exactly | `Keep`, weighted **5.00** |
| 02 Floor Case | Resonance far below the lowest band | `Keep` at 4.00 — **see the open question below** |
| 03 Missing Followers | A required metric is absent | `NEEDS_REFRESH`, no score invented |
| 04 Missing Rate | A required metric is absent | `NEEDS_REFRESH`, no score invented |
| 05 No Readiness | Judgement never made | `NEEDS_REVIEW`, no role assigned |
| 06 Wrong Category | Judged against another category | `NEEDS_REVIEW`, names `Fintech apps` |
| 07 Unexposed Role | Readiness drives role | `Keep`, role **Awareness** |
| 08 Exposed Role | Readiness drives role | `Keep`, role **Credibility** |
| 09 Adopted Role | Readiness drives role | `Keep`, role **Conversion** |
| 10 Locked By Clause | A read exclusivity clause removes a creator | `Drop`, reason names the clause |
| 11 Rival Sponsor No Clause | A rival's creator is a lead, not a disqualification | `Keep`, carries a commercial flag |
| 12 Uncalibrated Platform | No fitted bands for the platform | `NEEDS_CALIBRATION` |
| 13 Weak All Round | Below the tier floor | `Drop`, reason gives the score |

Rows 07–09 are identical apart from `readiness`, so they also prove the point that is
easiest to lose: **role comes from readiness, not from rank.** All three score 4.65.

Also worth confirming by hand on row 01:
`(5 × 0.30) + (5 × 0.25) + (5 × 0.25) + (5 × 0.10) + (5 × 0.10) = 5.00`

## Open question this fixture surfaced

**Row 02 has a 0.4% view rate — effectively nobody watching — and is still kept, at
4.00, ranked sixth.** It scores 1/5 on resonance and the other four dimensions carry it.

The spec states a hard rule: *"Engagement rate is a gate, not a tiebreaker. A creator
below the floor is ineligible regardless of how well they score on other dimensions."*
**No such gate currently fires.** Every instrument has `floor=None`.

That is not careless. The spec's floors (TikTok/Instagram 3.5%, YouTube 1.5%) are
*engagement rate* — likes and comments over reach. The instrument here is *view rate*,
a different construct on a different denominator, and `config.py` is explicit that
substituting one for the other is the exact conflation the instrument model exists to
prevent. There is no published view-rate floor to use instead, and inventing one would
be inventing a boundary — which this codebase refuses to do elsewhere.

So the gate is absent for a defensible reason. But the absence is not recorded anywhere
an operator would see it, and the consequence is real: **a creator nobody watches can be
shortlisted on the strength of four human judgement calls.** Either a view-rate floor
gets fitted from real data, or the missing gate should be stated on the How it works
page next to the other limitations. Not yet decided.

## What this cannot tell you

- **Whether your judgement scores are right.** The fixture proves the arithmetic and the
  gates. The four judged dimensions are whatever was typed in.
- **Whether a real creator was scored well.** For that you need a human benchmark: score
  a real list yourself *before* looking at the tool's output, then compare. The share you
  agree on is the measure. That is what the Craftly sheet was for.

## First run on a new brand will look empty — that is correct

A new brand usually means a new product category, and every readiness call in the pool
was made against one named category. Rows judged against a different one come back
`NEEDS_REVIEW` rather than carrying a stale role across. Row 06 proves that deliberately.
