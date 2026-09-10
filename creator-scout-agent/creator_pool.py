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
