"""Flask route tests.

These cover the browser-facing half of the verification list in CLAUDE.md:
the app imports and serves, Screen 1 carries every field, Screen 2 renders a
scored table, the CSV downloads, and /schedule answers as both HTML and JSON.

The UI's specific job is to make the engine's REFUSALS legible, so the sharpest
tests here are the ones asserting that unscored creators are still on the page.
"""

import csv
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as flask_app
import config
import scorer
from flask import Flask


@pytest.fixture()
def client():
    flask_app.app.config.update(TESTING=True)
    return flask_app.app.test_client()


BRIEF_FORM = {
    "brand_name": "Craftly",
    "product_description": config.DEFAULT_BRIEF["product_description"],
    "category": "AI app-building tools",
    "campaign_goal": "awareness",
    "target_audience": config.DEFAULT_BRIEF["target_audience"],
    "platforms": ["tiktok", "instagram", "youtube"],
    "cpm": "50",
    "follower_band": "all",
    "shortlist_size": "18",
    "exclusions": config.DEFAULT_BRIEF["exclusions"],
}


# ---------------------------------------------------------------------------
# Screen 1
# ---------------------------------------------------------------------------
def test_index_renders_every_brief_field(client):
    body = client.get("/").get_data(as_text=True)
    assert client.get("/").status_code == 200
    for field in (
        'name="brand_name"',
        'name="product_description"',
        'name="category"',
        'name="campaign_goal"',
        'name="target_audience"',
        'name="platforms"',
        'name="cpm"',
        'name="follower_band"',
        'name="shortlist_size"',
        'name="exclusions"',
    ):
        assert field in body, f"Screen 1 is missing {field}"


def test_index_offers_every_platform_including_linkedin(client):
    body = client.get("/").get_data(as_text=True)
    for slug in config.PLATFORM_SLUGS:
        assert f'value="{slug}"' in body
    # LinkedIn has no fitted bands and the form must say so rather than
    # presenting it as an equal option.
    assert "uncalibrated" in body


# ---------------------------------------------------------------------------
# Screen 2
# ---------------------------------------------------------------------------
def test_shortlist_renders_a_scored_table(client):
    response = client.post("/shortlist", data=BRIEF_FORM)
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Joshua La Rosa" in body
    assert "98.0" in body
    assert "Credibility" in body


def test_every_evaluated_creator_appears_on_screen_two(client):
    """A creator that vanishes is indistinguishable from one nobody sourced."""
    result = scorer.build_shortlist(config.DEFAULT_BRIEF, config.CREATOR_DATA)
    body = client.post("/shortlist", data=BRIEF_FORM).get_data(as_text=True)
    for creator in result["table"]:
        assert creator["name"] in body, f"{creator['name']} fell off the page"


def test_all_five_statuses_render_with_their_reason(client):
    body = client.post("/shortlist", data=BRIEF_FORM).get_data(as_text=True)
    for status in (
        scorer.STATUS_KEEP,
        scorer.STATUS_DROP,
        scorer.STATUS_REFRESH,
        scorer.STATUS_REVIEW,
    ):
        assert status in body, f"{status} rows are not rendered"
    # The reasons, not just the labels.
    assert "cannot produce the deliverable" in body
    assert "category readiness not judged" in body


def test_unreproducible_rates_are_flagged_in_the_ui(client):
    """Three rows carry rate_reproducible: false. The UI must not hide that."""
    body = client.post("/shortlist", data=BRIEF_FORM).get_data(as_text=True)
    assert "rate not reproducible" in body


def test_screen_two_shows_provenance(client):
    body = client.post("/shortlist", data=BRIEF_FORM).get_data(as_text=True)
    assert "Creator Sheet for Craftly" in body
    assert "2026-09-10" in body


def test_changing_the_category_changes_the_roles_not_just_the_heading(client):
    """The category field really drives scoring, and the screen shows it."""
    form = {**BRIEF_FORM, "category": "student productivity hardware"}
    body = client.post("/shortlist", data=form).get_data(as_text=True)
    assert "student productivity hardware" in body
    assert scorer.STATUS_REVIEW in body
    assert "re-judge before use" in body


def test_an_empty_roster_explains_itself_instead_of_looking_broken(client):
    """The guard's most confusing symptom is a blank shortlist.

    The per-row reason is not enough: it sits in a greyed table nobody reads
    when the thing above it is empty. The page must say, at the top, that this
    is a refusal rather than a failure — and what to do about it.
    """
    form = {**BRIEF_FORM, "category": "student productivity hardware"}
    body = client.post("/shortlist", data=form).get_data(as_text=True)

    assert "this is not an empty result" in body
    assert "held back for re-judgement" in body
    # Names both sides of the mismatch, so the cause is not a guess.
    assert "AI app-building tools" in body
    # And says how to fix it.
    assert "readiness_category" in body


def test_the_explanation_stays_out_of_the_way_on_a_normal_run(client):
    body = client.post("/shortlist", data=BRIEF_FORM).get_data(as_text=True)
    assert "held back for re-judgement" not in body
    assert "Nothing was shortlisted" not in body


def test_an_empty_shortlist_from_another_cause_still_explains_itself(client):
    """Not every empty roster is the readiness guard.

    A LinkedIn-only brief drops the whole pool on the briefed-platform check —
    a real emptiness with a different cause, which must not borrow the
    readiness explanation.
    """
    form = {**BRIEF_FORM, "platforms": ["linkedin"]}
    body = client.post("/shortlist", data=form).get_data(as_text=True)

    assert "Nothing was shortlisted" in body
    assert "held back for re-judgement" not in body, (
        "an unrelated emptiness must not be blamed on the readiness guard"
    )


def test_shortlist_survives_a_mostly_empty_form(client):
    """A partly filled form falls back to the campaign slot rather than erroring."""
    response = client.post("/shortlist", data={"brand_name": "Craftly"})
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------
def test_export_csv_downloads_a_valid_file(client):
    response = client.post("/export.csv", data=BRIEF_FORM)
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert "attachment" in response.headers["Content-Disposition"]
    assert ".csv" in response.headers["Content-Disposition"]

    rows = list(csv.reader(io.StringIO(response.get_data(as_text=True))))
    assert rows[0][0] == "Rank"
    assert len(rows) > 1


def test_export_matches_what_the_screen_showed(client):
    """Export re-runs the same brief, so it cannot drift from Screen 2."""
    result = scorer.build_shortlist(config.DEFAULT_BRIEF, config.CREATOR_DATA)
    rows = list(csv.reader(io.StringIO(
        client.post("/export.csv", data=BRIEF_FORM).get_data(as_text=True)
    )))
    assert len(rows) - 1 == len(result["table"])


# ---------------------------------------------------------------------------
# Schedule + JSON surfaces
# ---------------------------------------------------------------------------
def test_schedule_console_renders_html(client):
    response = client.get("/schedule")
    assert response.status_code == 200
    assert response.mimetype == "text/html"
    assert "Discovery schedule" in response.get_data(as_text=True)


def test_schedule_returns_json_on_request(client):
    """CLAUDE.md's verification item 6 — /schedule answers JSON too."""
    for response in (
        client.get("/schedule?format=json"),
        client.get("/schedule", headers={"Accept": "application/json"}),
        client.get("/api/schedule"),
    ):
        assert response.status_code == 200
        assert response.mimetype == "application/json"
        payload = response.get_json()
        assert payload["cadence"] in config.CADENCES
        assert "next_run" in payload


def test_cadence_can_be_set_and_a_bad_one_is_refused(client):
    assert client.post(
        "/schedule/cadence", data={"cadence": "daily"},
        headers={"Accept": "application/json"},
    ).get_json()["cadence"] == "daily"

    bad = client.post(
        "/schedule/cadence", data={"cadence": "hourly"},
        headers={"Accept": "application/json"},
    )
    assert bad.status_code == 400

    # Leave the stored cadence as the documented default.
    client.post("/schedule/cadence", data={"cadence": config.DEFAULT_CADENCE},
                headers={"Accept": "application/json"})


def test_api_shortlist_is_json(client):
    payload = client.get("/api/shortlist").get_json()
    assert payload["counts"]["evaluated"] > 0
    assert payload["table"][0]["name"]


def test_healthz_reports_spec_agreement(client):
    payload = client.get("/healthz").get_json()
    assert payload["ok"] is True
    assert payload["spec_loaded"] is True
    assert payload["weights_match_spec"] is True


def test_spec_markdown_is_rendered_not_escaped_into_the_page(client):
    """The spec is markdown on disk; the UI quotes it, so it must render."""
    body = client.get("/").get_data(as_text=True)
    assert "**Never fabricate" not in body
    assert "<strong>Never fabricate creator metrics</strong>" in body


# ---------------------------------------------------------------------------
# Deployment surface
#
# Two properties that fail silently: gunicorn cannot find the app, or debug
# reaches a public host. The first breaks the deploy loudly at boot; the second
# does not break anything at all, which is why it needs a test.
# ---------------------------------------------------------------------------
def test_gunicorn_entry_point_resolves():
    """render.yaml runs `gunicorn app:app` — that name must exist."""
    import app as module

    assert isinstance(module.app, Flask)


def test_debug_is_off_unless_explicitly_asked_for(monkeypatch):
    """The Werkzeug debugger executes arbitrary code from the browser.

    A debug default that survives to a public host is a remote shell, so debug
    must be opt-in through the environment and never the default.
    """
    assert flask_app.app.debug is False

    for value in ("", "0", "false", "no", "off"):
        monkeypatch.setenv("FLASK_DEBUG", value)
        assert flask_app._env_flag("FLASK_DEBUG") is False, f"{value!r} enabled debug"

    for value in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv("FLASK_DEBUG", value)
        assert flask_app._env_flag("FLASK_DEBUG") is True

    monkeypatch.delenv("FLASK_DEBUG", raising=False)
    assert flask_app._env_flag("FLASK_DEBUG") is False


def test_the_blueprint_matches_how_the_app_is_actually_served():
    """render.yaml drifting from the code is a deploy that boots to a 404."""
    import re

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    blueprint = open(os.path.join(root, "render.yaml"), encoding="utf-8").read()

    assert "gunicorn app:app" in blueprint
    assert re.search(r"rootDir:\s*creator-scout-agent", blueprint)
    # The health check must point at a route that exists.
    health = re.search(r"healthCheckPath:\s*(\S+)", blueprint).group(1)
    assert flask_app.app.test_client().get(health).status_code == 200
    # Debug must never be turned on from the blueprint.
    assert "FLASK_DEBUG" not in blueprint.split("# Never set")[0]
