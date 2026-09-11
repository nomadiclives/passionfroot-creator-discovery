"""Loads the creator-campaign-scout agent spec from agents/ at runtime.

The skill file is the spec of record for the scoring model. Keeping it in the repo
and reading it here means the app can show a Creator Partnership Manager the exact
criteria and rubric a shortlist was produced from, rather than asking them to trust
an undocumented number.

This module only reads and parses. The scoring constants themselves live in
config.py — see check_weights_documented() for the tie between the two.
"""

from __future__ import annotations

import os
import re

import config


def exists() -> bool:
    return os.path.exists(config.SPEC_FILE)


def load_markdown() -> str:
    """Raw markdown of the agent spec. Empty string if it is not checked in."""
    if not exists():
        return ""
    with open(config.SPEC_FILE, "r", encoding="utf-8") as fh:
        return fh.read()


def _body() -> str:
    """Markdown with the YAML frontmatter stripped."""
    text = load_markdown()
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].lstrip()
    return text


def frontmatter() -> dict:
    """The name/description block at the top of the skill file."""
    text = load_markdown()
    if not text.startswith("---"):
        return {}
    block = text.split("---", 2)[1]
    out: dict[str, str] = {}
    key = None
    for line in block.splitlines():
        match = re.match(r"^(\w[\w-]*):\s*(.*)$", line)
        if match:
            key, value = match.group(1), match.group(2).strip()
            out[key] = value
        elif key and line.strip():
            out[key] = (out[key] + " " + line.strip()).strip()
    return out


def campaign_slot() -> dict:
    """Parse the Campaign Slot block — the one block the skill says to swap.

    Returns KEY -> value with continuation lines folded in, e.g.
    {"CAMPAIGN": "Craftly for Students", "BUDGET MODEL": "~$50 CPM", ...}
    """
    # The heading is followed by a paragraph before the fenced block, so scan
    # forward to the first fence rather than expecting it on the next line.
    match = re.search(
        r"##[^\n]*Campaign Slot\b.*?```(.*?)```", _body(), re.S
    )
    if not match:
        return {}
    slot: dict[str, str] = {}
    key = None
    for line in match.group(1).splitlines():
        if not line.strip():
            continue
        field = re.match(r"^([A-Z][A-Z /&-]*[A-Z]):\s*(.*)$", line.strip())
        if field:
            key, value = field.group(1).strip(), field.group(2).strip()
            slot[key] = value
        elif key:
            slot[key] = (slot[key] + " " + line.strip()).strip()
    return slot


def sections() -> dict:
    """Top-level '## ' sections of the spec, in document order."""
    body = _body()
    found = list(re.finditer(r"^##\s+(.+)$", body, re.M))
    out = {}
    for i, match in enumerate(found):
        end = found[i + 1].start() if i + 1 < len(found) else len(body)
        title = re.sub(r"^[^\w]+", "", match.group(1)).strip()
        out[title] = body[match.end():end].strip()
    return out


def scoring_rubric() -> str:
    """The scoring model's point ladders, verbatim from the spec.

    Returned as the spec wrote it rather than parsed into fields. The ladders
    are the thing a Creator Partnership Manager is being asked to trust, and a
    paraphrase of them on screen could drift from the file the tests check —
    which would be worse than not showing them, because it would be believed.
    """
    text = sections().get("Step 5 — Scoring Model", "")
    block = re.search(r"```+\s*\n(.*?)\n```+", text, re.S)
    return block.group(1).strip() if block else ""


def hard_rules() -> list[str]:
    """The Hard Rules bullets — surfaced in the UI so constraints stay visible."""
    text = sections().get("Hard Rules", "")
    rules = re.findall(r"^-\s+(.+?)(?=\n-\s|\n*$)", text, re.M | re.S)
    return [re.sub(r"\s+", " ", r).strip() for r in rules]


def check_weights_documented() -> bool:
    """Guard: the dimension point values in config must appear in the spec.

    If someone edits the weights in config.py without the spec agreeing, this
    returns False and the app can say so instead of silently scoring differently.
    """
    body = _body()
    expected = {
        "audience_match": "AUDIENCE MATCH (30 pts)",
        "content_match": "CONTENT MATCH (25 pts)",
        "engagement_score": "ENGAGEMENT RATE (25 pts)",
        "geo_score": "GEO MATCH (10 pts)",
        "commercial_maturity": "COMMERCIAL MATURITY (10 pts)",
    }
    for dimension, marker in expected.items():
        if marker not in body:
            return False
        if config.DIMENSION_POINTS[dimension] != int(
            re.search(r"\((\d+) pts\)", marker).group(1)
        ):
            return False
    return True


def summary() -> dict:
    """Everything the app needs to render a 'scored against this spec' panel."""
    return {
        "available": exists(),
        "path": os.path.relpath(config.SPEC_FILE, config.BASE_DIR),
        "name": frontmatter().get("name", "creator-campaign-scout"),
        "description": frontmatter().get("description", ""),
        "campaign_slot": campaign_slot(),
        "hard_rules": hard_rules(),
        "sections": list(sections().keys()),
        "weights_match_spec": check_weights_documented(),
    }
