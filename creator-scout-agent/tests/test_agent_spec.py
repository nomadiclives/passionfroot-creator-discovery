"""The agent spec is checked in and loadable — the app scores against a visible spec."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_spec
import config


def test_spec_is_checked_into_the_repo():
    assert agent_spec.exists(), "agents/creator-campaign-scout.md is missing"
    assert os.path.getsize(config.SPEC_FILE) > 10_000


def test_frontmatter_identifies_the_skill():
    assert agent_spec.frontmatter().get("name") == "creator-campaign-scout"


def test_campaign_slot_parses():
    slot = agent_spec.campaign_slot()
    assert slot["CAMPAIGN"] == "Craftly for Students"
    assert slot["PLATFORMS"] == "TikTok, Instagram, YouTube"
    assert "$50 CPM" in slot["BUDGET MODEL"]
    assert "15-20" in slot["SHORTLIST SIZE"]


def test_hard_rules_are_extracted():
    rules = agent_spec.hard_rules()
    assert len(rules) >= 8
    assert any("Never fabricate creator metrics" in r for r in rules)
    assert any("D1/D2" in r for r in rules)


def test_config_weights_still_agree_with_the_spec():
    """Fails loudly if config.py drifts from the spec it claims to implement."""
    assert agent_spec.check_weights_documented()


def test_summary_is_renderable():
    summary = agent_spec.summary()
    assert summary["available"] is True
    assert summary["weights_match_spec"] is True
    assert summary["path"] == "agents/creator-campaign-scout.md"
    assert len(summary["sections"]) >= 10
