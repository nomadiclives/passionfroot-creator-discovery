"""Scoring engine for the Creator Campaign Scout Agent.

Implements Steps 1, 4, 5 and 5a of creator-campaign-scout.md:

  Step 1   lock_criteria()      brief -> locked criteria set
  Step 4   load_creators()      CSV/JSON -> normalised creator profiles
  Step 5   score_creator()      five-dimension weighted model
  Step 5a  assign_role()        campaign role from Category Readiness
  Step 6   build_shortlist()    ranked, tiered, role-assigned output

HARD RULE — never fabricate creator metrics. A creator missing any REQUIRED_FIELD is
flagged NEEDS_REFRESH and kept out of the ranked shortlist. Optional evidence fields
that are absent score 0 for their component; they are never guessed.
"""

from __future__ import annotations

import csv
import io
import json
import os
from typing import Any, Iterable

import config

# Metrics that must be present. Missing any of these -> NEEDS_REFRESH.
REQUIRED_FIELDS = (
    "name",
    "platform",
    "followers",
    "resonance_rate",
)

# Dimensions that no engine can derive from a follower count. A human scores
# these 1-5 with written evidence; absent, the creator is NEEDS_REVIEW and is
# never given a guessed number.
JUDGED_FIELDS = (
    "audience_match_score",
    "content_match_score",
    "geo_match_score",
    "commercial_maturity_score",
)

# Optional evidence fields. Absent means "no evidence", which scores 0 for that
# component — it never means "assume a good value".
NUMERIC_FIELDS = (
    "resonance_rate",
    "audience_match_score",
    "content_match_score",
    "geo_match_score",
    "commercial_maturity_score",
    "followers",
    "avg_views",
    "engagement_rate",
    "geo_us_pct",
    "brand_deals_count",
    "audience_18_24_pct",
    "niche_relevance_pct",
    "last_post_days",
)

STATUS_KEEP = "Keep"
STATUS_DROP = "Drop"
STATUS_REFRESH = "NEEDS_REFRESH"
STATUS_REVIEW = "NEEDS_REVIEW"            # human judgement absent, never invented
STATUS_CALIBRATION = "NEEDS_CALIBRATION"  # instrument has no fitted bands yet

ROLE_AWARENESS = "Awareness"
ROLE_CREDIBILITY = "Credibility"
ROLE_CONVERSION = "Conversion"

# Step 5a, expressed against the 1-5 sub-scores (config.ROLE_THRESHOLD == 4.0).
ROLE_RULES = """
Audience >= 4 AND Content >= 4  -> Credibility
Audience >= 4 AND Content <  4  -> Awareness
Audience <  4 AND Content >= 4  -> Conversion
Audience <  4 AND Content <  4  -> stronger of the two dimensions (tie -> Awareness)
"""

DEMO_FORMATS = {"talking-head", "screen-record", "tutorial", "review", "explainer"}
SOFT_FORMATS = {"vlog", "lifestyle", "entertainment", "vlog/lifestyle"}


# ---------------------------------------------------------------------------
# Parsing helpers — permissive on shape, strict on absence
# ---------------------------------------------------------------------------
def _num(value: Any) -> float | None:
    """Parse a number, or return None. Never substitutes a default."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip().replace(",", "").replace("%", "").replace("$", "")
    if text == "" or text.lower() in {"na", "n/a", "none", "null", "unknown", "-"}:
        return None
    multiplier = 1.0
    if text and text[-1].lower() in {"k", "m"}:
        multiplier = 1_000.0 if text[-1].lower() == "k" else 1_000_000.0
        text = text[:-1]
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _bool(value: Any) -> bool:
    return _text(value).lower() in {"1", "true", "yes", "y"}


def _platforms(value: Any) -> list[str]:
    """'TikTok, YouTube' / ['tiktok'] -> ['tiktok', 'youtube']."""
    if isinstance(value, (list, tuple, set)):
        parts = [str(p) for p in value]
    else:
        parts = str(value or "").replace("|", ",").replace("/", ",").split(",")
    out = []
    for part in parts:
        slug = part.strip().lower().replace(" ", "")
        if slug in config.PLATFORM_SLUGS and slug not in out:
            out.append(slug)
    return out


def _pretty_platform(slug: str) -> str:
    return {
        "tiktok": "TikTok",
        "instagram": "Instagram",
        "youtube": "YouTube",
        "linkedin": "LinkedIn",
    }.get(slug, slug.title())


# ---------------------------------------------------------------------------
# Step 1 — lock the criteria set from the brief
# ---------------------------------------------------------------------------
def lock_criteria(brief: dict) -> dict:
    """Translate a campaign brief into the locked criteria set (Step 1)."""
    brief = {**config.DEFAULT_BRIEF, **(brief or {})}
    platforms = _platforms(brief.get("platforms")) or list(config.PLATFORM_SLUGS)
    band = _text(brief.get("follower_band")).lower() or "all"
    if band not in config.FOLLOWER_BANDS:
        band = "all"
    band_min, band_max = config.FOLLOWER_BANDS[band]

    size = int(_num(brief.get("shortlist_size")) or config.SHORTLIST_MAX)
    size = max(config.SHORTLIST_MIN, min(config.SHORTLIST_MAX, size))
    cpm = _num(brief.get("cpm")) or config.DEFAULT_CPM

    exclusions = [
        e.strip() for e in str(brief.get("exclusions") or "").split(",") if e.strip()
    ]

    return {
        "brand_name": _text(brief.get("brand_name")) or "the brand",
        "product_description": _text(brief.get("product_description")),
        "campaign_goal": _text(brief.get("campaign_goal")).lower() or "awareness",
        "target_audience": _text(brief.get("target_audience")),
        "platforms": platforms,
        "platforms_display": [_pretty_platform(p) for p in platforms],
        "cpm": cpm,
        "follower_band": band,
        "follower_band_min": band_min,
        "follower_band_max": band_max,
        "follower_band_display": _band_label(band, band_min, band_max),
        "shortlist_size": size,
        "exclusions": exclusions,
        "instruments": {
            p: {
                "metric": config.INSTRUMENTS[p]["metric"],
                "label": config.INSTRUMENTS[p]["label"],
                "calibration": config.INSTRUMENTS[p]["calibration"],
                "calibrated": bool(config.INSTRUMENTS[p]["bands"]),
            }
            for p in platforms
            if p in config.INSTRUMENTS
        },
        "category": _text(brief.get("category")) or "the product category",
        "deliverable_formats": tuple(
            brief.get("deliverable_formats") or config.DEFAULT_DELIVERABLE_FORMATS
        ),
        "readiness_roles": dict(config.READINESS_ROLES),
        "weights": dict(config.SCORING_WEIGHTS),
        "videos_per_creator": config.VIDEOS_PER_CREATOR,
        "sponsor_decay": config.SPONSOR_DECAY,
    }


def _band_label(band: str, low: int, high: int) -> str:
    if band == "all":
        return "All bands (50K-750K+)"
    return f"{band.title()} {low//1000}K-{high//1000}K"


# ---------------------------------------------------------------------------
# Step 4 — creator profile build
# ---------------------------------------------------------------------------
def load_creators(source: str | Iterable[dict]) -> list[dict]:
    """Load creators from a CSV path, a JSON path, raw CSV/JSON text, or a list."""
    if isinstance(source, (list, tuple)):
        return [normalise_creator(row) for row in source]

    text = str(source)
    if os.path.exists(text):
        with open(text, "r", encoding="utf-8") as fh:
            text = fh.read()

    stripped = text.lstrip()
    if stripped.startswith("[") or stripped.startswith("{"):
        data = json.loads(stripped)
        if isinstance(data, dict):
            data = data.get("creators", [])
        return [normalise_creator(row) for row in data]

    reader = csv.DictReader(io.StringIO(text))
    return [normalise_creator(row) for row in reader]


def normalise_creator(row: dict) -> dict:
    """Coerce a raw row into the creator schema without inventing values."""
    row = {str(k).strip().lower(): v for k, v in dict(row).items()}
    creator: dict[str, Any] = {
        "name": _text(row.get("name") or row.get("creator_name")),
        "handle": _text(row.get("handle")),
        "platform": _text(row.get("platform")),
        "platforms": _platforms(row.get("platform")),
        "cross_platform": _text(row.get("cross_platform")),
        "content_format": _text(row.get("content_format")).lower(),
        "comment_quality": _text(row.get("comment_quality")).lower(),
        "age_evidence": _text(row.get("age_evidence")).lower(),
        "geo_evidence": _text(row.get("geo_evidence")).lower(),
        "current_sponsors": _text(row.get("current_sponsors")),
        "notes": _text(row.get("notes")),
        "has_media_kit": _bool(row.get("has_media_kit")),
        "source": _text(row.get("source")).lower() or "manual",
        # Category Readiness drives the campaign role (Step 5a). It is judged
        # against a NAMED category, and the name travels with it — a readiness
        # call about "AI app-building tools" says nothing about a tablet.
        "readiness": _text(row.get("readiness")).lower().strip(),
        "readiness_category": _text(row.get("readiness_category")).strip(),
        # Non-scored publishing surfaces (newsletter, podcast) still matter to
        # the deliverable gate.
        "other_surfaces": _text(row.get("other_surfaces")),
        "location": _text(row.get("location")),
        "search_source": _text(row.get("search_source")),
        "sample_video": _text(row.get("sample_video")),
        "sheet_outreach_angle": _text(row.get("sheet_outreach_angle")),
        "sourced_from": _text(row.get("sourced_from")),
        "sourced_date": _text(row.get("sourced_date")),
        "followers_scope": _text(row.get("followers_scope")),
        "rate_reproducible": row.get("rate_reproducible"),
        "calibration_cohort": bool(row.get("calibration_cohort")),
    }
    for field in NUMERIC_FIELDS:
        creator[field] = _num(row.get(field))
    creator["platforms_display"] = [_pretty_platform(p) for p in creator["platforms"]]
    return creator


def missing_required(creator: dict) -> list[str]:
    """Which REQUIRED_FIELDS are absent. Drives the NEEDS_REFRESH flag."""
    gaps = []
    for field in REQUIRED_FIELDS:
        value = creator.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            gaps.append(field)
    if not creator.get("platforms"):
        gaps.append("platform")
    return sorted(set(gaps))


# ---------------------------------------------------------------------------
# Step 5 — the five dimensions
# ---------------------------------------------------------------------------
def _primary_platform(creator: dict, criteria: dict) -> str:
    """The scored platform: the creator's first platform that the brief targets."""
    for slug in creator.get("platforms", []):
        if slug in criteria["platforms"]:
            return slug
    # No briefed platform. Return the creator's own first, or "" — never
    # fall back to a default, which would score them on a surface they are
    # not on.
    return (creator.get("platforms") or [""])[0]


def _judged(creator: dict, field: str, dimension: str) -> tuple[float, list[str]] | None:
    """Use a human 1-5 score when one exists, converted to dimension points.

    Judged dimensions take human judgement as INPUT rather than reverse-engineering
    it from metrics. The evidence note records that it was judged, not derived, so
    a shortlist can always say which is which.
    """
    raw = creator.get(field)
    if raw is None:
        return None
    score = max(1.0, min(5.0, float(raw)))
    points = score / 5.0 * config.DIMENSION_POINTS[dimension]
    return points, [f"judged {score:g}/5"]


def score_audience_match(creator: dict) -> tuple[float, list[str]]:
    """Dimension 1 — age skew (15) + US geography (10), normalised to 30 pts.

    The skill's D1 sub-rubric sums to 25 while the dimension is worth 30; the
    components are scaled by 30/25 so the dimension's own ceiling is reachable.
    """
    judged = _judged(creator, "audience_match_score", "audience_match")
    if judged is not None:
        return judged

    notes = []
    age_pct = creator.get("audience_18_24_pct")
    evidence = creator.get("age_evidence")

    if age_pct is not None and age_pct < 30:
        age_pts = 0
        notes.append(f"18-24 share {age_pct:.0f}% — not 18-24 dominant")
    elif evidence in {"strong", "media_kit", "marketplace"}:
        age_pts = 15
        notes.append("age skew: strong evidence")
    elif evidence in {"moderate", "comments", "content"}:
        age_pts = 10
        notes.append("age skew: moderate evidence")
    elif evidence in {"weak", "inferred"}:
        age_pts = 5
        notes.append("age skew: weak/inferred only")
    else:
        age_pts = 0
        notes.append("age skew: no evidence")

    geo_pct = creator.get("geo_us_pct")
    geo_evidence = creator.get("geo_evidence")
    if geo_pct is None:
        geo_pts = 0
        notes.append("US share: no evidence")
    elif geo_pct > 50 and geo_evidence in {"hard", "media_kit", "marketplace"}:
        geo_pts = 10
        notes.append(f"US audience {geo_pct:.0f}% confirmed")
    elif geo_pct > 50:
        geo_pts = 7
        notes.append(f"US audience ~{geo_pct:.0f}% (soft signals)")
    elif geo_pct >= 40:
        geo_pts = 3
        notes.append(f"US audience {geo_pct:.0f}% — uncertain")
    else:
        geo_pts = 0
        notes.append(f"US audience {geo_pct:.0f}% — non-US dominant")

    points = (age_pts + geo_pts) * (config.DIMENSION_POINTS["audience_match"] / 25.0)
    return round(points, 2), notes


def score_content_match(creator: dict) -> tuple[float, list[str]]:
    """Dimension 2 — niche alignment (20) + format compatibility (5)."""
    judged = _judged(creator, "content_match_score", "content_match")
    if judged is not None:
        return judged

    notes = []
    niche = creator.get("niche_relevance_pct")
    if niche is None:
        niche_pts = 0
        notes.append("niche alignment: no evidence")
    elif niche > 50:
        niche_pts = 20
        notes.append(f"core niche ({niche:.0f}% relevant)")
    elif niche >= 25:
        niche_pts = 14
        notes.append(f"adjacent niche ({niche:.0f}% relevant)")
    elif niche > 0:
        niche_pts = 7
        notes.append(f"tangential ({niche:.0f}% relevant)")
    else:
        niche_pts = 0
        notes.append("niche mismatch")

    fmt = creator.get("content_format")
    if fmt in DEMO_FORMATS:
        fmt_pts = 5
        notes.append(f"{fmt} suits a tool demo")
    elif fmt in SOFT_FORMATS:
        fmt_pts = 2
        notes.append(f"{fmt} — harder to integrate")
    else:
        fmt_pts = 0
        notes.append("format unknown" if not fmt else f"{fmt} works against a demo")

    return float(niche_pts + fmt_pts), notes


def score_resonance(creator: dict, platform: str) -> tuple[float, list[str], str]:
    """Dimension 3 — Audience Resonance.

    One construct (does this audience show up?), measured by whichever
    instrument the platform supports. Returns (points_out_of_25, notes, state)
    where state is "" for a clean score, or a STATUS_* that blocks scoring.

    The raw rate is never comparable across instruments; only the normalised
    1-5 is. See config.INSTRUMENTS.
    """
    notes: list[str] = []
    instrument = config.INSTRUMENTS.get(platform)
    if instrument is None:
        return 0.0, [f"no instrument defined for {platform or 'unknown platform'}"], STATUS_REFRESH

    rate = creator.get("resonance_rate")
    if rate is None:
        rate = creator.get("engagement_rate")  # legacy field name
    if rate is None:
        return 0.0, ["resonance rate missing"], STATUS_REFRESH

    bands = instrument["bands"]
    if not bands:
        # Uncalibrated instrument (LinkedIn today). Refuse to score rather than
        # inventing a band boundary.
        return 0.0, [
            f"{instrument['label']} {rate:.1f}% on {_pretty_platform(platform)} — "
            f"{platform} bands not yet calibrated"
        ], STATUS_CALIBRATION

    score = 1
    for min_rate, band_score in bands:
        if rate >= min_rate:
            score = band_score
            break
    notes.append(
        f"{instrument['label']} {rate:.1f}% on {_pretty_platform(platform)} "
        f"-> {score}/5"
    )

    # Authenticity is a gate, and it is separate from the rate. A high rate on
    # inauthentic comments is worse than a low rate on real ones.
    quality = creator.get("comment_quality")
    if quality in {"inauthentic", "suspected", "bot"}:
        return 0.0, notes + ["comments suspected inauthentic"], STATUS_DROP
    if quality in {"generic", "emoji"}:
        score = max(score - config.GENERIC_COMMENT_PENALTY, 1.0)
        notes.append(f"generic comments (-{config.GENERIC_COMMENT_PENALTY})")

    # Flag when the creator spans instruments with different bands, so the
    # chosen one is visible rather than silent.
    spans = {config.INSTRUMENTS[p]["metric"] for p in creator.get("platforms", [])
             if p in config.INSTRUMENTS}
    if len(spans) > 1:
        notes.append("spans multiple instruments — scored on " + _pretty_platform(platform))

    return float(score) / 5.0 * config.DIMENSION_POINTS["engagement_score"], notes, ""


def score_geo(creator: dict) -> tuple[float, list[str]]:
    """Dimension 4 — strength of US confirmation, not presence of a US audience."""
    judged = _judged(creator, "geo_match_score", "geo_score")
    if judged is not None:
        return judged

    pct = creator.get("geo_us_pct")
    evidence = creator.get("geo_evidence")
    hard = evidence in {"hard", "media_kit", "marketplace"}
    if pct is None:
        return 0.0, ["no geo data"]
    if pct > 60 and hard:
        return 10.0, [f"{pct:.0f}% US confirmed"]
    if pct >= 50 and hard:
        return 7.0, [f"{pct:.0f}% US confirmed"]
    if pct > 50:
        return 4.0, [f"~{pct:.0f}% US estimated"]
    return 2.0, [f"{pct:.0f}% US — unconfirmed above 50%"]


def score_commercial_maturity(creator: dict) -> tuple[float, list[str]]:
    """Dimension 5 — can they execute a paid brief professionally?"""
    judged = _judged(creator, "commercial_maturity_score", "commercial_maturity")
    if judged is not None:
        return judged

    deals = creator.get("brand_deals_count")
    if deals is None:
        return 0.0, ["no brand-deal data"]
    if deals >= 3:
        return 10.0, [f"{int(deals)} prior paid partnerships"]
    if deals >= 1 or creator.get("has_media_kit"):
        return 6.0, [f"{int(deals)} partnership(s)" + (" + media kit" if creator.get("has_media_kit") else "")]
    if creator.get("has_media_kit"):
        return 3.0, ["media kit only"]
    return 0.0, ["no signal of prior brand work"]


def _to_five(points: float, dimension: str) -> float:
    """Convert a dimension's points to the 1-5 display scale."""
    return round(points / config.DIMENSION_POINTS[dimension] * 5.0, 2)


# ---------------------------------------------------------------------------
# Step 5a — campaign role
# ---------------------------------------------------------------------------
def assign_role(readiness: str) -> str | None:
    """Role from Category Readiness — never from D1/D2, never from the total.

    Readiness is the audience's relationship to the campaign's product
    category. D1xD2 was a lossy proxy for it: it measures who the audience is
    and what the creator makes, then infers adoption. On the hand-scored
    Craftly set that proxy mislabelled 7 of 18 creators, because a creator can
    score 5/4 on audience and content while their audience has never opened a
    tool in the category.

    Returns None when readiness has not been judged — the caller turns that
    into NEEDS_REVIEW rather than guessing a role.
    """
    return config.READINESS_ROLES.get(_text(readiness).lower().strip())


def tier_for(score_100: float) -> str:
    for floor, label in config.SCORE_TIERS:
        if score_100 >= floor:
            return label
    return config.SCORE_TIERS[-1][1]


OUTREACH_ANGLES = {
    ROLE_AWARENESS: "\"Here's an AI tool I wish I had during finals\" — relatability over technical depth; {brand} as the shortcut, not the subject.",
    ROLE_CREDIBILITY: "\"I built this with {brand} — here's exactly how it works\" — full demo, honest review, technical depth welcome.",
    ROLE_CONVERSION: "\"{brand} is the fastest way to go from idea to working app\" — product-led, comparison framing, speed and simplicity.",
}


def outreach_angle(role: str, criteria: dict) -> str:
    return OUTREACH_ANGLES[role].format(brand=criteria.get("brand_name", "the brand"))


# ---------------------------------------------------------------------------
# CPM
# ---------------------------------------------------------------------------
def cpm_estimate(creator: dict, criteria: dict) -> dict:
    """Budget from views, never followers (Hard Rule)."""
    views = creator.get("avg_views")
    if views is None:
        return {"expected_views": None, "budget": None, "total_reach": None}
    expected = views * criteria["sponsor_decay"]
    videos = criteria["videos_per_creator"]
    budget = expected * videos / 1000.0 * criteria["cpm"]
    return {
        "expected_views": round(expected),
        "budget": round(budget, 2),
        "total_reach": round(expected * videos),
    }


# ---------------------------------------------------------------------------
# Step 5 entry point
# ---------------------------------------------------------------------------
def _unscored(creator, criteria, status, reason, notes=None) -> dict:
    """The shape of a creator the engine refuses to score. Never invents."""
    return {
        "audience_match": None,
        "content_match": None,
        "engagement_score": None,
        "geo_score": None,
        "commercial_maturity": None,
        "weighted_score": None,
        "score_100": None,
        "tier": "Unscored",
        "role": None,
        "role_colour": "",
        "readiness": _text(creator.get("readiness")).lower().strip(),
        "outreach_angle": "Resolve the gap before outreach.",
        "status": status,
        "status_reason": reason,
        "evidence": list(notes or []),
        "cpm": cpm_estimate(creator, criteria),
        "eligible": False,
    }


def score_creator(creator: dict, criteria: dict) -> dict:
    """Score one creator. Returns the full auditable breakdown."""
    result = dict(creator)
    gaps = missing_required(creator)
    platform = _primary_platform(creator, criteria)
    result["primary_platform"] = _pretty_platform(platform)

    deliverable_ok, deliverable_reason = can_deliver(creator, criteria)
    if not deliverable_ok:
        result.update(_unscored(creator, criteria, STATUS_DROP, deliverable_reason))
        return result

    if gaps:
        # Never score on invented data.
        result.update(
            {
                "audience_match": None,
                "content_match": None,
                "engagement_score": None,
                "geo_score": None,
                "commercial_maturity": None,
                "weighted_score": None,
                "score_100": None,
                "tier": "Unscored",
                "role": None,
                "role_colour": "",
                "outreach_angle": "Refresh metrics before outreach.",
                "status": STATUS_REFRESH,
                "status_reason": "Missing: " + ", ".join(gaps),
                "missing_fields": gaps,
                "evidence": [],
                "cpm": {"expected_views": None, "budget": None, "total_reach": None},
                "eligible": False,
            }
        )
        return result

    d1_pts, d1_notes = score_audience_match(creator)
    d2_pts, d2_notes = score_content_match(creator)
    d3_pts, d3_notes, d3_state = score_resonance(creator, platform)
    eligible = d3_state != STATUS_DROP
    d4_pts, d4_notes = score_geo(creator)
    d5_pts, d5_notes = score_commercial_maturity(creator)

    if d3_state == STATUS_DROP:
        result.update(_unscored(
            creator, criteria, STATUS_DROP, "; ".join(d3_notes), notes=d3_notes
        ))
        return result

    if d3_state in {STATUS_REFRESH, STATUS_CALIBRATION}:
        result.update(_unscored(
            creator, criteria, d3_state, "; ".join(d3_notes), notes=d3_notes
        ))
        return result

    unjudged = [f for f in JUDGED_FIELDS if creator.get(f) is None]
    if unjudged:
        result.update(_unscored(
            creator, criteria, STATUS_REVIEW,
            "not yet judged: " + ", ".join(f.replace("_score", "") for f in unjudged),
            notes=d3_notes,
        ))
        return result

    readiness = _text(creator.get("readiness")).lower().strip()

    # Readiness is category-relative. Reusing a judgement made against one
    # category for another campaign is inventing judgement — the same rule that
    # forbids inventing metrics. A row whose readiness was judged against a
    # different category is NEEDS_REVIEW, not a guessed role.
    judged_against = _text(creator.get("readiness_category")).strip()
    brief_category = _text(criteria.get("category")).strip()
    if readiness and judged_against and brief_category and (
        judged_against.lower() != brief_category.lower()
    ):
        result.update(_unscored(
            creator, criteria, STATUS_REVIEW,
            f"readiness was judged against “{judged_against}”; this brief "
            f"scores against “{brief_category}” — re-judge before use",
            notes=d3_notes,
        ))
        # Machine-readable, so callers can explain an empty roster without
        # parsing the reason string.
        result["readiness_mismatch"] = judged_against
        return result

    role = assign_role(readiness)
    if role is None:
        # Readiness is a human judgement. Absent, the creator is not given a
        # guessed role — the same rule that governs missing metrics.
        result.update(_unscored(
            creator, criteria, STATUS_REVIEW,
            "category readiness not judged", notes=d3_notes,
        ))
        return result

    audience_match = _to_five(d1_pts, "audience_match")
    content_match = _to_five(d2_pts, "content_match")
    engagement_score = _to_five(d3_pts, "engagement_score")
    geo_score = _to_five(d4_pts, "geo_score")
    commercial_maturity = _to_five(d5_pts, "commercial_maturity")

    # THE FORMULA — locked, see CLAUDE.md.
    weighted_score = (
        (audience_match * 0.30)
        + (content_match * 0.25)
        + (engagement_score * 0.25)
        + (geo_score * 0.10)
        + (commercial_maturity * 0.10)
    )
    weighted_score = round(weighted_score, 3)
    score_100 = round(weighted_score * 20, 1)

    status, reason = _status_for(creator, criteria, eligible, score_100, d3_notes)

    result.update(
        {
            "audience_match": audience_match,
            "content_match": content_match,
            "engagement_score": engagement_score,
            "geo_score": geo_score,
            "commercial_maturity": commercial_maturity,
            "points": {
                "audience_match": d1_pts,
                "content_match": d2_pts,
                "engagement_score": d3_pts,
                "geo_score": d4_pts,
                "commercial_maturity": d5_pts,
            },
            "weighted_score": weighted_score,
            "score_100": score_100,
            "tier": tier_for(score_100),
            "role": role,
            "role_colour": config.ROLE_COLOURS.get(role, ""),
            "readiness": readiness,
            "outreach_angle": outreach_angle(role, criteria),
            "status": status,
            "status_reason": reason,
            "missing_fields": [],
            "evidence": d1_notes + d2_notes + d3_notes + d4_notes + d5_notes,
            "cpm": cpm_estimate(creator, criteria),
            "eligible": eligible,
        }
    )
    return result


def can_deliver(creator: dict, criteria: dict) -> tuple[bool, str]:
    """Step 3 gate — can this creator physically produce the deliverable?

    A gate, not a low score. A newsletter cannot shoot a video: it is not a
    weak candidate for a video campaign, it is not a candidate at all. On the
    Craftly set this is what should have excluded No-Code Exits (a newsletter)
    before it was ever scored 3.0 and ranked.
    """
    wanted = set(criteria.get("deliverable_formats") or ())
    if not wanted:
        return True, ""
    capable: set[str] = set()
    for slug in creator.get("platforms") or []:
        capable |= config.FORMAT_CAPABILITIES.get(slug, set())
    raw = str(creator.get("other_surfaces") or "")
    for token in raw.replace("|", ",").replace("/", ",").split(","):
        slug = token.strip().lower().replace(" ", "")
        capable |= config.FORMAT_CAPABILITIES.get(slug, set())
    if capable & wanted:
        return True, ""
    have = ", ".join(sorted(capable)) or "no known publishing surface"
    return False, (
        f"cannot produce the deliverable ({'/'.join(sorted(wanted))}) — {have}"
    )


def _status_for(creator, criteria, eligible, score_100, engagement_notes) -> tuple[str, str]:
    """Keep / Drop, with the reason named rather than buried."""
    if not eligible:
        return STATUS_DROP, "; ".join(engagement_notes) or "below engagement floor"

    deliverable_ok, deliverable_reason = can_deliver(creator, criteria)
    if not deliverable_ok:
        return STATUS_DROP, deliverable_reason

    exclusions = [e.lower() for e in criteria.get("exclusions", [])]
    haystack = " ".join(
        [creator.get("current_sponsors", ""), creator.get("notes", "")]
    ).lower()
    for term in exclusions:
        if term and term in haystack:
            return STATUS_DROP, f"excluded: competitor sponsorship ({term})"

    if not any(p in criteria["platforms"] for p in creator.get("platforms", [])):
        return STATUS_DROP, "not active on a briefed platform"

    followers = creator.get("followers")
    low, high = criteria["follower_band_min"], criteria["follower_band_max"]
    if followers is not None and criteria["follower_band"] != "all":
        if followers < low or followers > high:
            return STATUS_DROP, (
                f"{followers/1000:.0f}K outside the "
                f"{criteria['follower_band_display']} band"
            )

    if score_100 < 35:
        return STATUS_DROP, f"scored {score_100:.0f}/100 — below Tier 3"

    return STATUS_KEEP, ""


# ---------------------------------------------------------------------------
# Step 6 — shortlist assembly
# ---------------------------------------------------------------------------
def build_shortlist(brief: dict, creators: str | Iterable[dict]) -> dict:
    """Full pipeline: brief + creators -> ranked, tiered, role-assigned shortlist."""
    criteria = lock_criteria(brief)
    rows = load_creators(creators) if not isinstance(creators, list) or (
        creators and not isinstance(creators[0], dict)
    ) else [normalise_creator(c) for c in creators]

    if config.ENRICHMENT_ENABLED:
        import enricher

        rows = [enricher.apply_enrichment(row) for row in rows]

    scored = [score_creator(row, criteria) for row in rows]

    keep = [c for c in scored if c["status"] == STATUS_KEEP]
    dropped = [c for c in scored if c["status"] == STATUS_DROP]
    refresh = [c for c in scored if c["status"] == STATUS_REFRESH]
    review = [c for c in scored if c["status"] == STATUS_REVIEW]
    calibration = [c for c in scored if c["status"] == STATUS_CALIBRATION]

    keep.sort(key=lambda c: c["weighted_score"], reverse=True)
    shortlist = keep[: criteria["shortlist_size"]]
    overflow = keep[criteria["shortlist_size"] :]
    for i, creator in enumerate(shortlist, start=1):
        creator["rank"] = i

    # NEEDS_REFRESH rows stay visible — an honest gap beats an invented number.
    table = shortlist + overflow + review + calibration + refresh + dropped
    assert len(table) == len(scored), "a creator fell out of the table"

    # Rows held back because their readiness was judged against another
    # category. This is the most common reason a roster comes back empty, and
    # an empty roster with no explanation reads as a broken run.
    mismatched = [c for c in review if c.get("readiness_mismatch")]

    return {
        "criteria": criteria,
        "shortlist": shortlist,
        "table": table,
        "needs_refresh": refresh,
        "needs_review": review,
        "readiness_mismatch": mismatched,
        "judged_categories": sorted({c["readiness_mismatch"] for c in mismatched}),
        "needs_calibration": calibration,
        "dropped": dropped,
        "composition": composition_summary(shortlist, criteria),
        "counts": {
            "evaluated": len(scored),
            "shortlisted": len(shortlist),
            "needs_refresh": len(refresh),
            "needs_review": len(review),
            "needs_calibration": len(calibration),
            "dropped": len(dropped),
        },
    }


def composition_summary(shortlist: list[dict], criteria: dict) -> dict:
    """Campaign composition panel — role counts, reach, budget."""
    roles = {ROLE_AWARENESS: [], ROLE_CREDIBILITY: [], ROLE_CONVERSION: []}
    for creator in shortlist:
        roles.setdefault(creator["role"], []).append(creator)

    by_role = {}
    for role, members in roles.items():
        reach = sum((m["cpm"]["total_reach"] or 0) for m in members)
        budget = sum((m["cpm"]["budget"] or 0) for m in members)
        low, high = config.COMPOSITION_TARGET[role]
        by_role[role] = {
            "count": len(members),
            "reach": reach,
            "budget": round(budget, 2),
            "target": f"{low}-{high}",
            "on_target": low <= len(members) <= high,
            "colour": config.ROLE_COLOURS[role],
        }

    total_reach = sum(r["reach"] for r in by_role.values())
    total_budget = sum(r["budget"] for r in by_role.values())
    credibility = by_role[ROLE_CREDIBILITY]["count"]
    gap_note = (
        f"Only {credibility} Credibility anchor(s) in this pool. The student-AI gap is "
        "structural — creators with a student-skewed audience rarely post AI/builder "
        "content. Reported as found rather than rebalanced by forcing roles."
        if credibility < config.COMPOSITION_TARGET[ROLE_CREDIBILITY][0]
        else f"{credibility} Credibility anchors available — the student-AI gap did not "
        "bind on this pool."
    )

    return {
        "by_role": by_role,
        "total_reach": total_reach,
        "total_budget": round(total_budget, 2),
        "cpm": criteria["cpm"],
        "videos": criteria["videos_per_creator"] * len(shortlist),
        "student_ai_gap_note": gap_note,
    }


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------
EXPORT_COLUMNS = [
    ("rank", "Rank"),
    ("name", "Creator Name"),
    ("platforms_csv", "Platform(s)"),
    ("followers", "Followers"),
    ("engagement_rate", "Engagement Rate (%)"),
    ("audience_match", "Audience Match (1-5)"),
    ("content_match", "Content Match (1-5)"),
    ("engagement_score", "Engagement Score (1-5)"),
    ("geo_score", "Geo Match (1-5)"),
    ("commercial_maturity", "Commercial Maturity (1-5)"),
    ("weighted_score", "Weighted Score"),
    ("score_100", "Score /100"),
    ("tier", "Tier"),
    ("role", "Campaign Role"),
    ("outreach_angle", "Outreach Angle"),
    ("status", "Status"),
    ("status_reason", "Status Reason"),
    ("budget", "Budget Estimate ($)"),
    ("expected_views", "Expected Views/Video"),
    ("source", "Metrics Source"),
]


def to_csv(result: dict) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([label for _, label in EXPORT_COLUMNS])
    for creator in result["table"]:
        row = []
        for key, _ in EXPORT_COLUMNS:
            if key == "platforms_csv":
                row.append(" / ".join(creator.get("platforms_display", [])))
            elif key in {"budget", "expected_views"}:
                row.append(creator.get("cpm", {}).get(key) or "")
            else:
                value = creator.get(key)
                row.append("" if value is None else value)
        writer.writerow(row)
    return out.getvalue()
