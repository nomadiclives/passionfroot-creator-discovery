"""Soft-roster discovery loop.

A Creator Partnership Manager's pipeline is known days before a brief is
signed. This loop reads that pipeline (`data/pipeline_intel.json`), runs each
upcoming campaign through the scoring engine, and leaves a dated soft roster in
`reports/` so the shortlist exists before anyone asks for it.

    python scheduler.py --once      one pass now, then exit
    python scheduler.py             blocking loop, default Monday 09:00

The loop invents nothing. It runs the same `scorer.build_shortlist()` the web
app runs, against the same sourced data, so a scheduled roster and a roster
produced by hand from the UI are the same artifact.

One consequence worth naming: readiness is judged against a NAMED category, so
running a campaign in a different category against the same pool returns
NEEDS_REVIEW rows rather than roles. That is correct — a readiness call about
"AI app-building tools" is not evidence about a tablet — and it shows up in the
run summary as `needs_review`, not as a failure.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import logging
import os
import sys
from typing import Any

import config
import scorer

LOGGER = logging.getLogger("scheduler")

WEEKDAYS = (
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def configure_logging(verbose: bool = True) -> logging.Logger:
    """File log always; console log when run interactively."""
    os.makedirs(config.LOGS_DIR, exist_ok=True)
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()

    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s")
    file_handler = logging.FileHandler(config.SCHEDULER_LOG, encoding="utf-8")
    file_handler.setFormatter(fmt)
    LOGGER.addHandler(file_handler)

    if verbose:
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(fmt)
        LOGGER.addHandler(stream)
    return LOGGER


# ---------------------------------------------------------------------------
# Pipeline intel
# ---------------------------------------------------------------------------
def load_pipeline_intel(path: str | None = None) -> list[dict]:
    """Upcoming campaign briefs. Missing or malformed file -> empty pipeline.

    An empty pipeline is a real state (nothing booked), not an error, so it
    returns [] rather than raising — the console then says "no campaigns" and
    the operator knows to add one.
    """
    path = path or config.PIPELINE_INTEL
    if not os.path.exists(path):
        LOGGER.warning("no pipeline intel at %s — nothing to pre-build", path)
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        LOGGER.error("pipeline intel unreadable (%s) — skipping this pass", exc)
        return []

    campaigns = doc.get("campaigns", []) if isinstance(doc, dict) else doc
    return [c for c in campaigns if isinstance(c, dict) and c.get("brand_name")]


def brief_from_campaign(campaign: dict) -> dict:
    """A pipeline entry -> the brief dict build_shortlist expects."""
    brief = {**config.DEFAULT_BRIEF}
    for key in (
        "brand_name",
        "product_description",
        "category",
        "campaign_goal",
        "target_audience",
        "platforms",
        "cpm",
        "follower_band",
        "shortlist_size",
        "exclusions",
    ):
        if campaign.get(key) not in (None, ""):
            brief[key] = campaign[key]
    return brief


# ---------------------------------------------------------------------------
# Schedule state — what the console reads
# ---------------------------------------------------------------------------
def default_state() -> dict:
    return {
        "cadence": config.DEFAULT_CADENCE,
        "run_day": config.DEFAULT_RUN_DAY,
        "run_time": config.DEFAULT_RUN_TIME,
        "last_run": None,
        "last_status": None,
        "last_report": None,
        "last_summary": [],
        "history": [],
    }


def read_state(path: str | None = None) -> dict:
    path = path or config.SCHEDULE_STATE
    state = default_state()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                stored = json.load(fh)
            if isinstance(stored, dict):
                state.update(stored)
        except (json.JSONDecodeError, OSError) as exc:
            LOGGER.error("schedule state unreadable (%s) — using defaults", exc)
    if state.get("cadence") not in config.CADENCES:
        state["cadence"] = config.DEFAULT_CADENCE
    return state


def write_state(state: dict, path: str | None = None) -> dict:
    path = path or config.SCHEDULE_STATE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
        fh.write("\n")
    return state


def set_cadence(cadence: str, path: str | None = None) -> dict:
    if cadence not in config.CADENCES:
        raise ValueError(f"unknown cadence {cadence!r}; expected one of {config.CADENCES}")
    state = read_state(path)
    state["cadence"] = cadence
    return write_state(state, path)


# ---------------------------------------------------------------------------
# Next-run arithmetic
# ---------------------------------------------------------------------------
def _parse_time(value: str) -> dt.time:
    try:
        hour, minute = (int(p) for p in str(value).split(":")[:2])
        return dt.time(hour, minute)
    except (ValueError, TypeError):
        return dt.time(9, 0)


def next_run_at(
    cadence: str,
    now: dt.datetime | None = None,
    run_day: str = config.DEFAULT_RUN_DAY,
    run_time: str = config.DEFAULT_RUN_TIME,
    last_run: dt.datetime | None = None,
) -> dt.datetime:
    """When the next pass is due. Pure arithmetic, so it is testable."""
    now = now or dt.datetime.now()
    at = _parse_time(run_time)
    today_at = dt.datetime.combine(now.date(), at)

    if cadence == "daily":
        return today_at if today_at > now else today_at + dt.timedelta(days=1)

    target = WEEKDAYS.index(str(run_day).lower()) if str(run_day).lower() in WEEKDAYS else 0
    ahead = (target - now.weekday()) % 7
    candidate = dt.datetime.combine(now.date() + dt.timedelta(days=ahead), at)
    if candidate <= now:
        candidate += dt.timedelta(days=7)

    if cadence == "biweekly":
        # Biweekly means every OTHER run day. Anchored to the last actual run so
        # the cadence survives a restart rather than resetting to "next week".
        if last_run is not None and (candidate - last_run).days < 14:
            candidate += dt.timedelta(days=7)
    return candidate


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------
SOFT_ROSTER_COLUMNS = [("campaign", "Campaign"), ("brand", "Brand")] + list(
    scorer.EXPORT_COLUMNS
)


def _roster_rows(campaign: dict, result: dict) -> list[list[Any]]:
    rows = []
    for creator in result["table"]:
        row = [campaign.get("id") or campaign.get("brand_name"), campaign.get("brand_name")]
        for key, _ in scorer.EXPORT_COLUMNS:
            if key == "platforms_csv":
                row.append(" / ".join(creator.get("platforms_display", [])))
            elif key in {"budget", "expected_views"}:
                row.append(creator.get("cpm", {}).get(key) or "")
            else:
                value = creator.get(key)
                row.append("" if value is None else value)
        rows.append(row)
    return rows


def soft_roster_csv(runs: list[tuple[dict, dict]]) -> str:
    """One CSV across every campaign in the pass, campaign named on each row."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([label for _, label in SOFT_ROSTER_COLUMNS])
    for campaign, result in runs:
        for row in _roster_rows(campaign, result):
            writer.writerow(row)
    return out.getvalue()


def report_path(when: dt.date | None = None) -> str:
    when = when or dt.date.today()
    return os.path.join(config.REPORTS_DIR, f"soft_roster_{when.isoformat()}.csv")


def run_once(
    creators: str | None = None,
    pipeline: str | None = None,
    state_path: str | None = None,
    when: dt.datetime | None = None,
) -> dict:
    """One discovery pass. Returns the run summary the console renders."""
    when = when or dt.datetime.now()
    campaigns = load_pipeline_intel(pipeline)
    if not campaigns:
        LOGGER.warning("pipeline empty — no soft roster written")
        summary = {
            "ran_at": when.isoformat(timespec="seconds"),
            "status": "empty",
            "campaigns": [],
            "report": None,
        }
        state = read_state(state_path)
        state.update(
            last_run=summary["ran_at"], last_status="empty",
            last_report=None, last_summary=[],
        )
        state["history"] = ([summary] + list(state.get("history", [])))[:10]
        write_state(state, state_path)
        return summary

    source = creators or config.CREATOR_DATA
    runs: list[tuple[dict, dict]] = []
    per_campaign = []

    for campaign in campaigns:
        name = campaign.get("brand_name")
        try:
            result = scorer.build_shortlist(brief_from_campaign(campaign), source)
        except Exception as exc:  # a bad brief must not kill the whole pass
            LOGGER.exception("%s failed: %s", name, exc)
            per_campaign.append(
                {
                    "id": campaign.get("id"),
                    "brand_name": name,
                    "category": campaign.get("category"),
                    "status": "error",
                    "error": str(exc),
                }
            )
            continue

        runs.append((campaign, result))
        counts = result["counts"]
        per_campaign.append(
            {
                "id": campaign.get("id"),
                "brand_name": name,
                "category": campaign.get("category"),
                "pipeline_status": campaign.get("status"),
                "status": "ok",
                "shortlisted": counts["shortlisted"],
                "evaluated": counts["evaluated"],
                "needs_refresh": counts["needs_refresh"],
                "needs_review": counts["needs_review"],
                "needs_calibration": counts["needs_calibration"],
                "dropped": counts["dropped"],
                "composition": {
                    role: data["count"]
                    for role, data in result["composition"]["by_role"].items()
                },
            }
        )
        LOGGER.info(
            "%s (%s): %s shortlisted of %s evaluated "
            "[refresh %s / review %s / calibration %s / dropped %s]",
            name, campaign.get("category"),
            counts["shortlisted"], counts["evaluated"], counts["needs_refresh"],
            counts["needs_review"], counts["needs_calibration"], counts["dropped"],
        )

    path = report_path(when.date())
    os.makedirs(config.REPORTS_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(soft_roster_csv(runs))
    LOGGER.info("soft roster written: %s", path)

    summary = {
        "ran_at": when.isoformat(timespec="seconds"),
        "status": "ok" if runs else "error",
        "campaigns": per_campaign,
        "report": os.path.relpath(path, config.BASE_DIR),
    }

    state = read_state(state_path)
    state.update(
        last_run=summary["ran_at"],
        last_status=summary["status"],
        last_report=summary["report"],
        last_summary=per_campaign,
    )
    state["history"] = ([summary] + list(state.get("history", [])))[:10]
    write_state(state, state_path)
    return summary


# ---------------------------------------------------------------------------
# Blocking loop
# ---------------------------------------------------------------------------
def start(cadence: str | None = None, poll_seconds: int = 30) -> None:
    """Register the job with `schedule` and block. Ctrl-C to stop."""
    import time

    import schedule as schedule_lib

    state = read_state()
    cadence = cadence or state.get("cadence") or config.DEFAULT_CADENCE
    if cadence not in config.CADENCES:
        raise ValueError(f"unknown cadence {cadence!r}")
    state["cadence"] = cadence
    write_state(state)

    at = state.get("run_time") or config.DEFAULT_RUN_TIME
    day = (state.get("run_day") or config.DEFAULT_RUN_DAY).lower()

    schedule_lib.clear()
    if cadence == "daily":
        schedule_lib.every().day.at(at).do(run_once)
    else:
        # `schedule` has no biweekly primitive. Register weekly and let the job
        # itself skip the off week, so the cadence stays anchored to real runs
        # rather than to process start.
        getattr(schedule_lib.every(), day).at(at).do(_weekly_job, cadence)

    LOGGER.info(
        "scheduler started — cadence=%s, next run %s",
        cadence,
        next_run_at(cadence, run_day=day, run_time=at).isoformat(timespec="minutes"),
    )
    try:
        while True:
            schedule_lib.run_pending()
            time.sleep(poll_seconds)
    except KeyboardInterrupt:
        LOGGER.info("scheduler stopped")


def _weekly_job(cadence: str) -> None:
    """Weekly tick. On biweekly, skip if the last run was under 13 days ago."""
    if cadence == "biweekly":
        state = read_state()
        last = state.get("last_run")
        if last:
            try:
                since = dt.datetime.now() - dt.datetime.fromisoformat(last)
                if since.days < 13:
                    LOGGER.info("biweekly: %s days since last run — skipping", since.days)
                    return
            except ValueError:
                pass
    run_once()


def status(state_path: str | None = None) -> dict:
    """What the /schedule console and /api/schedule endpoint render."""
    state = read_state(state_path)
    cadence = state.get("cadence", config.DEFAULT_CADENCE)
    last_run = state.get("last_run")
    last_dt = None
    if last_run:
        try:
            last_dt = dt.datetime.fromisoformat(last_run)
        except ValueError:
            last_dt = None
    upcoming = next_run_at(
        cadence,
        run_day=state.get("run_day", config.DEFAULT_RUN_DAY),
        run_time=state.get("run_time", config.DEFAULT_RUN_TIME),
        last_run=last_dt,
    )
    return {
        "cadence": cadence,
        "cadences": list(config.CADENCES),
        "run_day": state.get("run_day", config.DEFAULT_RUN_DAY),
        "run_time": state.get("run_time", config.DEFAULT_RUN_TIME),
        "last_run": last_run,
        "last_status": state.get("last_status"),
        "last_report": state.get("last_report"),
        "last_summary": state.get("last_summary", []),
        "next_run": upcoming.isoformat(timespec="minutes"),
        "history": state.get("history", []),
        "pipeline": [
            {
                "id": c.get("id"),
                "brand_name": c.get("brand_name"),
                "category": c.get("category"),
                "status": c.get("status"),
                "brief_received": c.get("brief_received"),
            }
            for c in load_pipeline_intel()
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Creator Scout soft-roster scheduler")
    parser.add_argument("--once", action="store_true", help="run one pass and exit")
    parser.add_argument("--cadence", choices=config.CADENCES, help="override the cadence")
    parser.add_argument("--status", action="store_true", help="print schedule state as JSON")
    args = parser.parse_args(argv)

    configure_logging()

    if args.status:
        print(json.dumps(status(), indent=2))
        return 0
    if args.cadence and not args.once:
        set_cadence(args.cadence)
    if args.once:
        summary = run_once()
        print(json.dumps(summary, indent=2))
        return 0 if summary["status"] in {"ok", "empty"} else 1

    start(args.cadence)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
