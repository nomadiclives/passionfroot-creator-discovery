"""Tests for Step 3 screening.

The tests that matter here are the negative ones. Any triage can report FAIL on
a creator sponsored by a competitor; the property worth pinning is that it
reports UNKNOWN — never PASS — on a creator nobody has looked at. Most of this
file exists to stop a future change from turning "we never checked" into a
clean bill of health.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import scorer  # noqa: E402
import screening  # noqa: E402


@pytest.fixture
def criteria():
    return scorer.lock_criteria(config.DEFAULT_BRIEF)


@pytest.fixture
def pool():
    with open(config.CREATOR_DATA, "r", encoding="utf-8") as fh:
        return json.load(fh)["creators"]


def make(**overrides) -> dict:
    """A creator that passes every check, so a test can break exactly one.

    Written out in full rather than built from the bundled pool: a fixture that
    drifts with the data would make these tests prove nothing.
    """
    creator = {
        "name": "Test Creator",
        "handle": "testcreator",
        "platform": "TikTok",
        "followers": 100_000,
        "avg_views": 40_000,
        "resonance_rate": 40.0,
        "engagement_rate": 6.0,
        "comment_quality": "substantive",
        "current_sponsors": "Notion, Grammarly",
        "growth_pattern": "organic",
        "brand_safety": "clear",
    }
    creator.update(overrides)
    return creator


# ---------------------------------------------------------------------------
# The core invariant: absence of evidence is never a pass
# ---------------------------------------------------------------------------
def test_pass_is_reachable(criteria):
    """If nothing can ever reach PASS the module is just an alarm. Baseline."""
    report = screening.screen(make(), criteria)
    assert report["verdict"] == screening.PASS
    assert report["open_items"] == []
    assert report["unanswered"] == []


def test_empty_creator_is_never_pass(criteria):
    """A row with nothing on it must not come back clean."""
    report = screening.screen({"name": "Nobody", "platform": "TikTok"}, criteria)
    assert report["verdict"] == screening.NEEDS_SCREENING
    verdicts = {c["key"]: c["verdict"] for c in report["checks"]}
    assert screening.PASS not in [
        verdicts[k] for k in ("competitor", "comments", "brand_safety")
    ]


@pytest.mark.parametrize(
    "field", ["brand_safety", "comment_quality", "current_sponsors"]
)
def test_dropping_any_blocking_field_blocks_the_row(criteria, field):
    """Each blocking check independently holds the row when unanswered."""
    creator = make()
    creator[field] = ""
    if field == "current_sponsors":
        creator["notes"] = ""  # sponsors are also read out of notes
    report = screening.screen(creator, criteria)
    assert report["verdict"] == screening.NEEDS_SCREENING
    assert report["open_items"]


def test_no_sponsor_data_is_unknown_not_pass(criteria):
    """The sharpest version of the rule.

    A creator with no sponsor information has not been cleared of a competitor
    conflict — nobody looked. Reading that as PASS would be the module telling
    a comfortable lie.
    """
    report = screening.screen(
        make(current_sponsors="", notes=""), criteria
    )
    check = next(c for c in report["checks"] if c["key"] == "competitor")
    assert check["verdict"] == screening.UNKNOWN
    assert "never" in check["reason"]


def test_sponsor_data_without_a_competitor_does_pass(criteria):
    """The positive case still works: looked, found nothing, PASS."""
    report = screening.screen(make(current_sponsors="Notion"), criteria)
    check = next(c for c in report["checks"] if c["key"] == "competitor")
    assert check["verdict"] == screening.PASS


def test_brand_safety_is_unknown_until_a_human_records_it(criteria):
    report = screening.screen(make(brand_safety=""), criteria)
    check = next(c for c in report["checks"] if c["key"] == "brand_safety")
    assert check["verdict"] == screening.UNKNOWN
    assert check["basis"] == config.BASIS_HUMAN
    assert check["blocking"] is True


def test_unrecognised_recorded_value_is_not_interpreted(criteria):
    """A value the module does not understand is UNKNOWN, not the nearest guess."""
    for field, key in (
        ("brand_safety", "brand_safety"),
        ("comment_quality", "comments"),
        ("growth_pattern", "growth"),
    ):
        report = screening.screen(make(**{field: "banana"}), criteria)
        check = next(c for c in report["checks"] if c["key"] == key)
        assert check["verdict"] == screening.UNKNOWN, field
        assert "not interpreted" in check["reason"]


# ---------------------------------------------------------------------------
# Agreement with the scorer — the two must never contradict each other
# ---------------------------------------------------------------------------
def test_screening_fails_exactly_the_creators_the_scorer_drops(pool, criteria):
    """The integration invariant.

    Screening and scoring apply the same Step 3 gates by different routes. If
    they ever disagree, one of them is wrong, and a shortlist would contain a
    creator the triage screen showed as rejected.
    """
    result = scorer.build_shortlist(config.DEFAULT_BRIEF, pool)
    dropped = {c["name"] for c in result["dropped"]}
    failed = {
        r["name"]
        for r in screening.screen_all(pool, criteria)["rows"]
        if r["verdict"] == screening.FAIL
    }
    assert failed == dropped


def test_inauthentic_comments_fail_here_and_drop_there(criteria):
    """The authenticity gate is one rule read from one vocabulary."""
    creator = make(comment_quality="suspected")
    report = screening.screen(creator, criteria)
    assert report["verdict"] == screening.FAIL

    result = scorer.build_shortlist(config.DEFAULT_BRIEF, [creator])
    assert result["dropped"], "scorer should drop a creator screening FAILs"


def test_newsletter_cannot_deliver_video(criteria):
    """The No-Code Exits case, in the shape the real row actually has.

    A newsletter carries no scored `platform`; its surfaces live in
    `other_surfaces`, which the deliverable gate reads too.
    """
    report = screening.screen(
        make(platform="", other_surfaces="newsletter, twitter"), criteria
    )
    check = next(c for c in report["checks"] if c["key"] == "deliverable")
    assert check["verdict"] == screening.FAIL
    assert report["verdict"] == screening.FAIL


def test_no_known_surface_is_unknown_not_fail(criteria):
    """Not knowing what someone publishes on is not the same as knowing they
    cannot deliver. The first is a sourcing gap; the second rejects a creator."""
    report = screening.screen(
        make(platform="", other_surfaces=""), criteria
    )
    check = next(c for c in report["checks"] if c["key"] == "deliverable")
    assert check["verdict"] == screening.UNKNOWN
    assert report["verdict"] == screening.NEEDS_SCREENING


def test_a_competitor_sponsorship_flags_rather_than_fails(criteria):
    """Matches the scorer: a rival's creator is a lead, not a rejection."""
    creator = make(current_sponsors="Sponsored by Bubble this month")
    report = screening.screen(creator, criteria)
    check = next(c for c in report["checks"] if c["key"] == "competitor")
    assert check["verdict"] == screening.FLAG
    assert scorer.competitor_hit(
        scorer.normalise_creator(creator), criteria["exclusions"]
    ) == "bubble"


def test_only_a_recorded_clause_fails_the_competitor_check(criteria):
    report = screening.screen(
        make(current_sponsors="Bubble", exclusivity="active until March"), criteria
    )
    check = next(c for c in report["checks"] if c["key"] == "competitor")
    assert check["verdict"] == screening.FAIL
    assert check["basis"] == config.BASIS_RECORDED


def test_a_note_mentioning_a_competitor_flags_more_weakly(criteria):
    """Prose is not a sponsor record, so it is reported as a mention."""
    report = screening.screen(
        make(current_sponsors="", notes="much better than Bubble honestly"), criteria
    )
    check = next(c for c in report["checks"] if c["key"] == "competitor")
    assert check["verdict"] == screening.FLAG
    assert "not a sponsorship" in check["reason"]


# ---------------------------------------------------------------------------
# The two constructs that must not be conflated
# ---------------------------------------------------------------------------
def test_resonance_rate_is_not_used_as_an_engagement_rate(criteria):
    """D3's view rate and the spec's engagement ratio are different measures.

    A creator with a healthy resonance_rate and no engagement_rate must come
    back UNKNOWN on the engagement check. Substituting one for the other would
    collapse the instrument distinction the whole D3 model rests on.
    """
    creator = make(resonance_rate=40.0)
    del creator["engagement_rate"]
    report = screening.screen(creator, criteria)
    check = next(c for c in report["checks"] if c["key"] == "engagement")
    assert check["verdict"] == screening.UNKNOWN
    assert "resonance_rate" in check["reason"]


def test_engagement_check_uses_the_spec_thresholds_not_the_d3_floors(criteria):
    """2.0% on TikTok is above the spec's 1% suspect line and below D3's 3.5%.

    It must FLAG at most here — the ineligibility decision belongs to the
    scorer, and importing it would make the triage silently double-penalise.
    """
    report = screening.screen(make(platform="TikTok", engagement_rate=2.0), criteria)
    check = next(c for c in report["checks"] if c["key"] == "engagement")
    assert check["verdict"] == screening.PASS

    low = screening.screen(make(platform="TikTok", engagement_rate=0.5), criteria)
    check = next(c for c in low["checks"] if c["key"] == "engagement")
    assert check["verdict"] == screening.FLAG


def test_view_ratio_flags_but_never_fails(criteria):
    """The floor is a project policy, not the spec's, so it cannot reject."""
    report = screening.screen(make(followers=1_000_000, avg_views=1_000), criteria)
    check = next(c for c in report["checks"] if c["key"] == "view_ratio")
    assert check["verdict"] == screening.FLAG
    assert "not the spec's" in check["reason"]
    assert report["verdict"] != screening.FAIL


def test_view_ratio_unknown_without_both_numbers(criteria):
    creator = make()
    del creator["avg_views"]
    report = screening.screen(creator, criteria)
    check = next(c for c in report["checks"] if c["key"] == "view_ratio")
    assert check["verdict"] == screening.UNKNOWN


# ---------------------------------------------------------------------------
# Audience evidence is evidence, not a verdict
# ---------------------------------------------------------------------------
def test_audience_evidence_never_produces_demographics(criteria):
    """The temptation DISCOVERY_PLAN.md §1 exists to close off.

    Content signals may be gathered and shown. They must never be turned into
    audience_18_24_pct or geo_us_pct — D1 and D4, 40% of the score.
    """
    creator = make(
        age_evidence="mentions dorms, finals and student loans",
        geo_evidence="US university references",
        location="US",
    )
    evidence = screening.audience_evidence(
        scorer.normalise_creator(creator), criteria
    )
    fields = {e["field"] for e in evidence}
    assert "audience_18_24_pct" not in fields
    assert "geo_us_pct" not in fields
    assert "age_evidence" in fields

    report = screening.screen(creator, criteria)
    assert "audience_18_24_pct" not in report
    assert not any(c["key"].endswith("_pct") for c in report["checks"])


def test_screening_never_assigns_a_score_or_a_role(criteria):
    """Triage is not judgement. Those belong to the human and the scorer."""
    report = screening.screen(make(), criteria)
    for forbidden in ("score", "score_100", "role", "tier", "readiness"):
        assert forbidden not in report


def test_screening_does_not_mutate_the_creator(criteria):
    creator = make()
    before = json.dumps(creator, sort_keys=True)
    screening.screen(creator, criteria)
    assert json.dumps(creator, sort_keys=True) == before


# ---------------------------------------------------------------------------
# Rollup behaviour
# ---------------------------------------------------------------------------
def test_fail_outranks_an_unanswered_check(criteria):
    report = screening.screen(
        make(comment_quality="inauthentic", brand_safety=""), criteria
    )
    assert report["verdict"] == screening.FAIL


def test_unanswered_blocking_check_outranks_a_flag(criteria):
    """A gap nobody looked at is a worse position than a concern somebody weighed."""
    report = screening.screen(
        make(comment_quality="generic", brand_safety=""), criteria
    )
    assert report["verdict"] == screening.NEEDS_SCREENING


def test_flag_survives_when_everything_is_answered(criteria):
    report = screening.screen(make(comment_quality="generic"), criteria)
    assert report["verdict"] == screening.FLAG


def test_non_blocking_gap_still_listed_on_a_pass(criteria):
    """A PASS row does not hide its remaining gaps."""
    report = screening.screen(make(growth_pattern=""), criteria)
    assert report["verdict"] == screening.PASS
    assert "Follower growth curve" in report["unanswered"]
    assert report["open_items"] == []


def test_needs_refresh_row_is_still_screenable(criteria):
    """A metric gap is not a screening gap; the two are reported separately."""
    creator = make()
    del creator["followers"]
    del creator["resonance_rate"]
    report = screening.screen(creator, criteria)
    assert "followers" in report["missing_metrics"]
    assert report["verdict"] in {
        screening.PASS, screening.FLAG, screening.NEEDS_SCREENING, screening.FAIL
    }
    # The checks that need no metric still answered.
    brand = next(c for c in report["checks"] if c["key"] == "brand_safety")
    assert brand["verdict"] == screening.PASS


def test_raw_and_normalised_rows_screen_identically(criteria):
    raw = make()
    report_raw = screening.screen(raw, criteria)
    report_norm = screening.screen(scorer.normalise_creator(raw), criteria)
    assert report_raw["checks"] == report_norm["checks"]
    assert report_raw["verdict"] == report_norm["verdict"]


# ---------------------------------------------------------------------------
# Pool-level reporting
# ---------------------------------------------------------------------------
def test_screen_all_counts_add_up(pool, criteria):
    result = screening.screen_all(pool, criteria)
    assert result["total"] == len(pool)
    assert sum(result["counts"].values()) == len(pool)


def test_bundled_pool_is_all_unscreened_until_brand_safety_is_done(pool, criteria):
    """Documents the deliberate consequence rather than hiding it.

    Nobody has recorded a brand-safety review for any bundled creator, so no
    row can honestly PASS. If this test starts failing because rows turned
    green, check that a default did not quietly start answering the check.
    """
    result = screening.screen_all(pool, criteria)
    assert result["counts"][screening.PASS] == 0
    backlog = {e["key"]: e for e in result["unknown_by_check"]}
    assert backlog["brand_safety"]["count"] == len(pool)


def test_backlog_puts_blocking_checks_first(pool, criteria):
    result = screening.screen_all(pool, criteria)
    blocking = [e["blocking"] for e in result["unknown_by_check"]]
    assert blocking == sorted(blocking, reverse=True)


def test_recording_brand_safety_unblocks_a_row(pool, criteria):
    """The backlog is actionable: answering the check changes the verdict."""
    creator = dict(pool[0])
    before = screening.screen(creator, criteria)
    assert before["verdict"] == screening.NEEDS_SCREENING

    creator["brand_safety"] = "clear"
    after = screening.screen(creator, criteria)
    assert "Brand safety" not in after["open_items"]
    # Still held, but by a different check now: no row in the bundled data
    # records `current_sponsors`, so nobody has sourced who pays this creator.
    # That is the honest answer, and naming which check is holding the row is
    # the point of open_items.
    assert after["open_items"] == ["Competitor exclusivity"]


# ---------------------------------------------------------------------------
# The /screen route
# ---------------------------------------------------------------------------
@pytest.fixture()
def client():
    import app as flask_app

    flask_app.app.config.update(TESTING=True)
    return flask_app.app.test_client()


def test_screen_route_renders(client, pool):
    page = client.get("/screen")
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "Screen the pool" in body
    # Every creator is on the page, including the ones that failed.
    assert "No-Code Exits" in body
    assert "sofieestudies" in body
    # And the backlog is shown rather than the gaps being quietly absorbed.
    assert "What to source next" in body
    assert "Brand safety" in body


def test_screen_route_shows_the_refusal_not_a_clean_bill(client):
    """The UI's job is to make the engine's refusals legible."""
    body = client.get("/screen").get_data(as_text=True)
    assert screening.NEEDS_SCREENING in body
    assert "A check nobody answered is not a pass." in body


def test_screen_route_has_no_form_inputs(client):
    """Read-only by construction.

    A check is cleared by sourcing evidence onto the row, not by ticking a box.
    An input here would be the same mistake the judging screen avoids by
    refusing to offer a followers field.
    """
    body = client.get("/screen").get_data(as_text=True)
    start = body.index("Screen the pool")
    assert "<input" not in body[start:]
    assert "<form" not in body[start:]


def test_api_screen_returns_the_backlog(client):
    payload = client.get("/api/screen").get_json()
    assert payload["total"] == payload["pool"]["count"]
    assert sum(payload["counts"].values()) == payload["total"]
    keys = {e["key"] for e in payload["unknown_by_check"]}
    assert "brand_safety" in keys
    assert payload["rows"][0]["checks"]


def test_screen_route_survives_an_empty_pool(client, tmp_path):
    """An empty pool explains itself instead of rendering a broken table."""
    import creator_pool

    token = creator_pool.save([], "empty pool")
    body = client.get(f"/screen?{creator_pool.TOKEN_FIELD}={token}").get_data(as_text=True)
    assert "nothing to triage" in body


def test_screen_carries_the_brief_through_to_judging(client):
    """Judging records readiness against the brief's category.

    A link that dropped the brief would send the operator to judge this pool
    against the default campaign instead of the one they screened it under —
    and readiness does not transfer between categories.
    """
    body = client.get(
        "/screen?category=Project+management+tools&brand_name=Acme"
    ).get_data(as_text=True)
    assert "category=Project+management+tools" in body
    assert "brand_name=Acme" in body
