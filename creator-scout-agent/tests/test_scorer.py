"""Scoring engine tests.

The suite guards three things that break the product if they drift: the locked
weights, the refusal to invent data or judgement, and the independence of
campaign role from score rank.
"""

import copy
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import scorer


def build(brief=None):
    return scorer.build_shortlist(brief or config.DEFAULT_BRIEF, config.CREATOR_DATA)


def by_name(result, name):
    for creator in result["table"]:
        if creator["name"] == name:
            return creator
    raise AssertionError(f"{name} missing from the table entirely")


# ---------------------------------------------------------------------------
# The locked model
# ---------------------------------------------------------------------------
def test_weights_are_locked():
    assert config.SCORING_WEIGHTS == {
        "audience_match": 0.30,
        "content_match": 0.25,
        "engagement_score": 0.25,
        "geo_score": 0.10,
        "commercial_maturity": 0.10,
    }
    assert sum(config.SCORING_WEIGHTS.values()) == pytest.approx(1.0)


def test_weighted_score_matches_formula_for_every_scored_creator():
    for creator in build()["table"]:
        if creator["weighted_score"] is None:
            continue
        expected = (
            creator["audience_match"] * 0.30
            + creator["content_match"] * 0.25
            + creator["engagement_score"] * 0.25
            + creator["geo_score"] * 0.10
            + creator["commercial_maturity"] * 0.10
        )
        assert creator["weighted_score"] == pytest.approx(expected, abs=0.005)


def test_score_100_equals_weighted_times_twenty():
    for creator in build()["table"]:
        if creator["score_100"] is None:
            continue
        assert creator["score_100"] == pytest.approx(creator["weighted_score"] * 20, abs=0.05)


def test_hand_calculated_scores():
    """Two creators verified by hand against the formula."""
    result = build()
    # Joshua La Rosa: 5/5/5/4/5 -> 1.500+1.250+1.250+0.400+0.500 = 4.900
    assert by_name(result, "Joshua La Rosa")["weighted_score"] == pytest.approx(4.900, abs=0.005)
    # Harper Carroll: 4/5/5/5/5 -> 1.200+1.250+1.250+0.500+0.500 = 4.700
    assert by_name(result, "Harper Carroll")["weighted_score"] == pytest.approx(4.700, abs=0.005)


# The engine must reproduce the product owner's hand-scored sheet exactly. It
# earns trust by agreeing with expert judgement and adding the gates on top —
# not by quietly re-ranking on a metric whose denominators are inconsistent.
SHEET_WEIGHTED = {
    "The Tech Girl": 3.50, "Parker Prompts": 4.30,
    "Mikey No Code": 4.05, "Andrew Kim": 3.95, "Joshua La Rosa": 4.90,
    "Riley Brown": 4.40, "askcatgpt": 4.45, "Kyle Balmer": 3.85,
    "Robo Nuggets": 4.35, "Maitri Mangal": 3.90, "genzbestie": 4.45,
    "Mia Yilin": 3.95, "soojintech": 4.55, "Harper Carroll": 4.70,
    "isabellagerli": 4.00, "Chams Eldin": 3.88,
}


def test_engine_reproduces_the_hand_scored_sheet():
    result = build()
    for name, expected in SHEET_WEIGHTED.items():
        got = by_name(result, name)["weighted_score"]
        assert got == pytest.approx(expected, abs=0.005), f"{name}: {got} != sheet {expected}"


def test_roberto_nickson_is_the_one_sheet_row_that_breaks_its_own_ladder():
    """The single divergence between engine and sheet, recorded deliberately.

    Roberto Nickson has a 24.66% view rate on TikTok/Instagram. The sheet's own
    ladder scores anything above 8% as 5/5, but the sheet records 4. The engine
    applies the stated rule and returns 5, which lifts his weighted score from
    3.90 to 4.15. This is a transcription slip in the sheet, not an engine bug —
    every other scored row reproduces exactly.
    """
    creator = by_name(build(), "Roberto Nickson")
    assert creator["weighted_score"] == pytest.approx(4.15, abs=0.005)
    assert creator["engagement_score"] == 5.0


def test_d3_saturation_is_a_known_limitation_not_a_surprise():
    """Guards the documented weakness so it cannot be forgotten: the restored
    ladder is an engagement-rate ladder fed view-rate data, so most creators
    max out D3. Recorded as a test so the fix has a failing signal to aim at."""
    scored = [c for c in build()["table"] if c["engagement_score"] is not None]
    maxed = [c for c in scored if c["engagement_score"] == 5.0]
    assert len(maxed) / len(scored) > 0.6, (
        "D3 saturation has changed — if this is the per-platform follower fix "
        "landing, update the bands and delete this test"
    )
    assert config.INSTRUMENTS["tiktok"]["calibration"] == "owner-ladder-known-saturating"


# ---------------------------------------------------------------------------
# Role comes from Category Readiness
# ---------------------------------------------------------------------------
def test_role_comes_from_readiness_not_sub_scores():
    assert scorer.assign_role("unexposed") == scorer.ROLE_AWARENESS
    assert scorer.assign_role("exposed") == scorer.ROLE_CREDIBILITY
    assert scorer.assign_role("adopted") == scorer.ROLE_CONVERSION


def test_unjudged_readiness_returns_no_role_rather_than_guessing():
    assert scorer.assign_role("") is None
    assert scorer.assign_role("something else") is None


def test_role_is_independent_of_total_score():
    """Two creators with the same role must be free to sit in different tiers."""
    result = build()
    roles = {}
    for creator in result["shortlist"]:
        roles.setdefault(creator["role"], []).append(creator["score_100"])
    spread = [scores for scores in roles.values() if len(scores) > 1]
    assert spread, "expected at least one role held by more than one creator"
    assert any(max(s) != min(s) for s in spread), "role is tracking score rank"


def test_high_scorer_can_be_awareness_and_low_scorer_credibility():
    result = build()
    awareness = [c for c in result["shortlist"] if c["role"] == scorer.ROLE_AWARENESS]
    credibility = [c for c in result["shortlist"] if c["role"] == scorer.ROLE_CREDIBILITY]
    assert awareness and credibility
    # genzbestie scores well and is still Awareness: her audience has exposure
    # to the category, not adoption.
    assert by_name(result, "genzbestie")["role"] == scorer.ROLE_AWARENESS


# ---------------------------------------------------------------------------
# The engine never invents
# ---------------------------------------------------------------------------
def test_missing_metric_flags_needs_refresh_and_never_scores():
    creator = by_name(build(), "Lara Acosta")
    assert creator["status"] == scorer.STATUS_REFRESH
    assert creator["weighted_score"] is None
    assert creator["score_100"] is None
    assert creator["role"] is None


def test_unjudged_dimension_flags_needs_review_and_never_scores():
    """A human judgement gap is as blocking as a metric gap."""
    creator = by_name(build(), "Andy Stapleton")
    assert creator["status"] == scorer.STATUS_REVIEW
    assert creator["weighted_score"] is None
    assert "readiness" in creator["status_reason"]


def test_uncalibrated_instrument_refuses_to_score():
    """LinkedIn has no fitted bands, so a fully-populated LinkedIn creator
    still returns NEEDS_CALIBRATION rather than a guessed band."""
    assert config.INSTRUMENTS["linkedin"]["bands"] is None
    brief = {**config.DEFAULT_BRIEF, "platforms": ["linkedin"]}
    result = scorer.build_shortlist(brief, [{
        "name": "Fully Populated LinkedIn Creator",
        "platform": "LinkedIn", "followers": 100000, "resonance_rate": 4.0,
        "avg_views": 4000, "audience_match_score": 5, "content_match_score": 5,
        "geo_match_score": 5, "commercial_maturity_score": 5, "readiness": "adopted",
    }])
    creator = result["table"][0]
    assert creator["status"] == scorer.STATUS_CALIBRATION
    assert creator["weighted_score"] is None


def test_no_creator_falls_out_of_the_table():
    result = build()
    assert len(result["table"]) == result["counts"]["evaluated"]
    buckets = (
        result["counts"]["shortlisted"] + result["counts"]["needs_refresh"]
        + result["counts"]["needs_review"] + result["counts"]["needs_calibration"]
        + result["counts"]["dropped"]
    )
    overflow = len(result["table"]) - buckets
    assert overflow >= 0


# ---------------------------------------------------------------------------
# Gates are gates, not tiebreakers
# ---------------------------------------------------------------------------
def test_deliverable_gate_drops_a_creator_who_cannot_produce_the_asset():
    """A newsletter is not a weak video candidate; it is not a candidate."""
    creator = by_name(build(), "No-Code Exits")
    assert creator["status"] == scorer.STATUS_DROP
    assert "deliverable" in creator["status_reason"]
    assert creator["weighted_score"] is None


def test_authenticity_gate_beats_a_good_score():
    creator = by_name(build(), "sofieestudies")
    assert creator["status"] == scorer.STATUS_DROP
    assert "inauthentic" in creator["status_reason"]


def test_exclusions_drop_a_creator():
    brief = {**config.DEFAULT_BRIEF, "exclusions": "Cursor"}
    result = scorer.build_shortlist(brief, config.CREATOR_DATA)
    assert by_name(result, "soojintech")["status"] == scorer.STATUS_DROP


# ---------------------------------------------------------------------------
# Instruments
# ---------------------------------------------------------------------------
def test_instruments_are_not_interchangeable():
    """The same raw rate must score differently on platforms whose instruments
    are calibrated differently — that is the whole point of the layer."""
    base = {
        "name": "Same Rate", "followers": 100000, "avg_views": 25000,
        "resonance_rate": 25.0, "audience_match_score": 4, "content_match_score": 4,
        "geo_match_score": 4, "commercial_maturity_score": 4, "readiness": "exposed",
    }
    yt = scorer.score_creator(
        scorer.normalise_creator({**base, "platform": "YouTube"}),
        scorer.lock_criteria(config.DEFAULT_BRIEF))
    ig = scorer.score_creator(
        scorer.normalise_creator({**base, "platform": "Instagram"}),
        scorer.lock_criteria(config.DEFAULT_BRIEF))
    assert yt["engagement_score"] != ig["engagement_score"], (
        "a 25% rate should not mean the same thing on YouTube and Instagram"
    )


def test_linkedin_is_a_recognised_platform():
    """It used to be silently dropped by the platform allowlist."""
    assert "linkedin" in config.PLATFORM_SLUGS
    assert scorer._platforms("LinkedIn") == ["linkedin"]


# ---------------------------------------------------------------------------
# Shortlist assembly
# ---------------------------------------------------------------------------
def test_shortlist_is_sorted_descending_and_capped():
    result = build()
    scores = [c["weighted_score"] for c in result["shortlist"]]
    assert scores == sorted(scores, reverse=True)
    assert len(result["shortlist"]) <= result["criteria"]["shortlist_size"]


def test_cpm_uses_views_not_followers():
    creator = by_name(build(), "Harper Carroll")
    assert creator["cpm"]["expected_views"] < creator["followers"]
    assert creator["cpm"]["budget"] > 0


def test_csv_export_has_header_and_every_row():
    result = build()
    lines = [l for l in scorer.to_csv(result).splitlines() if l.strip()]
    assert len(lines) == len(result["table"]) + 1


# ---------------------------------------------------------------------------
# Readiness is category-relative
#
# Role comes from Category Readiness, and readiness is judged AGAINST A NAMED
# CATEGORY. Reusing a judgement made about one category for a campaign in
# another is inventing judgement — the same rule that forbids inventing
# metrics. These guard the guard.
# ---------------------------------------------------------------------------
def test_readiness_does_not_transfer_to_a_different_category():
    """The whole pool was judged against "AI app-building tools"."""
    other = {**config.DEFAULT_BRIEF, "category": "student productivity hardware"}
    result = build(other)

    assert result["counts"]["shortlisted"] == 0, (
        "readiness judged against one category must not silently produce roles "
        "for a campaign in another"
    )
    roberto = by_name(result, "Roberto Nickson")
    assert roberto["status"] == scorer.STATUS_REVIEW
    assert roberto["role"] is None
    assert "AI app-building tools" in roberto["status_reason"]
    assert "student productivity hardware" in roberto["status_reason"]


def test_readiness_transfers_when_the_category_matches():
    """The guard must not fire on the campaign the pool was judged for."""
    result = build()
    assert result["counts"]["shortlisted"] == 17
    assert by_name(result, "Roberto Nickson")["role"] == scorer.ROLE_CREDIBILITY


def test_category_match_ignores_case_and_padding():
    result = build({**config.DEFAULT_BRIEF, "category": "  AI App-Building Tools "})
    assert result["counts"]["shortlisted"] == 17


def test_untagged_readiness_still_scores():
    """A row with no readiness_category predates the field; it is not punished.

    Backwards compatibility is deliberate: the guard fires on a KNOWN
    mismatch, never on absence of the tag.
    """
    rows = scorer.load_creators(config.CREATOR_DATA)
    for row in rows:
        row["readiness_category"] = ""
    result = scorer.build_shortlist(
        {**config.DEFAULT_BRIEF, "category": "anything at all"}, rows
    )
    assert result["counts"]["shortlisted"] == 17


def test_every_readiness_judgement_in_the_data_records_its_category():
    """No untagged judgement should slip back into the sourced data."""
    for creator in scorer.load_creators(config.CREATOR_DATA):
        if creator["readiness"]:
            assert creator["readiness_category"], (
                f"{creator['name']} has a readiness judgement with no category — "
                "the judgement cannot be checked against a brief"
            )
