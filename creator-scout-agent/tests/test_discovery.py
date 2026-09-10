"""Tests for the discovery seam, the query plan, and the YouTube adapter.

Discovery is the phase most likely to break the project's central rule, because
it is the first time the app produces creators rather than consuming them. A
system that invents a creator is worse than one that invents a metric — the
metric is at least attached to someone real.

So the sharpest tests here assert absence: that a source with no key returns
nothing rather than something plausible, that a hidden subscriber count stays
absent rather than becoming 0, and that no code path writes a judgement.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import discovery
import scorer
from sources import query_plan, youtube


# ---------------------------------------------------------------------------
# The seam
# ---------------------------------------------------------------------------
def test_a_candidate_carries_its_provenance():
    row = discovery.candidate(
        name="Ada Vance", handle="@adavance", platform="tiktok",
        source="query_plan", search_source="Pass 1 — #aitools",
    )
    assert row["handle"] == "adavance", "the @ is stripped so dedupe works"
    assert row["search_source"] == "Pass 1 — #aitools"
    assert row["sourced_date"] and row["sourced_from"] == "query_plan"
    assert row["source_confidence"] == config.CONFIDENCE_CANDIDATE


def test_a_candidate_never_gets_a_default_metric():
    """A default follower count would be an invented metric with a nice API."""
    row = discovery.candidate(
        name="Ada", platform="tiktok", source="s", search_source="p"
    )
    for metric in ("followers", "resonance_rate", "avg_views"):
        assert metric not in row, f"{metric} must be absent, not defaulted"


def test_a_candidate_with_no_metrics_scores_as_needs_refresh():
    """The honest downstream outcome: a pasted handle is a lead, not a measurement."""
    row = discovery.candidate(
        name="Ada", handle="ada", platform="tiktok", source="s", search_source="p"
    )
    scored = scorer.score_creator(
        scorer.normalise_creator(row), scorer.lock_criteria(config.DEFAULT_BRIEF)
    )
    assert scored["status"] == scorer.STATUS_REFRESH
    assert "followers" in scored["status_reason"]


def test_discovery_never_emits_a_judgement_or_a_role():
    """Judgement is human. Discovery producing one would be inventing it."""
    row = discovery.candidate(
        name="Ada", platform="tiktok", source="s", search_source="p",
        followers=100000.0, resonance_rate=9.0,
    )
    for field in scorer.JUDGED_FIELDS + ("readiness", "readiness_category", "role"):
        assert field not in row, f"discovery must not set {field}"


def test_the_same_creator_from_two_passes_merges_and_records_corroboration():
    rows = [
        discovery.candidate(name="Ada", handle="@ada", platform="tiktok",
                            source="a", search_source="Pass 1"),
        discovery.candidate(name="Ada", handle="ada", platform="tiktok",
                            source="b", search_source="Pass 2"),
    ]
    merged = discovery.merge(rows)
    assert len(merged) == 1
    assert merged[0]["corroboration"] == 2
    assert merged[0]["corroborated_by"] == ["Pass 1", "Pass 2"]


def test_the_same_handle_on_two_platforms_is_two_creators():
    rows = [
        discovery.candidate(name="Ada", handle="ada", platform="tiktok",
                            source="a", search_source="p"),
        discovery.candidate(name="Ada", handle="ada", platform="youtube",
                            source="a", search_source="p"),
    ]
    assert len(discovery.merge(rows)) == 2


def test_a_measured_metric_beats_a_candidate_row_and_the_conflict_is_recorded():
    """Never averaged — that would invent a number no source reported."""
    rows = [
        discovery.candidate(name="Ada", handle="ada", platform="youtube", source="paste",
                            search_source="p1", followers=50000.0,
                            confidence=config.CONFIDENCE_CANDIDATE),
        discovery.candidate(name="Ada", handle="ada", platform="youtube", source="youtube",
                            search_source="p2", followers=61234.0,
                            confidence=config.CONFIDENCE_MEASURED),
    ]
    merged = discovery.merge(rows)[0]
    assert merged["followers"] == 61234.0
    assert merged["source_confidence"] == config.CONFIDENCE_MEASURED
    assert any("followers" in c for c in merged["metric_conflicts"])
    assert 55617.0 not in merged.values(), "the mean must never appear"


def test_creators_already_in_the_pool_are_not_reported_as_finds():
    known = [{"name": "Riley Brown", "platform": "youtube", "handle": "rileybrown"}]
    found = [
        discovery.candidate(name="Riley Brown", handle="rileybrown", platform="youtube",
                            source="s", search_source="p"),
        discovery.candidate(name="New Person", handle="newperson", platform="youtube",
                            source="s", search_source="p"),
    ]
    fresh, skipped = discovery.exclude_known(found, known)
    assert [c["name"] for c in fresh] == ["New Person"]
    assert skipped == 1


class _Unavailable:
    name = "paid_thing"

    def available(self):
        return False, "no API key configured"

    def search(self, brief):  # pragma: no cover - must never be called
        raise AssertionError("an unavailable source must not be searched")


def test_an_unavailable_source_is_reported_not_silently_skipped():
    """'No candidates' and 'no key' look identical in a list and are not the same."""
    result = discovery.run(config.DEFAULT_BRIEF, [_Unavailable()])
    assert result["counts"]["found"] == 0
    assert result["unavailable"] == [
        {"source": "paid_thing", "reason": "no API key configured"}
    ]
    assert result["counts"]["sources_unavailable"] == 1


def test_corroborated_candidates_rank_first():
    rows = [
        discovery.candidate(name="Solo", handle="solo", platform="tiktok",
                            source="s", search_source="p1"),
        discovery.candidate(name="Both", handle="both", platform="tiktok",
                            source="s", search_source="p1"),
        discovery.candidate(name="Both", handle="both", platform="tiktok",
                            source="s", search_source="p2"),
    ]

    class _Fixed:
        name = "fixed"

        def available(self):
            return True, ""

        def search(self, brief):
            return discovery.SourceResult(source="fixed", candidates=rows)

    result = discovery.run(config.DEFAULT_BRIEF, [_Fixed()])
    assert [c["name"] for c in result["candidates"]] == ["Both", "Solo"]


# ---------------------------------------------------------------------------
# The query plan
# ---------------------------------------------------------------------------
def test_the_plan_builds_real_urls_for_every_briefed_platform():
    plan = query_plan.build(config.DEFAULT_BRIEF)
    platforms = {q["platform"] for p in plan["passes"] for q in p["queries"]}
    assert {"tiktok", "instagram", "youtube"} <= platforms
    for p in plan["passes"]:
        for q in p["queries"]:
            assert q["url"].startswith("https://"), "a query must be clickable"


def test_every_term_says_where_it_came_from():
    plan = query_plan.build(config.DEFAULT_BRIEF)
    assert all(t["origin"] in {"brief", "spec"} for t in plan["terms"])
    assert {t["origin"] for t in plan["terms"]} == {"brief", "spec"}


def test_the_specs_seed_hashtags_are_used_for_the_campaign_they_were_written_for():
    plan = query_plan.build(config.DEFAULT_BRIEF)
    spec_terms = {t["term"].lower() for t in plan["terms"] if t["origin"] == "spec"}
    assert "aitools" in spec_terms and "studentlife" in spec_terms


def test_the_specs_hashtags_do_not_transfer_to_another_campaign():
    """Same non-transfer rule as readiness_category, for the same reason."""
    other = {**config.DEFAULT_BRIEF, "brand_name": "Ledgerly", "category": "Fintech apps"}
    plan = query_plan.build(other)
    assert all(t["origin"] == "brief" for t in plan["terms"])
    assert any("were written for" in n for n in plan["notes"]), "the mismatch is reported"


def test_the_plan_says_it_is_queries_not_results():
    plan = query_plan.build(config.DEFAULT_BRIEF)
    assert any("not results" in n for n in plan["notes"])


def test_the_competitor_pass_searches_every_exclusion():
    plan = query_plan.build(config.DEFAULT_BRIEF)
    pass2 = next(p for p in plan["passes"] if "competitor" in p["pass"])
    terms = {q["term"] for q in pass2["queries"]}
    assert {"Bubble", "Glide", "Adalo"} <= terms


def test_a_brief_with_no_known_platform_yields_no_pass_one_queries():
    plan = query_plan.build({**config.DEFAULT_BRIEF, "platforms": []})
    pass_names = [p["pass"] for p in plan["passes"]]
    assert not any("Pass 1" in n for n in pass_names)


# ---------------------------------------------------------------------------
# Paste-back
# ---------------------------------------------------------------------------
def test_pasted_handles_become_candidates():
    rows = query_plan.parse_pasted("@ada\nbo_lindqvist\n@cy.okafor", platform="tiktok")
    assert [r["handle"] for r in rows] == ["ada", "bo_lindqvist", "cy.okafor"]
    assert all(r["platform"] == "tiktok" for r in rows)


def test_a_pasted_profile_url_infers_its_own_platform():
    rows = query_plan.parse_pasted(
        "https://www.tiktok.com/@adavance\nhttps://www.youtube.com/@cyokafor"
    )
    assert {r["platform"] for r in rows} == {"tiktok", "youtube"}
    assert {r["handle"] for r in rows} == {"adavance", "cyokafor"}


def test_pasted_rows_carry_no_metrics():
    """A pasted handle is a lead, not a measurement."""
    rows = query_plan.parse_pasted("@ada", platform="tiktok")
    for metric in ("followers", "resonance_rate", "avg_views"):
        assert metric not in rows[0]
    assert rows[0]["source_confidence"] == config.CONFIDENCE_CANDIDATE


def test_a_bare_handle_with_no_platform_is_dropped_rather_than_guessed():
    """Without a platform the engine cannot pick a D3 instrument."""
    assert query_plan.parse_pasted("@ada\nbo", platform="") == []


def test_pasting_the_same_handle_twice_yields_one_row():
    rows = query_plan.parse_pasted("@ada\n@ada\nada", platform="tiktok")
    assert len(rows) == 1


def test_blank_lines_and_comments_are_ignored():
    rows = query_plan.parse_pasted(
        "# from Pass 1\n\n@ada\n\n  \n@bo", platform="tiktok"
    )
    assert [r["handle"] for r in rows] == ["ada", "bo"]


def test_the_query_plan_source_reports_that_it_produces_no_creators():
    result = query_plan.QueryPlanSource().search(config.DEFAULT_BRIEF)
    assert result.candidates == []
    assert any("a plan, not creators" in n for n in result.notes)


# ---------------------------------------------------------------------------
# YouTube — wired but inert, tested against a patched transport
# ---------------------------------------------------------------------------
def test_youtube_is_unavailable_without_a_key_and_says_so(monkeypatch):
    monkeypatch.setattr(config, "YOUTUBE_API_KEY", "")
    ok, why = youtube.YouTubeSource().available()
    assert ok is False
    assert "YOUTUBE_API_KEY" in why


def test_an_unkeyed_youtube_source_returns_nothing_rather_than_something_plausible(
    monkeypatch,
):
    monkeypatch.setattr(config, "YOUTUBE_API_KEY", "")
    result = discovery.run(config.DEFAULT_BRIEF, [youtube.YouTubeSource()])
    assert result["candidates"] == []
    assert result["unavailable"][0]["source"] == "youtube"


SEARCH_PAGE = {"items": [
    {"snippet": {"channelId": "UC_ada"}},
    {"snippet": {"channelId": "UC_bo"}},
    {"snippet": {"channelId": "UC_ada"}},   # same channel again
]}

CHANNELS_PAGE = {"items": [
    {
        "id": "UC_ada",
        "snippet": {"title": "Ada Vance", "customUrl": "@adavance",
                    "country": "US", "description": "I build apps"},
        "statistics": {"subscriberCount": "120000"},
        "contentDetails": {"relatedPlaylists": {"uploads": "UU_ada"}},
    },
    {
        "id": "UC_bo",
        "snippet": {"title": "Bo Hidden", "customUrl": "@bohidden"},
        "statistics": {},                     # channel hides its subscriber count
        "contentDetails": {"relatedPlaylists": {"uploads": "UU_bo"}},
    },
]}

PLAYLIST_PAGE = {"items": [{"contentDetails": {"videoId": f"v{i}"}} for i in range(5)]}
VIDEOS_PAGE = {"items": [{"statistics": {"viewCount": v}}
                         for v in ("10000", "12000", "14000", "16000", "1000000")]}


def _fake_transport(page_for):
    def _get(path, params, timeout=None):
        return page_for(path)
    return _get


@pytest.fixture()
def keyed(monkeypatch):
    monkeypatch.setattr(config, "YOUTUBE_API_KEY", "test-key-not-real")
    monkeypatch.setattr(youtube, "_get", _fake_transport(lambda path: {
        "search": SEARCH_PAGE,
        "channels": CHANNELS_PAGE,
        "playlistItems": PLAYLIST_PAGE,
        "videos": VIDEOS_PAGE,
    }[path]))


def test_youtube_returns_candidates_with_real_measured_metrics(keyed):
    result = youtube.YouTubeSource(terms=["ai tools for students"]).search(
        config.DEFAULT_BRIEF
    )
    ada = next(c for c in result.candidates if c["name"] == "Ada Vance")
    assert ada["followers"] == 120000.0
    assert ada["platform"] == "youtube"
    assert ada["source_confidence"] == config.CONFIDENCE_MEASURED


def test_the_resonance_rate_is_the_median_not_the_mean(keyed):
    """One viral video must not set the rate a sponsor is quoted against."""
    result = youtube.YouTubeSource(terms=["x"]).search(config.DEFAULT_BRIEF)
    ada = next(c for c in result.candidates if c["name"] == "Ada Vance")
    # median of 10k/12k/14k/16k/1M is 14000 -> 14000/120000 = 11.67%
    assert ada["resonance_rate"] == 11.67
    assert ada["avg_views"] == 14000.0


def test_the_rate_is_reproducible_from_the_columns_stored_beside_it(keyed):
    """Unlike the three rate_reproducible: false rows in the bundled data."""
    result = youtube.YouTubeSource(terms=["x"]).search(config.DEFAULT_BRIEF)
    ada = next(c for c in result.candidates if c["name"] == "Ada Vance")
    assert ada["rate_reproducible"] is True
    assert ada["followers_scope"] == "youtube", "single-platform denominator"
    assert round(ada["avg_views"] / ada["followers"] * 100, 2) == ada["resonance_rate"]


def test_a_hidden_subscriber_count_stays_absent_and_never_becomes_zero(keyed):
    """Hidden is not zero, and zero is the most consequential lie in the model."""
    result = youtube.YouTubeSource(terms=["x"]).search(config.DEFAULT_BRIEF)
    bo = next(c for c in result.candidates if c["name"] == "Bo Hidden")
    assert "followers" not in bo
    assert "resonance_rate" not in bo, "no denominator means no rate, not a rate of 0"
    assert bo["source_confidence"] == config.CONFIDENCE_CANDIDATE


def test_a_channel_with_no_subscriber_count_scores_as_needs_refresh(keyed):
    result = youtube.YouTubeSource(terms=["x"]).search(config.DEFAULT_BRIEF)
    bo = next(c for c in result.candidates if c["name"] == "Bo Hidden")
    scored = scorer.score_creator(
        scorer.normalise_creator(bo), scorer.lock_criteria(config.DEFAULT_BRIEF)
    )
    assert scored["status"] == scorer.STATUS_REFRESH


def test_duplicate_channels_across_search_results_are_fetched_once(keyed):
    result = youtube.YouTubeSource(terms=["x"]).search(config.DEFAULT_BRIEF)
    assert len(result.candidates) == 2, "UC_ada appeared twice in the search page"


# ---------------------------------------------------------------------------
# Quota — the binding constraint
# ---------------------------------------------------------------------------
def test_a_search_costs_a_hundred_units_and_enrichment_costs_one():
    budget = youtube.QuotaBudget()
    budget.charge("search")
    assert budget.spent == 100
    budget.charge("channels")
    assert budget.spent == 101


def test_a_run_stops_inside_its_budget_rather_than_being_stopped_by_google(keyed):
    """Hitting the quota mid-run yields a partial list that looks complete."""
    budget = youtube.QuotaBudget(limit=250)      # affords 2 searches, not 5
    result = youtube.YouTubeSource(terms=["a", "b", "c", "d", "e"], budget=budget).search(
        config.DEFAULT_BRIEF
    )
    assert result.truncated is True
    assert any("stopped after 2 of 5 searches" in n for n in result.notes)
    assert budget.spent <= 250


def test_a_truncated_run_says_so_in_the_result_dict(keyed):
    budget = youtube.QuotaBudget(limit=100)
    result = youtube.YouTubeSource(terms=["a", "b"], budget=budget).search(
        config.DEFAULT_BRIEF
    )
    assert result.as_dict()["truncated"] is True
    assert result.as_dict()["quota_spent"] > 0


def test_quota_exhaustion_surfaces_as_an_error_not_an_empty_result(monkeypatch):
    """A 403 means 'ask again tomorrow', which is not the same as 'nobody matched'."""
    import urllib.error
    import urllib.request

    monkeypatch.setattr(config, "YOUTUBE_API_KEY", "k")

    # Patched at the transport, not at _get, so the real error-conversion path
    # is what gets exercised.
    def _boom(request, timeout=None):
        raise urllib.error.HTTPError("u", 403, "Forbidden", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    result = discovery.run(config.DEFAULT_BRIEF, [youtube.YouTubeSource(terms=["x"])])
    assert result["candidates"] == []
    assert "quota exceeded" in result["unavailable"][0]["reason"]


def test_a_source_that_raises_an_unexpected_error_does_not_kill_the_whole_run():
    """One broken adapter must not take the other sources down with it."""

    class _Broken:
        name = "broken"

        def available(self):
            return True, ""

        def search(self, brief):
            raise ValueError("something nobody predicted")

    class _Fine:
        name = "fine"

        def available(self):
            return True, ""

        def search(self, brief):
            return discovery.SourceResult(source="fine", candidates=[
                discovery.candidate(name="Ada", handle="ada", platform="tiktok",
                                    source="fine", search_source="p")
            ])

    result = discovery.run(config.DEFAULT_BRIEF, [_Broken(), _Fine()])
    assert [c["name"] for c in result["candidates"]] == ["Ada"], "the good source ran"
    assert result["unavailable"][0]["source"] == "broken"
    assert "something nobody predicted" in result["unavailable"][0]["reason"]


def test_the_spec_terms_are_search_terms_not_method_prose():
    """Step 2 quotes how to search as well as what to search for.

    "related channels", "similar accounts" and "I post about" describe a method.
    Sending an operator to search for them looks thorough and finds nothing.
    """
    plan = query_plan.build(config.DEFAULT_BRIEF)
    spec_phrases = {
        t["term"].lower() for t in plan["terms"]
        if t["origin"] == "spec" and not t.get("hashtag")
    }
    for prose in ("related channels", "similar accounts", "i post about",
                  "student creator", "tiktok creator"):
        assert prose not in spec_phrases, f"{prose!r} is method prose, not a search term"
    assert "ai tools for students" in spec_phrases, "the real keywords survive"


def test_no_term_is_an_unfilled_template_placeholder():
    """The spec contains "[brand] + #ad" as a template. It is not a query."""
    plan = query_plan.build(config.DEFAULT_BRIEF)
    for term in plan["terms"]:
        assert "[" not in term["term"] and "]" not in term["term"], term["term"]


def test_derived_terms_do_not_include_bare_audience_adjectives():
    """"aged 18-24" once produced "AI app-building tools for aged"."""
    plan = query_plan.build(config.DEFAULT_BRIEF)
    terms = {t["term"].lower() for t in plan["terms"]}
    for junk in ("ai app-building tools for aged", "aged", "whose", "skews"):
        assert junk not in terms


def test_every_query_url_is_well_formed():
    import urllib.parse

    plan = query_plan.build(config.DEFAULT_BRIEF)
    for group in plan["passes"]:
        for query in group["queries"]:
            parsed = urllib.parse.urlparse(query["url"])
            assert parsed.scheme == "https" and parsed.netloc
            assert " " not in query["url"], "spaces must be percent-encoded"
