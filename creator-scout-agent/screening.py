"""Screening — Step 3 of creator-campaign-scout.md.

`discovery.py` finds candidates. `scorer.py` scores creators. Between them sits
the triage this module implements: for every candidate, is there any reason not
to pitch them at all? The spec calls it "Screening and Red Flag Triage" and asks
for a ✅ PASS / ⚠️ FLAG / ❌ FAIL per check.

This adds a fourth verdict the spec does not name, and it is the reason the
module is worth having:

    **UNKNOWN — nothing was ever sourced to answer this check.**

A triage that answers PASS when it checked nothing is worse than no triage,
because it launders an absence of evidence into a clean bill of health. That is
the same failure as inventing a metric, one level up: instead of a number nobody
measured, it is a *judgement* nobody made. So a check with no data returns
UNKNOWN, an UNKNOWN on a blocking check holds the whole row at
NEEDS_SCREENING, and PASS is reachable only when somebody actually looked.

The consequence is deliberate and will look severe: **run this against today's
bundled pool and every row comes back NEEDS_SCREENING**, because brand safety
has never been recorded for any of them. That is the correct answer. The open
items are the to-do list, and `screen_all()` reports which checks are unknown
most often, which is the same thing as saying what to go and source next.

Three kinds of check, and the difference is recorded on every one as `basis`:

- `computed` — arithmetic over sourced metrics. Deliverable fit, competitor
  exclusivity, the view-to-follower ratio. These the machine can answer.
- `recorded` — a field a human or an API wrote. Comment quality. The machine
  reports it; it never derives it.
- `human` — no data source in this system can ever supply it. Brand safety and
  the follower growth curve. These stay UNKNOWN until a person writes them
  down, permanently, by design. See DISCOVERY_PLAN.md §5.

What this module will not do, however much the spec's "Audience Fit
Verification" block invites it: turn content signals into demographics. "They
say 'dorm', so the audience is 18-24" is a guess wearing evidence's clothes.
`audience_evidence()` gathers those signals and hands them to a human **as
evidence, with no verdict attached** — it never writes `audience_18_24_pct` or
`geo_us_pct`, which are D1 and D4, 40% of the score, and are exactly what the
free tier cannot honestly supply.
"""

from __future__ import annotations

import datetime as _dt
from typing import Iterable

import config
import scorer

PASS = config.SCREEN_PASS
FLAG = config.SCREEN_FLAG
FAIL = config.SCREEN_FAIL
UNKNOWN = config.SCREEN_UNKNOWN

# The row-level rollup. Not a per-check verdict: it means at least one blocking
# check has never been answered, so no defensible PASS is available yet.
NEEDS_SCREENING = "NEEDS_SCREENING"

# Recorded-judgement vocabularies. Unrecognised text is UNKNOWN, never coerced
# into the nearest verdict — a value this module does not understand is a value
# it must not interpret.
BRAND_SAFETY_CLEAR = ("clear", "ok", "safe", "pass")
BRAND_SAFETY_CONCERN = ("flag", "minor", "concern", "watch")
BRAND_SAFETY_UNSAFE = ("unsafe", "fail", "controversy", "controversial")

GROWTH_ORGANIC = ("organic", "gradual", "steady")
GROWTH_SUSPECT = ("spike", "purchased", "bought", "bulk", "inorganic")


class Check:
    """One triage question and its answer.

    `blocking` says whether an UNKNOWN here holds the row. It is set on checks
    where absence of evidence is not weak evidence of absence: nobody having
    recorded a competitor sponsorship does not mean there isn't one.
    """

    def __init__(
        self,
        key: str,
        label: str,
        verdict: str,
        reason: str,
        basis: str,
        blocking: bool = False,
    ):
        self.key = key
        self.label = label
        self.verdict = verdict
        self.reason = reason
        self.basis = basis
        self.blocking = blocking

    @property
    def open_item(self) -> bool:
        """An unanswered check that is holding the row."""
        return self.verdict == UNKNOWN and self.blocking

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "verdict": self.verdict,
            "reason": self.reason,
            "basis": self.basis,
            "blocking": self.blocking,
            "open_item": self.open_item,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Check {self.key} {self.verdict}: {self.reason}>"


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------
def check_deliverable(creator: dict, criteria: dict) -> Check:
    """Can this creator physically produce the asset the brief asks for?

    Delegates to `scorer.can_deliver` rather than reimplementing it, so the
    triage screen and the scorer's Drop reason are the same sentence.
    """
    wanted = criteria.get("deliverable_formats") or ()
    if not wanted:
        return Check(
            "deliverable", "Deliverable fit", PASS,
            "brief names no required format", config.BASIS_COMPUTED, blocking=True,
        )

    has_surface = bool(creator.get("platforms")) or bool(creator.get("other_surfaces"))
    if not has_surface:
        return Check(
            "deliverable", "Deliverable fit", UNKNOWN,
            "no publishing surface recorded — cannot tell what they can produce",
            config.BASIS_COMPUTED, blocking=True,
        )

    ok, why = scorer.can_deliver(creator, criteria)
    if ok:
        return Check(
            "deliverable", "Deliverable fit", PASS,
            f"can produce {'/'.join(sorted(wanted))}",
            config.BASIS_COMPUTED, blocking=True,
        )
    return Check(
        "deliverable", "Deliverable fit", FAIL, why,
        config.BASIS_COMPUTED, blocking=True,
    )


def check_competitor(creator: dict, criteria: dict) -> Check:
    """Currently sponsored by a competitor the brief excludes?

    The honest half of this check is the negative case. An empty sponsor field
    means nobody sourced their sponsors — not that they have none — so it is
    UNKNOWN, not PASS. Reading it as PASS would clear a creator of a conflict
    on the strength of never having looked.
    """
    exclusions = criteria.get("exclusions") or []
    if not exclusions:
        return Check(
            "competitor", "Competitor exclusivity", PASS,
            "brief names no competitor exclusions",
            config.BASIS_COMPUTED, blocking=True,
        )

    hit = scorer.competitor_hit(creator, exclusions)
    if hit:
        return Check(
            "competitor", "Competitor exclusivity", FAIL,
            f"excluded: competitor sponsorship ({hit})",
            config.BASIS_COMPUTED, blocking=True,
        )

    if not scorer.competitor_sponsor_text(creator).strip():
        return Check(
            "competitor", "Competitor exclusivity", UNKNOWN,
            "no sponsor information sourced — absence of a competitor was never "
            "confirmed, only never observed",
            config.BASIS_COMPUTED, blocking=True,
        )

    return Check(
        "competitor", "Competitor exclusivity", PASS,
        f"no excluded competitor named in sourced sponsor text "
        f"({len(exclusions)} checked)",
        config.BASIS_COMPUTED, blocking=True,
    )


def check_comment_quality(creator: dict, criteria: dict) -> Check:
    """The authenticity gate, read from the recorded `comment_quality` field.

    Reads the same vocabulary as `scorer.score_engagement`'s gate, from
    `config`, so a value that drops a creator in the scorer FAILs them here.
    """
    quality = str(creator.get("comment_quality") or "").strip().lower()
    if not quality:
        return Check(
            "comments", "Comment quality", UNKNOWN,
            "no comment-quality assessment recorded",
            config.BASIS_RECORDED, blocking=True,
        )
    if quality in config.COMMENT_QUALITY_INAUTHENTIC:
        return Check(
            "comments", "Comment quality", FAIL,
            f"comments suspected inauthentic ({quality}) — a high rate on fake "
            "comments is worse than a low rate on real ones",
            config.BASIS_RECORDED, blocking=True,
        )
    if quality in config.COMMENT_QUALITY_GENERIC:
        return Check(
            "comments", "Comment quality", FLAG,
            f"{quality} comments — signals an inflated rate, low real influence",
            config.BASIS_RECORDED, blocking=True,
        )
    if quality in config.COMMENT_QUALITY_GOOD:
        return Check(
            "comments", "Comment quality", PASS,
            f"{quality} comments",
            config.BASIS_RECORDED, blocking=True,
        )
    return Check(
        "comments", "Comment quality", UNKNOWN,
        f"unrecognised comment-quality value ({quality}) — not interpreted",
        config.BASIS_RECORDED, blocking=True,
    )


def check_engagement_authenticity(creator: dict, criteria: dict) -> Check:
    """The spec's follower-to-engagement suspect ratio.

    Corroborates the comment-quality gate rather than duplicating it, so it is
    not blocking: `comments` is the blocking authenticity check.

    Two things this deliberately does not do. It does not read
    `resonance_rate` — that is a view rate on a different denominator, and
    substituting it would collapse the instrument distinction D3 is built on.
    And it flags rather than fails, because the spec calls these numbers
    "suspect", while the numbers that make a creator *ineligible* are the
    separate D3 floors the scorer applies.
    """
    platform = scorer._primary_platform(creator, criteria)
    rate = creator.get("engagement_rate")

    if rate is None:
        return Check(
            "engagement", "Engagement ratio", UNKNOWN,
            "engagement_rate not sourced — resonance_rate is a view rate on a "
            "different denominator and is not a substitute for it",
            config.BASIS_COMPUTED,
        )

    threshold = config.SCREEN_ENGAGEMENT_SUSPECT.get(platform)
    if threshold is None:
        return Check(
            "engagement", "Engagement ratio", UNKNOWN,
            f"no suspect threshold published for "
            f"{scorer._pretty_platform(platform) or 'this platform'}",
            config.BASIS_COMPUTED,
        )

    if rate < threshold:
        return Check(
            "engagement", "Engagement ratio", FLAG,
            f"{rate:.2f}% on {scorer._pretty_platform(platform)} — below the "
            f"spec's {threshold}% suspect threshold",
            config.BASIS_COMPUTED,
        )
    return Check(
        "engagement", "Engagement ratio", PASS,
        f"{rate:.2f}% on {scorer._pretty_platform(platform)} — at or above the "
        f"{threshold}% suspect threshold",
        config.BASIS_COMPUTED,
    )


def check_view_to_follower(creator: dict, criteria: dict) -> Check:
    """Views consistently far below followers — ghost following or a shadow-ban.

    The floor is a project policy choice, not a spec number: the spec says
    "MUCH lower" and names none. The reason text says so every time, because a
    threshold presented as the spec's would be borrowing authority it does not
    have.
    """
    followers = creator.get("followers")
    views = creator.get("avg_views")
    floor = config.SCREEN_VIEW_FOLLOWER_FLOOR_PCT

    if followers is None or views is None:
        missing = "followers" if followers is None else "avg_views"
        return Check(
            "view_ratio", "View-to-follower ratio", UNKNOWN,
            f"{missing} not sourced",
            config.BASIS_COMPUTED,
        )
    if not followers:
        return Check(
            "view_ratio", "View-to-follower ratio", UNKNOWN,
            "follower count is zero — ratio undefined",
            config.BASIS_COMPUTED,
        )

    ratio = views / followers * 100
    if ratio < floor:
        return Check(
            "view_ratio", "View-to-follower ratio", FLAG,
            f"views are {ratio:.1f}% of followers, below the {floor:g}% floor "
            f"(a project-set threshold, not the spec's)",
            config.BASIS_COMPUTED,
        )
    return Check(
        "view_ratio", "View-to-follower ratio", PASS,
        f"views are {ratio:.1f}% of followers",
        config.BASIS_COMPUTED,
    )


def check_growth(creator: dict, criteria: dict) -> Check:
    """The follower growth curve — gradual and organic, or bought in bulk?

    Permanently `human` basis. No source wired into this app returns a follower
    time series, so this is UNKNOWN until somebody reads the curve and records
    it. Not blocking, precisely because nothing can currently answer it — a
    blocking check no source can satisfy would make PASS unreachable for a
    reason that says nothing about the creator.
    """
    pattern = str(creator.get("growth_pattern") or "").strip().lower()
    if not pattern:
        return Check(
            "growth", "Follower growth curve", UNKNOWN,
            "no follower time series available from any source wired into this "
            "app — a person must read the curve and record it",
            config.BASIS_HUMAN,
        )
    if any(token in pattern for token in GROWTH_SUSPECT):
        return Check(
            "growth", "Follower growth curve", FAIL,
            f"growth recorded as '{pattern}' — spike-then-plateau suggests "
            "purchased followers",
            config.BASIS_HUMAN,
        )
    if any(token in pattern for token in GROWTH_ORGANIC):
        return Check(
            "growth", "Follower growth curve", PASS,
            f"growth recorded as '{pattern}'",
            config.BASIS_HUMAN,
        )
    return Check(
        "growth", "Follower growth curve", UNKNOWN,
        f"unrecognised growth value ({pattern}) — not interpreted",
        config.BASIS_HUMAN,
    )


def check_brand_safety(creator: dict, criteria: dict) -> Check:
    """Controversy, offensive content, brand collision in the last 60 days.

    Blocking and `human` basis: reading content for controversy is judgement,
    not classification, and DISCOVERY_PLAN.md §5 lists it as permanently
    manual. This is the check that holds today's whole pool at
    NEEDS_SCREENING, and it should, because nobody has done it.
    """
    call = str(creator.get("brand_safety") or "").strip().lower()
    if not call:
        return Check(
            "brand_safety", "Brand safety", UNKNOWN,
            "not reviewed — reading the last 60 days for controversy is a human "
            "judgement, and no API in this app classifies it",
            config.BASIS_HUMAN, blocking=True,
        )
    if any(token in call for token in BRAND_SAFETY_UNSAFE):
        return Check(
            "brand_safety", "Brand safety", FAIL,
            f"reviewed and rejected ({call})", config.BASIS_HUMAN, blocking=True,
        )
    if any(token in call for token in BRAND_SAFETY_CONCERN):
        return Check(
            "brand_safety", "Brand safety", FLAG,
            f"reviewed with a concern ({call})", config.BASIS_HUMAN, blocking=True,
        )
    if any(token in call for token in BRAND_SAFETY_CLEAR):
        return Check(
            "brand_safety", "Brand safety", PASS,
            f"reviewed and clear ({call})", config.BASIS_HUMAN, blocking=True,
        )
    return Check(
        "brand_safety", "Brand safety", UNKNOWN,
        f"unrecognised brand-safety value ({call}) — not interpreted",
        config.BASIS_HUMAN, blocking=True,
    )


# Order is the order they are reported in: hard mechanical gates first, then
# authenticity, then the human reads.
CHECKS = (
    check_deliverable,
    check_competitor,
    check_comment_quality,
    check_engagement_authenticity,
    check_view_to_follower,
    check_growth,
    check_brand_safety,
)


# ---------------------------------------------------------------------------
# Audience fit — evidence, never a verdict
# ---------------------------------------------------------------------------
def audience_evidence(creator: dict, criteria: dict) -> list[dict]:
    """Gather the signals the spec's Audience Fit block asks a human to weigh.

    This returns EVIDENCE AND NOTHING ELSE — no verdict, no score, and above
    all no demographic percentage. D1 (30%) and D4 (10%) ask who is watching;
    no free source answers that, and inferring it from content is the single
    temptation DISCOVERY_PLAN.md §1 exists to close off. A human reads these
    rows on the judging screen and supplies the sub-scores there.
    """
    fields = (
        ("age_evidence", "Age skew signal"),
        ("geo_evidence", "Geography signal"),
        ("location", "Stated location"),
        ("niche_relevance_pct", "Niche overlap (%)"),
        ("sample_video", "Sample content"),
        ("notes", "Sourcing notes"),
    )
    out = []
    for field, label in fields:
        value = creator.get(field)
        if value in (None, "", []):
            continue
        out.append({"field": field, "label": label, "value": value})
    return out


# ---------------------------------------------------------------------------
# Rollup
# ---------------------------------------------------------------------------
def _overall(checks: list[Check]) -> tuple[str, str]:
    """Roll per-check verdicts into one, and say which check decided it.

    Precedence is FAIL > unanswered-blocking > FLAG > PASS. An UNKNOWN on a
    blocking check outranks a FLAG deliberately: a known concern somebody has
    weighed is a better position than a gap nobody has looked at.
    """
    for check in checks:
        if check.verdict == FAIL:
            return FAIL, check.label
    for check in checks:
        if check.open_item:
            return NEEDS_SCREENING, check.label
    for check in checks:
        if check.verdict == FLAG:
            return FLAG, check.label
    return PASS, ""


def screen(creator: dict, criteria: dict) -> dict:
    """Triage one creator. Returns the report; writes nothing to the row.

    Screening is read-only by design. It does not set a status, a score or a
    role — `scorer.py` owns those, and a triage that quietly edited the pool
    would make it impossible to tell a sourced value from a screened one.
    """
    # Normalise unconditionally. `normalise_creator` is idempotent, and taking
    # a raw row and an already-scored row down the same path means the triage
    # answer cannot depend on which door the creator arrived through.
    creator = scorer.normalise_creator(creator)
    checks = [fn(creator, criteria) for fn in CHECKS]
    verdict, decided_by = _overall(checks)

    return {
        "name": creator.get("name", ""),
        "handle": creator.get("handle", ""),
        "platform": creator.get("platform", ""),
        "verdict": verdict,
        "decided_by": decided_by,
        "checks": [c.as_dict() for c in checks],
        "open_items": [c.label for c in checks if c.open_item],
        # Every unanswered check, blocking or not. A row can roll up to PASS
        # with non-blocking gaps still open, so the gaps stay visible rather
        # than being absorbed into the verdict.
        "unanswered": [c.label for c in checks if c.verdict == UNKNOWN],
        "audience_evidence": audience_evidence(creator, criteria),
        # Surfaced so a reader can tell a screening gap from a metric gap. A
        # NEEDS_REFRESH row can still be screened — the metric checks simply
        # come back UNKNOWN, which is the true answer for them.
        "missing_metrics": scorer.missing_required(creator),
        "screened_date": _dt.date.today().isoformat(),
    }


def screen_all(creators: Iterable[dict], criteria: dict) -> dict:
    """Triage a pool, and report what is most often unanswered.

    `unknown_by_check` is the useful output for a person planning work: it is
    the sourcing backlog, ranked. "Brand safety unknown on 25 of 25" is an
    afternoon's reading; "engagement_rate unknown on 25 of 25" is a field
    nothing currently populates.
    """
    rows = [screen(creator, criteria) for creator in creators]

    tally = {PASS: 0, FLAG: 0, FAIL: 0, NEEDS_SCREENING: 0}
    unknown_by_check: dict[str, dict] = {}
    for row in rows:
        tally[row["verdict"]] = tally.get(row["verdict"], 0) + 1
        for check in row["checks"]:
            if check["verdict"] != UNKNOWN:
                continue
            entry = unknown_by_check.setdefault(
                check["key"],
                {"key": check["key"], "label": check["label"],
                 "basis": check["basis"], "blocking": check["blocking"], "count": 0},
            )
            entry["count"] += 1

    backlog = sorted(
        unknown_by_check.values(),
        key=lambda e: (not e["blocking"], -e["count"], e["label"]),
    )

    return {
        "rows": rows,
        "counts": tally,
        "total": len(rows),
        "unknown_by_check": backlog,
        "screened_date": _dt.date.today().isoformat(),
    }
