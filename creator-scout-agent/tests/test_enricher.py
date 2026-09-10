"""Enrichment stub tests.

The hard rule is that a metric is never invented. Enrichment is the one place
that could quietly break it — a failed call is exactly the moment a plausible
default is tempting. These tests hold the three outcomes:

    off      -> pass through, source stays manual
    success  -> merge only what came back, never overwrite an audited value
    failure  -> keep manual values and flag UNVERIFIED

No test here touches the network.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import enricher


@pytest.fixture()
def enabled(monkeypatch):
    monkeypatch.setattr(config, "ENRICHMENT_ENABLED", True)
    monkeypatch.setattr(config, "API_KEY", "test-key")
    monkeypatch.setattr(config, "API_PROVIDER", "favikon")


def test_disabled_by_default():
    assert config.ENRICHMENT_ENABLED is False
    assert config.API_KEY == "", "never commit a real API key"
    assert enricher.is_enabled() is False


def test_a_toggle_without_a_key_stays_off(monkeypatch):
    monkeypatch.setattr(config, "ENRICHMENT_ENABLED", True)
    monkeypatch.setattr(config, "API_KEY", "")
    assert enricher.is_enabled() is False


def test_inert_when_off_and_marks_the_source_manual():
    row = {"name": "A", "followers": None, "platforms": ["tiktok"]}
    out = enricher.apply_enrichment(row)
    assert out["followers"] is None, "an absent metric stays absent"
    assert out["source"] == "manual"
    assert out["flags"] == []


def test_enrich_creator_returns_nothing_when_off():
    assert enricher.enrich_creator("someone", "tiktok") == {}


def test_a_successful_call_fills_only_the_gaps(enabled, monkeypatch):
    monkeypatch.setattr(enricher, "_request", lambda url: {
        "follower_count": 120000,
        "average_views": 41000,
        "view_rate": 34.2,
    })
    row = {
        "name": "A", "handle": "@a", "platforms": ["tiktok"],
        "followers": 99000,          # audited — must survive
        "avg_views": None,           # gap — must be filled
        "source": "manual",
    }
    out = enricher.apply_enrichment(row)

    assert out["followers"] == 99000, "an audited value must not be overwritten"
    assert out["avg_views"] == 41000
    assert out["source"] == "favikon"
    assert set(out["enriched_fields"]) == {"avg_views", "resonance_rate"}


def test_a_failed_call_flags_unverified_and_invents_nothing(enabled, monkeypatch):
    def boom(url):
        raise OSError("connection reset")

    monkeypatch.setattr(enricher, "_request", boom)
    row = {"name": "A", "handle": "@a", "platforms": ["tiktok"],
           "followers": None, "source": "manual"}
    out = enricher.apply_enrichment(row)

    assert out["followers"] is None, "a failed call must not produce a number"
    assert enricher.FLAG_UNVERIFIED in out["flags"]
    assert out["source"] == "manual"
    assert "connection reset" in out["enrichment_error"]


def test_unrecognised_provider_fields_are_dropped(enabled, monkeypatch):
    monkeypatch.setattr(enricher, "_request", lambda url: {
        "follower_count": 1000,
        "vibe_score": 11,          # not in our schema
        "average_views": "n/a",    # unparseable -> missing, not zero
    })
    out = enricher.enrich_creator("@a", "tiktok")
    assert out == {"followers": 1000.0}
    assert "vibe_score" not in out


def test_a_wrapped_payload_is_unwrapped(enabled, monkeypatch):
    monkeypatch.setattr(enricher, "_request", lambda url: {
        "data": {"follower_count": 5000}
    })
    assert enricher.enrich_creator("@a", "tiktok") == {"followers": 5000.0}


def test_an_unexpected_shape_is_an_error_not_a_silent_empty(enabled, monkeypatch):
    monkeypatch.setattr(enricher, "_request", lambda url: ["nope"])
    with pytest.raises(enricher.EnrichmentError):
        enricher.enrich_creator("@a", "tiktok")


def test_an_unknown_provider_is_an_error(enabled, monkeypatch):
    monkeypatch.setattr(config, "API_PROVIDER", "nonesuch")
    with pytest.raises(enricher.EnrichmentError):
        enricher.enrich_creator("@a", "tiktok")


def test_the_endpoint_carries_the_handle_and_platform(enabled):
    url = enricher._endpoint("@a", "tiktok")
    assert url.startswith(config.API_BASE_URLS["favikon"])
    assert "handle=%40a" in url
    assert "platform=tiktok" in url


def test_build_shortlist_runs_the_enricher_when_the_toggle_is_on(enabled, monkeypatch):
    """The import in build_shortlist must resolve — this is what used to fail."""
    import scorer

    monkeypatch.setattr(enricher, "_request", lambda url: {})
    result = scorer.build_shortlist(config.DEFAULT_BRIEF, config.CREATOR_DATA)
    assert result["counts"]["evaluated"] > 0
