"""Resolves which creator pool a request scores against.

The engine has always accepted an arbitrary creator list; until now the web app
could only ever hand it the bundled file. This module lets a request carry its own
pool, and keeps that pool addressable for the length of the session so that an
Export CSV re-run produces the rows the screen actually showed.

Uploads are parked on disk rather than held in memory because the app runs under
more than one gunicorn worker — an in-process cache would be a coin flip over
which worker served the export.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid

import config
import scorer

TOKEN_FIELD = "pool_token"
BUNDLED = "bundled"

_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")


class PoolError(ValueError):
    """The uploaded file could not be read as a creator list."""


def _upload_dir() -> str:
    os.makedirs(config.UPLOAD_DIR, exist_ok=True)
    return config.UPLOAD_DIR


def _path(token: str) -> str:
    if not _TOKEN_RE.match(token or ""):
        raise PoolError("bad pool reference")
    return os.path.join(_upload_dir(), f"{token}.json")


def parse(raw: bytes, filename: str = "") -> list[dict]:
    """Parse an uploaded CSV or JSON body into creator rows.

    Raises PoolError with something a person can act on — a silent fallback to the
    bundled pool would be the worst possible failure here, since the screen would
    look like it worked and score the wrong creators.
    """
    if len(raw) > config.UPLOAD_MAX_BYTES:
        raise PoolError(
            f"file is larger than {config.UPLOAD_MAX_BYTES // (1024 * 1024)}MB"
        )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PoolError("file is not UTF-8 text — export it as CSV or JSON") from exc

    if not text.strip():
        raise PoolError("file is empty")

    try:
        rows = scorer.load_creators(text)
    except json.JSONDecodeError as exc:
        raise PoolError(f"invalid JSON: {exc.msg} (line {exc.lineno})") from exc
    except Exception as exc:  # noqa: BLE001 - surfaced to the user verbatim
        raise PoolError(f"could not read {filename or 'the file'}: {exc}") from exc

    rows = [r for r in rows if r.get("name")]
    if not rows:
        raise PoolError(
            "no creators found — the file needs a 'name' column, plus "
            "platform, followers and resonance_rate"
        )
    return rows


def save(rows: list[dict], filename: str = "") -> str:
    """Park a parsed pool and return its token."""
    _sweep()
    token = uuid.uuid4().hex
    with open(_path(token), "w", encoding="utf-8") as fh:
        json.dump({"filename": filename, "creators": rows}, fh)
    return token


def load(token: str) -> tuple[list[dict], str]:
    """Return (rows, filename) for a token, or raise PoolError if it has expired."""
    path = _path(token)
    if not os.path.exists(path):
        raise PoolError(
            "that uploaded list is no longer available — upload it again"
        )
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    return payload.get("creators", []), payload.get("filename", "")


def _sweep() -> None:
    """Drop pools past their retention window."""
    cutoff = time.time() - config.UPLOAD_RETENTION_HOURS * 3600
    try:
        entries = os.listdir(_upload_dir())
    except OSError:
        return
    for entry in entries:
        path = os.path.join(_upload_dir(), entry)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
        except OSError:
            continue


def resolve(form, files) -> tuple[object, dict]:
    """Work out what to score.

    Returns (source_for_build_shortlist, provenance) where provenance describes
    the pool on screen so the operator can tell at a glance which creators were
    scored — the bundled sample or their own file.
    """
    upload = files.get("creator_file") if files else None
    if upload is not None and getattr(upload, "filename", ""):
        rows = parse(upload.read(), upload.filename)
        token = save(rows, upload.filename)
        return rows, {
            "kind": "upload",
            "filename": upload.filename,
            "count": len(rows),
            "token": token,
        }

    token = (form.get(TOKEN_FIELD) or "").strip()
    if token and token != BUNDLED:
        rows, filename = load(token)
        return rows, {
            "kind": "upload",
            "filename": filename,
            "count": len(rows),
            "token": token,
        }

    return config.CREATOR_DATA, {
        "kind": "bundled",
        "filename": os.path.basename(config.CREATOR_DATA),
        "count": None,
        "token": BUNDLED,
    }


# ---------------------------------------------------------------------------
# In-app judging
# ---------------------------------------------------------------------------
# Four of the five dimensions, and the readiness call that assigns campaign role,
# are human judgements. The engine will not invent them — so an uploaded sourcing
# export scores nothing until a person supplies them. Until now the only way to
# supply them was to hand-edit CSV columns in a text editor.
#
# Judging in the browser does not weaken the never-invent rule; it is the same
# judgement arriving through a better door. The rule it must not break is the
# other one: a metric is sourced, never typed. So the judging form offers the
# four sub-scores and readiness, and NOTHING that would let someone fill in a
# follower count or a resonance rate.

JUDGEMENT_FIELDS = (
    "audience_match_score",
    "content_match_score",
    "geo_match_score",
    "commercial_maturity_score",
)


def open_for_judging(token: str) -> tuple[list[dict], str, str]:
    """Return (rows, filename, token) for a pool that can be judged.

    The bundled pool is FORKED rather than edited. `data/creators.json` is
    checked-in sourced data — every row carries where it came from and when —
    and letting a browser form write into it would leave an audit trail that
    says "manual, sourced 2026-09-10" over values typed by someone else on a
    different day. It is also read-only in practice on a deployed host, whose
    filesystem resets on every deploy.
    """
    if not token or token == BUNDLED:
        rows = scorer.load_creators(config.CREATOR_DATA)
        new_token = save(rows, f"{os.path.basename(config.CREATOR_DATA)} (working copy)")
        return rows, f"{os.path.basename(config.CREATOR_DATA)} (working copy)", new_token

    rows, filename = load(token)
    return rows, filename, token


def apply_judgements(token: str, judgements: dict[int, dict], category: str) -> int:
    """Write judgements into a parked pool. Returns how many rows changed.

    A judgement is recorded against the campaign category it was made for.
    That is the whole point of `readiness_category`: the judgement is evidence
    about one named category and must not silently transfer to another brief.

    Blank means unjudged. The form is pre-filled with what the pool already
    holds, so an emptied field is someone withdrawing a judgement, not an
    omission to be papered over with the previous value.
    """
    rows, filename = load(token)
    changed = 0

    for index, payload in judgements.items():
        if not 0 <= index < len(rows):
            continue
        row = rows[index]
        before = {f: row.get(f) for f in JUDGEMENT_FIELDS}
        before["readiness"] = row.get("readiness")

        # Only these fields are ever written. This allowlist — not the form's
        # choice of inputs — is what stops a hand-crafted POST setting a metric.
        for field in JUDGEMENT_FIELDS:
            row[field] = _score_or_none(payload.get(field))

        readiness = (payload.get("readiness") or "").strip().lower()
        if readiness in config.READINESS_ROLES:
            row["readiness"] = readiness
            # The category travels with the judgement, always. A readiness value
            # without the category it was judged against is the ambiguity this
            # field exists to remove.
            row["readiness_category"] = category
        elif not readiness:
            row["readiness"] = ""
            row["readiness_category"] = ""
        else:
            # Refused rather than ignored, for the same reason an out-of-range
            # score is: silently dropping it would leave whatever readiness the
            # row already had, and report success.
            raise PoolError(
                f"“{readiness}” is not a readiness level — use "
                + ", ".join(config.READINESS_ORDER)
            )

        after = {f: row.get(f) for f in JUDGEMENT_FIELDS}
        after["readiness"] = row.get("readiness")
        if after != before:
            changed += 1
            # Provenance: a judgement typed into a browser is distinguishable
            # from one that arrived with the sourced data.
            row["judged_in_app"] = True
            row["judged_date"] = _today()

    with open(_path(token), "w", encoding="utf-8") as fh:
        json.dump({"filename": filename, "creators": rows}, fh)
    return changed


def _score_or_none(raw) -> float | None:
    """A 1-5 sub-score, or None for blank. Out-of-range is refused, not clamped.

    Clamping would turn a typo into a judgement. `_judged()` in the scorer
    clamps values that reached it from sourced data; that is a different job
    from accepting form input, where the operator is present to be told.
    """
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError as exc:
        raise PoolError(f"“{text}” is not a score — use 1 to 5, or leave blank") from exc
    if not 1.0 <= value <= 5.0:
        raise PoolError(f"score {value:g} is outside 1-5")
    return value


def _today() -> str:
    from datetime import date

    return date.today().isoformat()
