"""Flask API and server-rendered UI for the Creator Campaign Scout Agent.

Two screens and a console:

    GET  /                 Screen 1 — the campaign brief form
    POST /shortlist        Screen 2 — the scored, role-assigned shortlist
    POST /export.csv       the same shortlist as a CSV download
    GET  /schedule         the schedule console (JSON on Accept: application/json)
    GET  /api/schedule     schedule state as JSON, always
    POST /schedule/run     run one discovery pass now
    POST /schedule/cadence set daily / weekly / biweekly
    GET  /api/shortlist    the shortlist as JSON, for anything not a browser
    GET  /healthz          liveness

There is no session and no database. Screen 2 and the CSV export are both pure
functions of the submitted form, so exporting re-runs the same brief through the
same engine and cannot drift from what the screen showed.

The UI's job is to make the engine's refusals legible. Every creator the engine
evaluated is rendered — Keep, Drop, NEEDS_REFRESH, NEEDS_REVIEW and
NEEDS_CALIBRATION alike, each with its reason. A creator never silently
disappears, because a disappeared creator looks like one that was never
sourced.
"""

from __future__ import annotations

import re

import agent_spec
import config
import scheduler
import scorer
from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from markupsafe import Markup, escape

app = Flask(__name__)


@app.template_filter("inline_md")
def inline_md(text: str) -> Markup:
    """Render the spec's inline markdown — **bold** and `code` — as HTML.

    The spec is markdown on disk and is quoted into the UI verbatim, so the
    marker characters would otherwise show up as literal asterisks. Escaped
    first, so spec text can never inject markup.
    """
    escaped = str(escape(text or ""))
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"`([^`]+?)`", r"<code>\1</code>", escaped)
    return Markup(escaped)

FORM_TEXT_FIELDS = (
    "brand_name",
    "product_description",
    "category",
    "campaign_goal",
    "target_audience",
    "exclusions",
)


def brief_from_form(form) -> dict:
    """Form -> brief dict. Blank fields fall back to the campaign slot default.

    Deliberately permissive: a partly filled form should still produce a
    shortlist against sensible defaults rather than an error page. Values that
    matter to scoring (`category` above all) are echoed back on Screen 2 so the
    user can see what was actually used.
    """
    brief = {**config.DEFAULT_BRIEF}

    for field in FORM_TEXT_FIELDS:
        value = (form.get(field) or "").strip()
        if value:
            brief[field] = value

    platforms = [p for p in form.getlist("platforms") if p in config.PLATFORM_SLUGS]
    if platforms:
        brief["platforms"] = platforms

    band = (form.get("follower_band") or "").strip().lower()
    if band in config.FOLLOWER_BANDS:
        brief["follower_band"] = band

    cpm = scorer._num(form.get("cpm"))
    if cpm is not None and cpm > 0:
        brief["cpm"] = cpm

    size = scorer._num(form.get("shortlist_size"))
    if size is not None:
        brief["shortlist_size"] = int(size)

    return brief


def run_brief(form) -> tuple[dict, dict]:
    brief = brief_from_form(form)
    result = scorer.build_shortlist(brief, config.CREATOR_DATA)
    return brief, result


# ---------------------------------------------------------------------------
# Screen 1 — the brief
# ---------------------------------------------------------------------------
@app.get("/")
def index():
    return render_template(
        "index.html",
        brief=config.DEFAULT_BRIEF,
        platforms=[
            {
                "slug": slug,
                "label": scorer._pretty_platform(slug),
                "calibrated": bool(config.INSTRUMENTS[slug]["bands"]),
                "metric": config.INSTRUMENTS[slug]["label"],
            }
            for slug in config.PLATFORM_SLUGS
        ],
        follower_bands=config.FOLLOWER_BANDS,
        shortlist_min=config.SHORTLIST_MIN,
        shortlist_max=config.SHORTLIST_MAX,
        spec=agent_spec.summary(),
        weights=config.SCORING_WEIGHTS,
        dimension_points=config.DIMENSION_POINTS,
    )


# ---------------------------------------------------------------------------
# Screen 2 — the shortlist
# ---------------------------------------------------------------------------
@app.route("/shortlist", methods=["GET", "POST"])
def shortlist():
    # GET is supported so the screen can be reloaded or linked; it runs the
    # default campaign slot rather than 404ing.
    source = request.form if request.method == "POST" else request.args
    brief, result = run_brief(source)
    return render_template(
        "results.html",
        brief=brief,
        result=result,
        criteria=result["criteria"],
        composition=result["composition"],
        counts=result["counts"],
        spec=agent_spec.summary(),
        role_colours=config.ROLE_COLOURS,
        statuses={
            "keep": scorer.STATUS_KEEP,
            "drop": scorer.STATUS_DROP,
            "refresh": scorer.STATUS_REFRESH,
            "review": scorer.STATUS_REVIEW,
            "calibration": scorer.STATUS_CALIBRATION,
        },
        form_values=dict(source.lists()) if hasattr(source, "lists") else {},
    )


@app.route("/export.csv", methods=["GET", "POST"])
def export_csv():
    source = request.form if request.method == "POST" else request.args
    _, result = run_brief(source)
    brand = (result["criteria"]["brand_name"] or "shortlist").lower().replace(" ", "-")
    return Response(
        scorer.to_csv(result),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{brand}-shortlist.csv"'
        },
    )


@app.get("/api/shortlist")
def api_shortlist():
    _, result = run_brief(request.args)
    return jsonify(
        {
            "criteria": _jsonable(result["criteria"]),
            "counts": result["counts"],
            "composition": result["composition"],
            "table": [_creator_json(c) for c in result["table"]],
        }
    )


def _jsonable(criteria: dict) -> dict:
    out = dict(criteria)
    out["deliverable_formats"] = list(criteria.get("deliverable_formats") or ())
    return out


def _creator_json(creator: dict) -> dict:
    keys = (
        "rank", "name", "handle", "platforms_display", "followers", "resonance_rate",
        "audience_match", "content_match", "engagement_score", "geo_score",
        "commercial_maturity", "weighted_score", "score_100", "tier", "role",
        "readiness", "status", "status_reason", "evidence", "outreach_angle",
        "source", "sourced_from", "sourced_date", "rate_reproducible", "flags",
    )
    out = {k: creator.get(k) for k in keys}
    out["cpm"] = creator.get("cpm")
    return out


# ---------------------------------------------------------------------------
# Schedule console
# ---------------------------------------------------------------------------
def _wants_json() -> bool:
    if request.args.get("format") == "json":
        return True
    accept = request.headers.get("Accept", "")
    return "application/json" in accept and "text/html" not in accept


@app.get("/schedule")
def schedule_console():
    state = scheduler.status()
    if _wants_json():
        return jsonify(state)
    return render_template("schedule.html", state=state, cadences=config.CADENCES)


@app.get("/api/schedule")
def api_schedule():
    return jsonify(scheduler.status())


@app.post("/schedule/run")
def schedule_run():
    scheduler.configure_logging(verbose=False)
    summary = scheduler.run_once()
    if _wants_json():
        return jsonify(summary)
    return redirect(url_for("schedule_console"))


@app.post("/schedule/cadence")
def schedule_cadence():
    cadence = (request.form.get("cadence") or request.args.get("cadence") or "").lower()
    try:
        scheduler.set_cadence(cadence)
    except ValueError as exc:
        if _wants_json():
            return jsonify({"error": str(exc)}), 400
        return render_template(
            "schedule.html",
            state=scheduler.status(),
            cadences=config.CADENCES,
            error=str(exc),
        ), 400
    if _wants_json():
        return jsonify(scheduler.status())
    return redirect(url_for("schedule_console"))


@app.get("/healthz")
def healthz():
    return jsonify(
        {
            "ok": True,
            "spec_loaded": agent_spec.exists(),
            "weights_match_spec": agent_spec.check_weights_documented(),
            "enrichment_enabled": config.ENRICHMENT_ENABLED,
        }
    )


if __name__ == "__main__":
    scheduler.configure_logging(verbose=False)
    app.run(host="127.0.0.1", port=5000, debug=True)
