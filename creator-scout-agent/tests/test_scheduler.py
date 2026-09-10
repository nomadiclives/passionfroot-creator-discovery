"""Scheduler tests.

The loop's value is that a scheduled roster and a hand-built one are the same
artifact. These tests hold that, plus the next-run arithmetic and the failure
modes that must not take a whole pass down.

Every test writes state and reports into tmp_path — the suite never touches
`data/schedule_state.json` or `reports/`.
"""

import csv
import datetime as dt
import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import scheduler
import scorer


@pytest.fixture(autouse=True)
def quiet_logging():
    scheduler.configure_logging(verbose=False)


@pytest.fixture()
def state_file(tmp_path):
    return str(tmp_path / "schedule_state.json")


@pytest.fixture()
def reports_dir(tmp_path, monkeypatch):
    path = tmp_path / "reports"
    path.mkdir()
    monkeypatch.setattr(config, "REPORTS_DIR", str(path))
    return path


# ---------------------------------------------------------------------------
# Pipeline intel
# ---------------------------------------------------------------------------
def test_pipeline_intel_loads_the_checked_in_file():
    campaigns = scheduler.load_pipeline_intel()
    assert campaigns
    assert any(c["id"] == "craftly-students" for c in campaigns)
    for campaign in campaigns:
        assert campaign["category"], "a campaign with no category cannot assign roles"


def test_fictional_pipeline_entries_are_labelled_as_such():
    """Illustrative briefs must never read as real pipeline."""
    for campaign in scheduler.load_pipeline_intel():
        if campaign["brand_name"].startswith("Fictional"):
            assert campaign["status"] == "example"


def test_missing_pipeline_is_an_empty_pipeline_not_a_crash(tmp_path):
    assert scheduler.load_pipeline_intel(str(tmp_path / "nope.json")) == []


def test_malformed_pipeline_is_survivable(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert scheduler.load_pipeline_intel(str(bad)) == []


def test_brief_from_campaign_fills_gaps_from_the_campaign_slot():
    brief = scheduler.brief_from_campaign({"brand_name": "X", "category": "widgets"})
    assert brief["brand_name"] == "X"
    assert brief["category"] == "widgets"
    # Untouched keys still come from the default slot.
    assert brief["target_audience"] == config.DEFAULT_BRIEF["target_audience"]


# ---------------------------------------------------------------------------
# Next-run arithmetic
# ---------------------------------------------------------------------------
def test_daily_rolls_to_tomorrow_once_the_time_has_passed():
    morning = dt.datetime(2026, 9, 10, 8, 0)
    evening = dt.datetime(2026, 9, 10, 18, 0)
    assert scheduler.next_run_at("daily", morning, run_time="09:00").day == 10
    assert scheduler.next_run_at("daily", evening, run_time="09:00").day == 11


def test_weekly_lands_on_the_configured_day():
    # 2026-09-10 is a Thursday.
    nxt = scheduler.next_run_at("weekly", dt.datetime(2026, 9, 10, 12, 0),
                                run_day="monday", run_time="09:00")
    assert nxt.weekday() == 0
    assert (nxt.date() - dt.date(2026, 9, 10)).days == 4


def test_weekly_skips_today_if_the_time_already_passed():
    monday_afternoon = dt.datetime(2026, 9, 14, 15, 0)
    nxt = scheduler.next_run_at("weekly", monday_afternoon,
                                run_day="monday", run_time="09:00")
    assert nxt.date() == dt.date(2026, 9, 21)


def test_biweekly_is_anchored_to_the_last_actual_run():
    """Biweekly means every other run day, and it survives a restart."""
    now = dt.datetime(2026, 9, 10, 12, 0)
    recent = dt.datetime(2026, 9, 7, 9, 0)   # last Monday
    soon = scheduler.next_run_at("biweekly", now, run_day="monday", last_run=recent)
    assert soon.date() == dt.date(2026, 9, 21), "must skip the intervening Monday"

    old = dt.datetime(2026, 8, 24, 9, 0)
    due = scheduler.next_run_at("biweekly", now, run_day="monday", last_run=old)
    assert due.date() == dt.date(2026, 9, 14)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
def test_state_round_trips_and_defaults_are_sane(state_file):
    state = scheduler.read_state(state_file)
    assert state["cadence"] == config.DEFAULT_CADENCE
    assert state["last_run"] is None

    state["cadence"] = "daily"
    scheduler.write_state(state, state_file)
    assert scheduler.read_state(state_file)["cadence"] == "daily"


def test_unknown_cadence_is_refused(state_file):
    with pytest.raises(ValueError):
        scheduler.set_cadence("fortnightly", state_file)


def test_corrupt_state_falls_back_to_defaults(state_file):
    with open(state_file, "w", encoding="utf-8") as fh:
        fh.write("{{{")
    assert scheduler.read_state(state_file)["cadence"] == config.DEFAULT_CADENCE


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------
def test_run_once_writes_a_dated_roster_and_records_state(reports_dir, state_file):
    when = dt.datetime(2026, 9, 10, 9, 0)
    summary = scheduler.run_once(state_path=state_file, when=when)

    assert summary["status"] == "ok"
    report = reports_dir / "soft_roster_2026-09-10.csv"
    assert report.exists()

    state = scheduler.read_state(state_file)
    assert state["last_run"] == "2026-09-10T09:00:00"
    assert state["last_status"] == "ok"
    assert state["history"]


def test_the_roster_names_the_campaign_on_every_row(reports_dir, state_file):
    scheduler.run_once(state_path=state_file, when=dt.datetime(2026, 9, 10, 9, 0))
    text = (reports_dir / "soft_roster_2026-09-10.csv").read_text(encoding="utf-8")
    rows = list(csv.reader(io.StringIO(text)))

    assert rows[0][:2] == ["Campaign", "Brand"]
    campaigns = {row[0] for row in rows[1:]}
    assert "craftly-students" in campaigns
    assert len(campaigns) == len(scheduler.load_pipeline_intel())


def test_a_scheduled_roster_matches_a_hand_built_one(reports_dir, state_file):
    """The loop must run the same engine, not a parallel one."""
    scheduler.run_once(state_path=state_file, when=dt.datetime(2026, 9, 10, 9, 0))
    rows = list(csv.reader(io.StringIO(
        (reports_dir / "soft_roster_2026-09-10.csv").read_text(encoding="utf-8")
    )))
    craftly = [r for r in rows[1:] if r[0] == "craftly-students"]

    expected = scorer.build_shortlist(config.DEFAULT_BRIEF, config.CREATOR_DATA)
    assert len(craftly) == len(expected["table"])
    # Rank, name and score, in the same order.
    for row, creator in zip(craftly, expected["table"]):
        assert row[3] == creator["name"]
        assert row[2] == (str(creator["rank"]) if creator.get("rank") else "")


def test_a_campaign_in_an_unjudged_category_yields_review_not_invented_roles(
    reports_dir, state_file
):
    summary = scheduler.run_once(state_path=state_file, when=dt.datetime(2026, 9, 10, 9, 0))
    by_id = {c["id"]: c for c in summary["campaigns"]}

    craftly = by_id["craftly-students"]
    assert craftly["shortlisted"] == 17

    hardware = by_id["example-study-hardware"]
    assert hardware["shortlisted"] == 0
    assert hardware["needs_review"] == 18, (
        "a different category must return the pool for re-judgement rather than "
        "reusing readiness judged against AI app-building tools"
    )


def test_an_empty_pipeline_is_recorded_not_crashed(tmp_path, reports_dir, state_file):
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"campaigns": []}), encoding="utf-8")
    summary = scheduler.run_once(pipeline=str(empty), state_path=state_file)
    assert summary["status"] == "empty"
    assert summary["report"] is None
    assert scheduler.read_state(state_file)["last_status"] == "empty"


def test_one_bad_campaign_does_not_kill_the_pass(tmp_path, reports_dir, state_file,
                                                 monkeypatch):
    pipeline = tmp_path / "pipeline.json"
    pipeline.write_text(json.dumps({"campaigns": [
        {"id": "boom", "brand_name": "Boom", "category": "x"},
        {"id": "craftly-students", **config.DEFAULT_BRIEF},
    ]}), encoding="utf-8")

    real = scorer.build_shortlist

    def explode(brief, creators):
        if brief.get("brand_name") == "Boom":
            raise RuntimeError("bad brief")
        return real(brief, creators)

    monkeypatch.setattr(scorer, "build_shortlist", explode)
    summary = scheduler.run_once(pipeline=str(pipeline), state_path=state_file,
                                 when=dt.datetime(2026, 9, 10, 9, 0))

    statuses = {c["id"]: c["status"] for c in summary["campaigns"]}
    assert statuses["boom"] == "error"
    assert statuses["craftly-students"] == "ok"
    assert summary["status"] == "ok"


def test_status_reports_everything_the_console_needs(state_file):
    state = scheduler.status(state_file)
    for key in ("cadence", "cadences", "run_day", "run_time", "last_run",
                "next_run", "pipeline", "history"):
        assert key in state
    assert state["cadence"] in config.CADENCES


def test_cli_once_runs_and_returns_zero(reports_dir, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SCHEDULE_STATE", str(tmp_path / "state.json"))
    assert scheduler.main(["--once"]) == 0
