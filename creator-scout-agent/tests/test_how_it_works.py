"""The one-pager must describe the model that is actually applied.

This page exists to explain the scoring model to someone deciding whether to trust a
shortlist. A stale explanation is worse than none, because it gets believed — so these
tests pin the page to live config rather than to prose, and pin the two claims most
likely to drift into overclaiming.
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module
import config
import scorer


@pytest.fixture()
def client():
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        yield client


@pytest.fixture()
def page(client):
    response = client.get("/how-it-works")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def test_page_renders(page):
    assert "How this works" in page


def test_every_weight_is_rendered_from_config(page):
    """Change a weight and the page changes with it, or this fails."""
    for dimension, weight in config.SCORING_WEIGHTS.items():
        rendered = f"{round(weight * 100)}%"
        assert rendered in page, f"{dimension} weight missing from the page"


def test_readiness_to_role_mapping_comes_from_config(page):
    for readiness, role in config.READINESS_ROLES.items():
        assert readiness in page
        assert role in page


def test_uncalibrated_platforms_are_named_as_such(page):
    """A platform without fitted bands must be named, not quietly omitted.

    Matched against the page's own display labels, not a capitalize() of the slug —
    the page renders "LinkedIn", which is the name a reader would recognise.
    """
    uncalibrated = [s for s, i in config.INSTRUMENTS.items() if not i.get("bands")]
    for slug in uncalibrated:
        assert scorer._pretty_platform(slug) in page
    if uncalibrated:
        assert "NEEDS_CALIBRATION" in page


def test_every_refusal_state_is_explained(page):
    for status in ("Keep", "Drop", "NEEDS_REFRESH", "NEEDS_REVIEW", "NEEDS_CALIBRATION"):
        assert status in page


def test_upload_retention_is_not_hardcoded(page):
    assert str(config.UPLOAD_RETENTION_HOURS) in page


def test_it_says_four_of_five_dimensions_are_human(page):
    """The single most important limitation. If this stops being true, say so here."""
    human_dimensions = [
        d for d in config.SCORING_WEIGHTS if d != "engagement_score"
    ]
    assert len(human_dimensions) == 4
    assert "Human judgement" in page
    assert page.count("who-human") >= 4


def test_it_does_not_claim_to_source_or_verify(page):
    """Guards against the page drifting into overclaiming what the tool does."""
    assert "cannot find creators" in page
    assert "does not verify a single number" in page
    assert "does not form judgements" in page


def test_outreach_angles_are_declared_as_templates(page):
    """They are three role-keyed strings. Never let the page imply generated copy."""
    assert "templates" in page.lower()
    assert "placeholder, not copy" in page


def test_sheet_agreement_claim_is_stated_precisely(page):
    """'16 of 17' is agreement across rows BOTH parties score, not the whole sheet.

    The looser phrasing overclaims: the sheet has 21 rows, and the engine is not a
    superset of its judgement. Corrected 2026-09-11; pinned here so it stays corrected.
    """
    assert "both score" in page
    assert "21 rows" in page
    assert "not a superset" in page.replace("<em>", "").replace("</em>", "")
    # The bare overclaim must not reappear.
    assert not re.search(r"16 of 17 hand-scored rows", page)


def test_spec_agreement_is_reported_not_assumed(page):
    assert "agree" in page


def test_page_is_reachable_from_every_screen(client):
    """It is only useful if someone lands on it; the nav link must be present."""
    for route in ("/", "/shortlist", "/schedule"):
        body = client.get(route).get_data(as_text=True)
        assert "/how-it-works" in body, f"nav link missing on {route}"
