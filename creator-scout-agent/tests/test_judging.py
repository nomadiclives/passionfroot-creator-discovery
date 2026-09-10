"""Tests for the in-app judging screen.

Judging in the browser is the one feature that looks, from a distance, like it
weakens the project's central rule. It does not — it is the same human judgement
arriving through a better door than hand-editing CSV columns. But the boundary it
must hold is exact, and these tests are mostly about that boundary:

    judgement can be typed        the four sub-scores and the readiness call
    a metric must be sourced      followers and resonance_rate are never inputs

The other property worth pinning is that judging never writes to the checked-in
creator data, which carries provenance the browser cannot honestly supply.
"""

import io
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as flask_app
import config
import creator_pool
import scorer


@pytest.fixture(autouse=True)
def isolated_upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "UPLOAD_DIR", str(tmp_path / "uploads"))


@pytest.fixture()
def client():
    flask_app.app.config.update(TESTING=True)
    return flask_app.app.test_client()


# Three judgeable creators and one with a metric gap, which must stay locked.
RAW_POOL = (
    "name,platform,followers,resonance_rate\n"
    "Ada Vance,TikTok,120000,9.1\n"
    "Bo Lindqvist,Instagram,64000,7.2\n"
    "Cy Okafor,YouTube,210000,11.4\n"
    "Dee Nakamura,TikTok,,\n"
)

FORM = {
    "brand_name": "Ledgerly",
    "category": "Fintech apps",
    "campaign_goal": "awareness",
    "platforms": ["tiktok", "instagram", "youtube"],
    "cpm": "50",
    "follower_band": "all",
    "shortlist_size": "18",
}

FULL_JUDGEMENT = {
    "audience_match_score": "4",
    "content_match_score": "4",
    "geo_match_score": "5",
    "commercial_maturity_score": "3",
}


@pytest.fixture()
def pool():
    """A parked raw pool, as an upload would leave it."""
    rows = creator_pool.parse(RAW_POOL.encode("utf-8"), "fintech.csv")
    return creator_pool.save(rows, "fintech.csv")


def judgement_for(index: int, readiness: str = "exposed", **overrides) -> dict:
    payload = {**FULL_JUDGEMENT, "readiness": readiness, **overrides}
    return {f"judge-{index}-{field}": value for field, value in payload.items()}


# ---------------------------------------------------------------------------
# The boundary: judgement is typed, a metric is sourced
# ---------------------------------------------------------------------------
def test_the_form_offers_every_judged_dimension_and_the_readiness_call(client, pool):
    body = client.post("/judge", data={**FORM, "pool_token": pool}).get_data(as_text=True)
    for field in scorer.JUDGED_FIELDS:
        assert f'name="judge-0-{field}"' in body, f"{field} must be judgeable"
    assert 'name="judge-0-readiness"' in body


def test_the_form_never_offers_an_input_for_a_sourced_metric(client, pool):
    """The rule the whole project rests on. A metric is sourced, never typed."""
    body = client.post("/judge", data={**FORM, "pool_token": pool}).get_data(as_text=True)
    for metric in ("followers", "resonance_rate", "avg_views", "engagement_rate"):
        assert f'name="judge-0-{metric}"' not in body, (
            f"{metric} is a metric — offering it as an input would invite invention"
        )


def test_a_row_missing_a_metric_is_locked_rather_than_judgeable(client, pool):
    body = client.post("/judge", data={**FORM, "pool_token": pool}).get_data(as_text=True)
    assert 'name="judge-3-audience_match_score"' not in body, (
        "Dee Nakamura has no follower count — judging cannot rescue that row"
    )
    assert "Locked" in body
    assert "Source the metric" in body


def test_a_locked_row_is_ignored_even_if_judgements_are_posted_for_it(client, pool):
    """The form does not offer row 3, so a hand-crafted POST must not change it."""
    client.post(
        "/judge/save", data={**FORM, "pool_token": pool, **judgement_for(3)}
    )
    rows, _ = creator_pool.load(pool)
    assert rows[3]["followers"] is None, "a metric gap must survive a judgement"
    scored = scorer.score_creator(
        scorer.normalise_creator(rows[3]), scorer.lock_criteria({**config.DEFAULT_BRIEF})
    )
    assert scored["status"] == scorer.STATUS_REFRESH


# ---------------------------------------------------------------------------
# Saving a judgement
# ---------------------------------------------------------------------------
def test_judging_a_row_makes_it_scorable(client, pool):
    before = scorer.build_shortlist({**config.DEFAULT_BRIEF, **{"category": "Fintech apps"}},
                                    creator_pool.load(pool)[0])
    assert before["counts"]["shortlisted"] == 0, "a raw pool scores nothing"

    client.post(
        "/judge/save",
        data={**FORM, "pool_token": pool, **judgement_for(0, "adopted")},
    )

    rows, _ = creator_pool.load(pool)
    after = scorer.build_shortlist({**config.DEFAULT_BRIEF, "category": "Fintech apps"}, rows)
    assert after["counts"]["shortlisted"] == 1
    assert after["shortlist"][0]["name"] == "Ada Vance"
    assert after["shortlist"][0]["role"] == "Conversion", "adopted -> Conversion"


@pytest.mark.parametrize(
    "readiness,role",
    [("unexposed", "Awareness"), ("exposed", "Credibility"), ("adopted", "Conversion")],
)
def test_the_readiness_typed_in_drives_the_role(client, pool, readiness, role):
    client.post(
        "/judge/save",
        data={**FORM, "pool_token": pool, **judgement_for(0, readiness)},
    )
    rows, _ = creator_pool.load(pool)
    result = scorer.build_shortlist({**config.DEFAULT_BRIEF, "category": "Fintech apps"}, rows)
    assert result["shortlist"][0]["role"] == role


def test_a_judgement_is_recorded_against_the_category_it_was_made_for(client, pool):
    """The whole point of readiness_category — evidence about one named category."""
    client.post("/judge/save", data={**FORM, "pool_token": pool, **judgement_for(0)})
    rows, _ = creator_pool.load(pool)
    assert rows[0]["readiness_category"] == "Fintech apps"


def test_a_judgement_does_not_transfer_to_a_brief_about_something_else(client, pool):
    client.post("/judge/save", data={**FORM, "pool_token": pool, **judgement_for(0)})
    rows, _ = creator_pool.load(pool)

    other = scorer.build_shortlist(
        {**config.DEFAULT_BRIEF, "category": "Running shoes"}, rows
    )
    assert other["counts"]["shortlisted"] == 0
    assert other["readiness_mismatch"], "the guard must still fire on an in-app judgement"
    assert other["judged_categories"] == ["Fintech apps"]


def test_an_in_app_judgement_is_distinguishable_from_a_sourced_one(client, pool):
    """Provenance: a judgement typed in a browser must not look like sourced data."""
    client.post("/judge/save", data={**FORM, "pool_token": pool, **judgement_for(0)})
    rows, _ = creator_pool.load(pool)
    assert rows[0]["judged_in_app"] is True
    assert rows[0]["judged_date"], "a judgement carries the date it was made"
    assert not rows[1].get("judged_in_app"), "an untouched row gains no provenance"


def test_a_partial_judgement_leaves_the_row_needing_review(client, pool):
    """Half a judgement is not a judgement. The row must not slip through scored."""
    client.post(
        "/judge/save",
        data={
            **FORM, "pool_token": pool,
            "judge-0-audience_match_score": "4",
            "judge-0-content_match_score": "4",
            "judge-0-readiness": "exposed",
        },
    )
    rows, _ = creator_pool.load(pool)
    result = scorer.build_shortlist({**config.DEFAULT_BRIEF, "category": "Fintech apps"}, rows)
    assert result["counts"]["shortlisted"] == 0
    assert result["counts"]["needs_review"] >= 1


def test_clearing_a_field_withdraws_the_judgement_rather_than_keeping_the_old_value(
    client, pool
):
    """The form shows what the pool holds, so an emptied field means 'unjudged'."""
    client.post("/judge/save", data={**FORM, "pool_token": pool, **judgement_for(0)})
    assert creator_pool.load(pool)[0][0]["audience_match_score"] == 4.0

    client.post(
        "/judge/save",
        data={**FORM, "pool_token": pool, **judgement_for(0, audience_match_score="")},
    )
    assert creator_pool.load(pool)[0][0]["audience_match_score"] is None


def test_the_form_is_prefilled_with_judgements_already_made(client, pool):
    client.post("/judge/save", data={**FORM, "pool_token": pool, **judgement_for(0, "adopted")})
    body = client.post("/judge", data={**FORM, "pool_token": pool}).get_data(as_text=True)
    assert re.search(r'name="judge-0-audience_match_score"[^>]*value="4', body)
    assert re.search(r'value="adopted"\s+selected', body)


# ---------------------------------------------------------------------------
# Refusing bad input
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["9", "0", "-2", "banana", "5.5"])
def test_an_out_of_range_score_is_refused_not_clamped(client, pool, bad):
    """Clamping would turn a typo into a judgement the operator never made."""
    response = client.post(
        "/judge/save",
        data={**FORM, "pool_token": pool, **judgement_for(0, audience_match_score=bad)},
    )
    assert response.status_code == 400
    assert "1 to 5" in response.get_data(as_text=True) or "outside 1-5" in response.get_data(as_text=True)


def test_a_refused_save_writes_nothing_at_all(client, pool):
    """One bad field must not leave the pool half-updated."""
    client.post(
        "/judge/save",
        data={
            **FORM, "pool_token": pool,
            **judgement_for(0),
            **judgement_for(1, audience_match_score="99"),
        },
    )
    rows, _ = creator_pool.load(pool)
    assert rows[0]["audience_match_score"] is None, "row 0 must not be saved either"
    assert rows[1]["audience_match_score"] is None


def test_a_refused_save_re_renders_the_form_rather_than_losing_the_work(client, pool):
    body = client.post(
        "/judge/save",
        data={**FORM, "pool_token": pool, **judgement_for(0, audience_match_score="9")},
    ).get_data(as_text=True)
    assert 'name="judge-0-audience_match_score"' in body, "the operator stays on the form"
    assert "Nothing was saved" in body


def test_an_unknown_readiness_value_is_refused_not_silently_dropped(client, pool):
    """Ignoring it would leave whatever the row already had, and report success."""
    client.post("/judge/save", data={**FORM, "pool_token": pool, **judgement_for(0, "adopted")})

    response = client.post(
        "/judge/save",
        data={**FORM, "pool_token": pool, **judgement_for(0, readiness="very-exposed")},
    )
    assert response.status_code == 400
    assert "not a readiness level" in response.get_data(as_text=True)
    assert creator_pool.load(pool)[0][0]["readiness"] == "adopted", "unchanged"


def test_a_hand_crafted_post_cannot_write_a_metric(client, pool):
    """The form not offering metric inputs is a courtesy. This allowlist is the guarantee."""
    client.post(
        "/judge/save",
        data={
            **FORM, "pool_token": pool, **judgement_for(0),
            "judge-0-followers": "999999",
            "judge-0-resonance_rate": "42",
            "judge-0-avg_views": "500000",
            "judge-0-readiness_category": "Something Else",
        },
    )
    row = creator_pool.load(pool)[0][0]
    assert row["followers"] == 120000, "the sourced follower count must be untouched"
    assert row["resonance_rate"] == 9.1
    assert row["avg_views"] is None, "a metric absent from the source stays absent"
    assert row["readiness_category"] == "Fintech apps", (
        "the category is taken from the brief, never from the posted form"
    )


def test_an_expired_pool_sends_the_operator_back_to_the_brief(client):
    response = client.post("/judge", data={**FORM, "pool_token": "0" * 32})
    assert response.status_code == 400
    assert "no longer available" in response.get_data(as_text=True)


# ---------------------------------------------------------------------------
# The bundled pool is forked, never edited
# ---------------------------------------------------------------------------
def test_judging_the_bundled_pool_forks_it_instead_of_editing_the_checked_in_data(client):
    before = open(config.CREATOR_DATA, "rb").read()
    body = client.post(
        "/judge", data={**FORM, "pool_token": creator_pool.BUNDLED}
    ).get_data(as_text=True)

    token = re.search(r'name="pool_token" value="([0-9a-f]{32})"', body).group(1)
    client.post("/judge/save", data={**FORM, "pool_token": token, **judgement_for(0)})

    assert open(config.CREATOR_DATA, "rb").read() == before, (
        "the checked-in creator data carries provenance a browser form cannot supply"
    )
    assert "working copy" in body


def test_a_forked_pool_carries_every_bundled_creator(client):
    body = client.post(
        "/judge", data={**FORM, "pool_token": creator_pool.BUNDLED}
    ).get_data(as_text=True)
    token = re.search(r'name="pool_token" value="([0-9a-f]{32})"', body).group(1)
    rows, _ = creator_pool.load(token)
    assert len(rows) == len(scorer.load_creators(config.CREATOR_DATA))


# ---------------------------------------------------------------------------
# The round trip through the screens
# ---------------------------------------------------------------------------
def test_save_and_build_lands_on_a_shortlist_of_the_judged_pool(client, pool):
    body = client.post(
        "/judge/save",
        data={
            **FORM, "pool_token": pool, "then": "shortlist",
            **judgement_for(0, "adopted"), **judgement_for(1, "exposed"),
        },
    ).get_data(as_text=True)
    assert "Ada Vance" in body and "Bo Lindqvist" in body
    assert "Joshua La Rosa" not in body, "the bundled pool must not leak in"
    assert "Conversion" in body and "Credibility" in body


def test_the_brief_survives_the_round_trip_through_judging(client, pool):
    body = client.post(
        "/judge/save",
        data={**FORM, "pool_token": pool, "then": "shortlist", **judgement_for(0)},
    ).get_data(as_text=True)
    assert "Ledgerly" in body
    assert "Fintech apps" in body, "the category must not revert to the campaign default"


def test_screen_two_offers_judging_when_rows_need_it(client):
    body = client.post(
        "/shortlist",
        data={**FORM, "creator_file": (io.BytesIO(RAW_POOL.encode()), "fintech.csv")},
        content_type="multipart/form-data",
    ).get_data(as_text=True)
    assert "/judge" in body
    assert "Judge 3 creators" in body


def test_screen_two_does_not_offer_judging_when_nothing_needs_it(client, pool):
    judged = {
        **FORM, "pool_token": pool, "then": "shortlist",
        **judgement_for(0, "adopted"), **judgement_for(1, "exposed"),
        **judgement_for(2, "unexposed"),
    }
    body = client.post("/judge/save", data=judged).get_data(as_text=True)
    assert "Judge " not in body, "nothing is left needing judgement"
