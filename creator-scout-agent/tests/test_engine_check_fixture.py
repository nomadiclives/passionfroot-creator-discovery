"""The engine-check fixture must keep behaving as data/fixtures/README.md says.

The fixture is how an operator confirms the engine is sound before trusting a
shortlist for a new brand. If the documented outcomes and the engine drift apart,
the fixture stops being evidence and becomes decoration — so the table in that
README is pinned here.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import scorer

FIXTURE = os.path.join(config.DATA_DIR, "fixtures", "engine_check.csv")


@pytest.fixture(scope="module")
def rows():
    result = scorer.build_shortlist(config.DEFAULT_BRIEF, FIXTURE)
    return {c["name"]: c for c in result["table"]}


def test_fixture_exists_and_is_all_synthetic(rows):
    assert len(rows) == 13
    for creator in rows.values():
        assert creator["source"] == "fixture", "a fixture row must never look real"


def test_perfect_row_scores_exactly_five(rows):
    row = rows["01 Perfect Score"]
    assert row["status"] == scorer.STATUS_KEEP
    assert row["weighted_score"] == 5.00


def test_missing_required_metrics_refuse_to_score(rows):
    for name, field in (
        ("03 Missing Followers", "followers"),
        ("04 Missing Rate", "resonance_rate"),
    ):
        row = rows[name]
        assert row["status"] == scorer.STATUS_REFRESH
        assert field in row["missing_fields"]
        assert row["weighted_score"] is None


def test_unjudged_and_miscategorised_readiness_go_to_review(rows):
    assert rows["05 No Readiness"]["status"] == scorer.STATUS_REVIEW
    wrong = rows["06 Wrong Category"]
    assert wrong["status"] == scorer.STATUS_REVIEW
    assert "Fintech apps" in wrong["status_reason"]


def test_role_comes_from_readiness_not_rank(rows):
    """Three identical rows, three different roles, one identical score."""
    expected = {
        "07 Unexposed Role": "Awareness",
        "08 Exposed Role": "Credibility",
        "09 Adopted Role": "Conversion",
    }
    scores = set()
    for name, role in expected.items():
        assert rows[name]["role"] == role
        scores.add(rows[name]["weighted_score"])
    assert len(scores) == 1, "the three rows must score identically"


def test_a_read_exclusivity_clause_drops_but_a_rival_sponsor_does_not(rows):
    locked = rows["10 Locked By Clause"]
    assert locked["status"] == scorer.STATUS_DROP
    assert "exclusivity" in locked["status_reason"].lower()

    rival = rows["11 Rival Sponsor No Clause"]
    assert rival["status"] == scorer.STATUS_KEEP, (
        "working with a rival is a qualified lead, not a disqualification"
    )


def test_uncalibrated_platform_refuses_a_band(rows):
    assert rows["12 Uncalibrated Platform"]["status"] == scorer.STATUS_CALIBRATION


def test_below_tier_floor_is_dropped(rows):
    weak = rows["13 Weak All Round"]
    assert weak["status"] == scorer.STATUS_DROP
    assert "below Tier 3" in weak["status_reason"]


def test_no_resonance_eligibility_gate_currently_fires(rows):
    """Pins a known gap so it cannot be forgotten or silently changed.

    The spec calls the engagement rate a gate: below the floor is ineligible
    regardless of other dimensions. No instrument defines a floor today, because
    the spec's floors are engagement-rate numbers and the instrument measures view
    rate — a different construct. The consequence is real and belongs on the
    record: a creator at 0.4% view rate is still shortlisted on the strength of
    four human judgement calls.

    If a view-rate floor is ever fitted, this test should fail and be rewritten.
    """
    assert all(i.get("floor") is None for i in config.INSTRUMENTS.values())
    floor_case = rows["02 Floor Case"]
    assert floor_case["status"] == scorer.STATUS_KEEP
    assert floor_case["engagement_score"] == 1.0, "resonance should bottom out at 1/5"
    assert floor_case["weighted_score"] == 4.00
