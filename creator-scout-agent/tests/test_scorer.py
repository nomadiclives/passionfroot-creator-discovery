"""Tests for the scoring engine. The formula and role logic are contract, not detail."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import scorer


def build():
    return scorer.build_shortlist(config.DEFAULT_BRIEF, config.CREATOR_CSV)


def by_name(result, name):
    return next(c for c in result["table"] if c["name"] == name)


def test_weights_are_locked():
    assert config.SCORING_WEIGHTS == {
        "audience_match": 0.30,
        "content_match": 0.25,
        "engagement_score": 0.25,
        "geo_score": 0.10,
        "commercial_maturity": 0.10,
    }
    assert sum(config.SCORING_WEIGHTS.values()) == 1.0


def test_weighted_score_matches_formula_for_every_scored_creator():
    for creator in build()["table"]:
        if creator["weighted_score"] is None:
            continue
        expected = (
            (creator["audience_match"] * 0.30)
            + (creator["content_match"] * 0.25)
            + (creator["engagement_score"] * 0.25)
            + (creator["geo_score"] * 0.10)
            + (creator["commercial_maturity"] * 0.10)
        )
        assert round(expected, 3) == creator["weighted_score"], creator["name"]


def test_hand_calculated_scores():
    """Three creators verified by hand against the formula."""
    result = build()
    # Harper Carroll: 5.00, 5.00, 3.80, 5.00, 5.00
    #   1.500 + 1.250 + 0.950 + 0.500 + 0.500 = 4.700
    assert by_name(result, "Harper Carroll")["weighted_score"] == 4.700
    # askcatgpt: 5.00, 5.00, 5.00, 3.50, 3.00
    #   1.500 + 1.250 + 1.250 + 0.350 + 0.300 = 4.650
    assert by_name(result, "askcatgpt")["weighted_score"] == 4.650
    # Riley Brown: 3.00, 5.00, 3.80, 5.00, 5.00
    #   0.900 + 1.250 + 0.950 + 0.500 + 0.500 = 4.100
    assert by_name(result, "Riley Brown")["weighted_score"] == 4.100


def test_score_100_equals_weighted_times_twenty():
    """The 1-5 model and the skill's /100 rubric are the same model."""
    for creator in build()["table"]:
        if creator["weighted_score"] is None:
            continue
        assert creator["score_100"] == round(creator["weighted_score"] * 20, 1)
        assert abs(sum(creator["points"].values()) - creator["score_100"]) < 0.05


def test_role_assignment_follows_d1_d2_relationship():
    assert scorer.assign_role(4.5, 4.5) == scorer.ROLE_CREDIBILITY
    assert scorer.assign_role(4.0, 4.0) == scorer.ROLE_CREDIBILITY
    assert scorer.assign_role(4.5, 3.9) == scorer.ROLE_AWARENESS
    assert scorer.assign_role(3.9, 4.5) == scorer.ROLE_CONVERSION
    # Neither clears: falls to the stronger dimension, never to Credibility.
    assert scorer.assign_role(2.6, 1.8) == scorer.ROLE_AWARENESS
    assert scorer.assign_role(1.8, 2.6) == scorer.ROLE_CONVERSION


def test_role_is_independent_of_total_score():
    """A top-scoring creator can be Awareness; role never reads the total."""
    result = build()
    top = result["shortlist"][0]
    high_awareness = [c for c in result["shortlist"] if c["role"] == "Awareness"]
    assert top["role"] == "Credibility"
    assert any(c["score_100"] > 80 for c in high_awareness)


def test_missing_required_field_flags_needs_refresh_and_never_scores():
    result = build()
    robo = by_name(result, "Robo Nuggets")
    assert robo["status"] == scorer.STATUS_REFRESH
    assert "avg_views" in robo["missing_fields"]
    # Never fabricate: no score is invented for an incomplete row.
    assert robo["weighted_score"] is None
    assert robo["role"] is None
    assert robo not in result["shortlist"]


def test_engagement_floor_is_a_gate_not_a_tiebreaker():
    result = build()
    mikey = by_name(result, "Mikey No Code")
    assert mikey["status"] == scorer.STATUS_DROP
    assert mikey["content_match"] == 5.0  # perfect on content and still dropped
    assert "floor" in mikey["status_reason"]


def test_shortlist_is_sorted_descending_and_capped():
    result = build()
    scores = [c["weighted_score"] for c in result["shortlist"]]
    assert scores == sorted(scores, reverse=True)
    assert len(result["shortlist"]) <= result["criteria"]["shortlist_size"]
    assert [c["rank"] for c in result["shortlist"]] == list(
        range(1, len(result["shortlist"]) + 1)
    )


def test_cpm_uses_views_not_followers():
    result = build()
    riley = by_name(result, "Riley Brown")
    expected_views = 180_000 * config.SPONSOR_DECAY
    assert riley["cpm"]["expected_views"] == round(expected_views)
    assert riley["cpm"]["budget"] == round(
        expected_views * 2 / 1000 * config.DEFAULT_CPM, 2
    )


def test_exclusions_drop_a_creator():
    brief = {**config.DEFAULT_BRIEF, "exclusions": "Notion"}
    result = scorer.build_shortlist(brief, config.CREATOR_CSV)
    parker = by_name(result, "Parker Prompts")
    assert parker["status"] == scorer.STATUS_DROP
    assert "notion" in parker["status_reason"].lower()


def test_follower_band_filter():
    brief = {**config.DEFAULT_BRIEF, "follower_band": "micro"}
    result = scorer.build_shortlist(brief, config.CREATOR_CSV)
    for creator in result["shortlist"]:
        assert 50_000 <= creator["followers"] <= 150_000


def test_loads_json_as_well_as_csv():
    payload = [
        {
            "name": "Test Creator",
            "platform": "TikTok",
            "followers": 100000,
            "avg_views": 40000,
            "engagement_rate": 9.0,
            "geo_us_pct": 70,
            "brand_deals_count": 3,
            "audience_18_24_pct": 60,
            "age_evidence": "strong",
            "geo_evidence": "hard",
            "niche_relevance_pct": 60,
            "content_format": "tutorial",
        }
    ]
    result = scorer.build_shortlist(config.DEFAULT_BRIEF, payload)
    creator = result["shortlist"][0]
    assert creator["name"] == "Test Creator"
    assert creator["role"] == scorer.ROLE_CREDIBILITY
    assert creator["weighted_score"] == 5.0


def test_csv_export_has_header_and_every_row():
    result = build()
    csv_text = scorer.to_csv(result)
    lines = [line for line in csv_text.splitlines() if line.strip()]
    assert lines[0].startswith("Rank,Creator Name,Platform(s)")
    assert len(lines) == len(result["table"]) + 1
    assert "NEEDS_REFRESH" in csv_text
