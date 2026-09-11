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

import os
import re

import agent_spec
import creator_pool
import discovery
import config
import scheduler
import scorer
import screening
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


def run_brief(form, files=None) -> tuple[dict, dict]:
    """Score a brief against the pool the request carries.

    An uploaded file wins; a pool token from a previous upload is next (this is
    what keeps Export CSV honest); the bundled sample is the fallback.
    """
    brief = brief_from_form(form)
    source, provenance = creator_pool.resolve(form, files)
    result = scorer.build_shortlist(brief, source)
    result["pool"] = provenance
    return brief, result


# ---------------------------------------------------------------------------
# Screen 1 — the brief
# ---------------------------------------------------------------------------
def _index_context() -> dict:
    """Everything Screen 1 needs, shared by the happy path and the error re-render."""
    return dict(
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
        required_fields=scorer.REQUIRED_FIELDS,
        judged_fields=scorer.JUDGED_FIELDS,
        bundled_count=_bundled_count(),
    )


def _bundled_count() -> int:
    try:
        return len(scorer.load_creators(config.CREATOR_DATA))
    except Exception:  # noqa: BLE001 - a broken bundle must not break Screen 1
        return 0


@app.get("/")
def index():
    return render_template(
        "index.html", brief=config.DEFAULT_BRIEF, **_index_context()
    )


@app.get("/how-it-works")
def how_it_works():
    """The one-pager: the model's logic, what it refuses, and what it depends on.

    Rendered from live config rather than prose so the page cannot drift from the
    model actually being applied — a stale explanation of a scoring model is worse
    than none, because it is believed.
    """
    return render_template(
        "how_it_works.html",
        spec=agent_spec.summary(),
        weights=config.SCORING_WEIGHTS,
        # The rubric a shortlist is actually defensible by. Two sources on
        # purpose: the ladders verbatim from the spec, and the bands the code
        # applies read from live config, so a reader can see they agree.
        rubric=agent_spec.scoring_rubric(),
        dimension_points=config.DIMENSION_POINTS,
        score_tiers=config.SCORE_TIERS,
        instruments=config.INSTRUMENTS,
        readiness_roles=config.READINESS_ROLES,
        role_colours=config.ROLE_COLOURS,
        retention_hours=config.UPLOAD_RETENTION_HOURS,
    )


@app.get("/creator-template.csv")
def creator_template():
    """A blank row with every column the engine reads, so an upload can be filled in."""
    columns = [
        "name", "platform", "followers", "resonance_rate",
        "audience_match_score", "content_match_score", "geo_match_score",
        "commercial_maturity_score", "readiness", "readiness_category",
        "location", "comment_quality", "current_sponsors", "notes",
        "source", "sourced_from", "sourced_date",
    ]
    example = [
        "Example Creator", "TikTok, Instagram", "120000", "8.4",
        "4", "3", "5", "4", "exposed", "AI app-building tools",
        "US", "substantive", "", "why they fit",
        "manual", "where you found them", "2026-09-10",
    ]
    body = ",".join(columns) + "\n" + ",".join(
        f'"{v}"' if "," in v else v for v in example
    ) + "\n"
    return Response(
        body,
        mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="creator-template.csv"'},
    )


# ---------------------------------------------------------------------------
# Screen 2 — the shortlist
# ---------------------------------------------------------------------------
@app.route("/shortlist", methods=["GET", "POST"])
def shortlist():
    # GET is supported so the screen can be reloaded or linked; it runs the
    # default campaign slot rather than 404ing.
    source = request.form if request.method == "POST" else request.args
    try:
        brief, result = run_brief(source, request.files)
    except creator_pool.PoolError as exc:
        # Never fall back to the bundled pool on a bad upload: the screen would
        # look right and describe creators the operator never submitted.
        return (
            render_template(
                "index.html",
                brief=brief_from_form(source),
                upload_error=str(exc),
                **_index_context(),
            ),
            400,
        )
    return _render_shortlist(
        brief, result, dict(source.lists()) if hasattr(source, "lists") else {}
    )


def _render_shortlist(brief: dict, result: dict, form_values: dict) -> str:
    """Screen 2. Shared by /shortlist and the judging screen's save-and-build."""
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
        form_values=form_values,
    )


# ---------------------------------------------------------------------------
# Screen 0 — discovery
# ---------------------------------------------------------------------------
# The app could never find creators, only score ones you already had. This is
# the front half. It produces CANDIDATES — handles with whatever metrics their
# source actually returned — which flow into the same pool an upload makes, and
# on to judging and scoring.
#
# The query plan deliberately does not call anything. The spec says Step 2
# "produces a query plan and candidate pool, not verified metrics", and on
# platforms with no free API that is simply true, so the app builds real
# clickable searches and a person runs them.
def _sources() -> list:
    from sources import query_plan as qp, youtube as yt

    return [yt.YouTubeSource(), qp.QueryPlanSource()]


def _discovery_context(brief: dict) -> dict:
    from sources import query_plan as qp, youtube as yt

    availability = []
    for source in _sources():
        ok, why = source.available()
        availability.append({"name": source.name, "available": ok, "reason": why})

    return dict(
        brief=brief,
        plan=qp.build(brief),
        availability=availability,
        quota_per_day=config.YOUTUBE_QUOTA_PER_DAY,
        search_cost=config.YOUTUBE_QUOTA_COSTS["search"],
        form_values=_carry_brief(brief),
        platforms=[
            {"slug": s, "label": scorer._pretty_platform(s)}
            for s in config.PLATFORM_SLUGS
        ],
    )


@app.route("/discover", methods=["GET", "POST"])
def discover():
    source = request.form if request.method == "POST" else request.args
    brief = brief_from_form(source)
    return render_template("discover.html", collected=None, error=None,
                           **_discovery_context(brief))


@app.post("/discover/collect")
def discover_collect():
    """Turn pasted handles into a scoreable pool.

    Every row lands as NEEDS_REFRESH, because a pasted handle is a lead and not a
    measurement. That is the correct outcome, and Screen 2 says so per row rather
    than the app quietly filling numbers in.
    """
    from sources import query_plan as qp

    form = request.form
    brief = brief_from_form(form)
    pasted = form.get("pasted") or ""
    platform = (form.get("paste_platform") or "").strip().lower()

    rows = qp.parse_pasted(
        pasted, platform=platform if platform in config.PLATFORM_SLUGS else "",
        search_source=(form.get("paste_pass") or "manual paste").strip(),
    )
    if not rows:
        return (
            render_template(
                "discover.html",
                collected=None,
                error=(
                    "No handles found. Paste one per line — either a profile URL, or "
                    "a handle plus a platform chosen below (a bare handle with no "
                    "platform cannot be scored, so it is not guessed)."
                ),
                **_discovery_context(brief),
            ),
            400,
        )

    # Fold in anything already collected this session, so several passes build up
    # one pool rather than each replacing the last.
    token = (form.get(creator_pool.TOKEN_FIELD) or "").strip()
    existing: list[dict] = []
    if token and token != creator_pool.BUNDLED:
        try:
            existing, _ = creator_pool.load(token)
        except creator_pool.PoolError:
            existing = []

    merged = discovery.merge([*existing, *rows])
    new_token = creator_pool.save(merged, f"discovered {discovery.today()}")

    result = scorer.build_shortlist(brief, merged)
    result["pool"] = {
        "kind": "upload",
        "filename": f"discovered {discovery.today()}",
        "count": len(merged),
        "token": new_token,
    }
    return _render_shortlist(brief, result, {creator_pool.TOKEN_FIELD: [new_token]})


# ---------------------------------------------------------------------------
# The screening screen — Step 3
# ---------------------------------------------------------------------------
# Between finding a creator and judging one sits the question "is there any
# reason not to pitch them at all?". The spec calls it Red Flag Triage.
#
# This screen is READ-ONLY and deliberately so. It does not fork the pool the
# way judging does, does not write a status, and cannot be used to clear a
# check — clearing one means sourcing the evidence and putting it on the row.
# What it produces is a verdict per creator and, more usefully, the list of
# checks nobody has answered yet, which is the sourcing backlog in priority
# order.
VERDICT_CLASSES = {
    screening.PASS: "status-keep",
    screening.FLAG: "status-needs-refresh",
    screening.FAIL: "status-drop",
    screening.UNKNOWN: "status-needs-calibration",
    screening.NEEDS_SCREENING: "status-needs-review",
}


def _pool_for_screening(token: str) -> tuple[list[dict], str, str]:
    """Load a pool without forking it. Screening writes nothing."""
    if not token or token == creator_pool.BUNDLED:
        rows = scorer.load_creators(config.CREATOR_DATA)
        return rows, os.path.basename(config.CREATOR_DATA), creator_pool.BUNDLED
    rows, filename = creator_pool.load(token)
    return rows, filename, token


def _screen_context(brief: dict, rows: list[dict], filename: str, token: str) -> dict:
    criteria = scorer.lock_criteria(brief)
    result = screening.screen_all(rows, criteria)
    return dict(
        brief=brief,
        criteria=criteria,
        result=result,
        pool={"filename": filename, "token": token, "count": len(rows)},
        verdict_classes=VERDICT_CLASSES,
        form_values=_carry_brief(brief),
        # The verdict constants, so the template names them rather than
        # hard-coding strings that could drift from screening.py.
        PASS=screening.PASS,
        FLAG=screening.FLAG,
        FAIL=screening.FAIL,
        UNKNOWN=screening.UNKNOWN,
        NEEDS_SCREENING=screening.NEEDS_SCREENING,
    )


@app.route("/screen", methods=["GET", "POST"])
def screen():
    source = request.form if request.method == "POST" else request.args
    brief = brief_from_form(source)
    token = (source.get(creator_pool.TOKEN_FIELD) or "").strip()
    try:
        rows, filename, token = _pool_for_screening(token)
    except creator_pool.PoolError as exc:
        return (
            render_template(
                "index.html", brief=brief, upload_error=str(exc), **_index_context()
            ),
            400,
        )
    return render_template("screen.html", **_screen_context(brief, rows, filename, token))


@app.get("/api/screen")
def api_screen():
    """The same triage as JSON, for anything that wants to read the backlog."""
    brief = brief_from_form(request.args)
    token = (request.args.get(creator_pool.TOKEN_FIELD) or "").strip()
    try:
        rows, filename, token = _pool_for_screening(token)
    except creator_pool.PoolError as exc:
        return jsonify({"error": str(exc)}), 400
    result = screening.screen_all(rows, scorer.lock_criteria(brief))
    return jsonify(
        {
            "pool": {"filename": filename, "token": token, "count": len(rows)},
            "category": brief.get("category", ""),
            "counts": result["counts"],
            "total": result["total"],
            "unknown_by_check": result["unknown_by_check"],
            "rows": result["rows"],
            "screened_date": result["screened_date"],
        }
    )


# ---------------------------------------------------------------------------
# The judging screen
# ---------------------------------------------------------------------------
# Four of the five dimensions and the readiness call are human judgements, so a
# freshly sourced list scores as NEEDS_REVIEW on every row. That is correct — the
# engine will not invent judgement — but until now the only way to supply it was
# to hand-edit CSV columns. This screen is the same judgement arriving through a
# better door.
#
# What it deliberately does NOT offer is a way to type a metric. Followers and
# resonance rate are shown read-only, and a row missing them stays NEEDS_REFRESH
# and is not judgeable here. Judgement can be typed; a metric must be sourced.
def _judging_rows(rows: list[dict], criteria: dict) -> list[dict]:
    """Pair every pool row with its current status, in pool order.

    Scored individually rather than through build_shortlist(), which ranks and
    would break the index the form posts back against.
    """
    out = []
    for index, row in enumerate(rows):
        creator = scorer.normalise_creator(row)
        scored = scorer.score_creator(creator, criteria)
        status = scored.get("status")
        out.append(
            {
                "index": index,
                "creator": creator,
                "status": status,
                "status_reason": scored.get("status_reason", ""),
                # A metric gap cannot be judged away, so the form locks the row
                # and says why rather than offering inputs that would not help.
                "judgeable": status != scorer.STATUS_REFRESH,
                "needs_judgement": status == scorer.STATUS_REVIEW,
                "judged_in_app": bool(row.get("judged_in_app")),
                "judged_date": row.get("judged_date", ""),
            }
        )
    return out


def _judge_context(brief: dict, rows: list[dict], filename: str, token: str) -> dict:
    criteria = scorer.lock_criteria(brief)
    judging = _judging_rows(rows, criteria)
    return dict(
        brief=brief,
        criteria=criteria,
        rows=judging,
        pool={"filename": filename, "token": token, "count": len(rows)},
        readiness_roles=config.READINESS_ROLES,
        readiness_order=config.READINESS_ORDER,
        judged_fields=creator_pool.JUDGEMENT_FIELDS,
        outstanding=sum(1 for r in judging if r["needs_judgement"]),
        unrefreshable=sum(1 for r in judging if not r["judgeable"]),
        form_values=_carry_brief(brief),
    )


def _carry_brief(brief: dict) -> dict:
    """The brief fields the judging form re-posts, so the round trip keeps them."""
    carried = {f: brief.get(f, "") for f in FORM_TEXT_FIELDS}
    carried["platforms"] = brief.get("platforms", [])
    carried["follower_band"] = brief.get("follower_band", "")
    carried["cpm"] = brief.get("cpm", "")
    carried["shortlist_size"] = brief.get("shortlist_size", "")
    return carried


@app.route("/judge", methods=["GET", "POST"])
def judge():
    source = request.form if request.method == "POST" else request.args
    brief = brief_from_form(source)
    token = (source.get(creator_pool.TOKEN_FIELD) or "").strip()
    try:
        rows, filename, token = creator_pool.open_for_judging(token)
    except creator_pool.PoolError as exc:
        return (
            render_template(
                "index.html", brief=brief, upload_error=str(exc), **_index_context()
            ),
            400,
        )
    return render_template(
        "judge.html", saved=None, error=None, **_judge_context(brief, rows, filename, token)
    )


@app.post("/judge/save")
def judge_save():
    form = request.form
    brief = brief_from_form(form)
    token = (form.get(creator_pool.TOKEN_FIELD) or "").strip()

    try:
        judgements = _judgements_from_form(form)
        changed = creator_pool.apply_judgements(
            token, judgements, scorer.lock_criteria(brief)["category"]
        )
        rows, filename = creator_pool.load(token)
    except creator_pool.PoolError as exc:
        # Re-render the form the operator was filling in rather than dropping
        # the other judgements they had already typed.
        try:
            rows, filename, token = creator_pool.open_for_judging(token)
        except creator_pool.PoolError:
            return (
                render_template(
                    "index.html", brief=brief, upload_error=str(exc), **_index_context()
                ),
                400,
            )
        return (
            render_template(
                "judge.html",
                error=str(exc),
                saved=None,
                **_judge_context(brief, rows, filename, token),
            ),
            400,
        )

    if form.get("then") == "shortlist":
        result = scorer.build_shortlist(brief, rows)
        result["pool"] = {
            "kind": "upload", "filename": filename,
            "count": len(rows), "token": token,
        }
        return _render_shortlist(brief, result, {creator_pool.TOKEN_FIELD: [token]})

    return render_template(
        "judge.html",
        saved=changed,
        error=None,
        **_judge_context(brief, rows, filename, token),
    )


def _judgements_from_form(form) -> dict[int, dict]:
    """Read `judge-<index>-<field>` inputs back into per-row payloads.

    Only rows the form actually offered come back — a locked NEEDS_REFRESH row
    posts no inputs and is therefore never touched.
    """
    judgements: dict[int, dict] = {}
    for key in form.keys():
        match = re.match(r"^judge-(\d+)-([a-z_]+)$", key)
        if not match:
            continue
        index = int(match.group(1))
        judgements.setdefault(index, {})[match.group(2)] = form.get(key)
    return judgements


@app.route("/export.csv", methods=["GET", "POST"])
def export_csv():
    source = request.form if request.method == "POST" else request.args
    try:
        _, result = run_brief(source, request.files)
    except creator_pool.PoolError as exc:
        return Response(f"Cannot export: {exc}\n", status=400, mimetype="text/plain")
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


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    # Local development entry point only. In production the app is served by
    # gunicorn against the `app` object above (see render.yaml), so none of
    # this runs there.
    #
    # Debug defaults to OFF and must be asked for. The Werkzeug debugger
    # executes arbitrary code from the browser, so a debug default that
    # survives to a deployed host is a remote shell, not a convenience.
    scheduler.configure_logging(verbose=False)
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=_env_flag("FLASK_DEBUG"),
    )
