"""API enrichment for creator metrics — wired, but inert by default.

The toggle lives in `config.ENRICHMENT_ENABLED` (default False). With it off,
this module is a pass-through: it returns the creator unchanged and marks the
metrics `manual`. Nothing here ever produces a number that did not come back
from a real call.

HARD RULE — never fabricate creator metrics.

That rule is what shapes this file. Three outcomes, and none of them is a
guess:

  toggle off      -> return the row untouched, `source='manual'`
  call succeeds   -> merge ONLY the fields the provider actually returned,
                     `source=<provider>`
  call fails      -> keep the manual values, flag the row `UNVERIFIED`

A failed call is not a licence to interpolate. It is a fact about the row, so
it is recorded on the row and the UI shows it.

Enrichment also never OVERWRITES a value that is already present. `data/
creators.json` is hand-sourced from the product owner's sheet with a
`sourced_from` audit trail; an API number silently replacing an audited one
would break that trail. Enrichment fills gaps only.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import config

FLAG_UNVERIFIED = "UNVERIFIED"

# Fields an enrichment provider is allowed to supply. Anything else it returns
# is ignored: the provider does not get to invent schema.
ENRICHABLE_FIELDS = (
    "followers",
    "avg_views",
    "resonance_rate",
    "engagement_rate",
    "geo_us_pct",
    "audience_18_24_pct",
    "brand_deals_count",
    "last_post_days",
)

# Provider field name -> our field name. Providers disagree on naming; this is
# the only place that disagreement lives.
FIELD_MAP = {
    "follower_count": "followers",
    "followers": "followers",
    "average_views": "avg_views",
    "avg_views": "avg_views",
    "view_rate": "resonance_rate",
    "engagement_rate": "engagement_rate",
    "audience_us_pct": "geo_us_pct",
    "geo_us_pct": "geo_us_pct",
    "audience_18_24_pct": "audience_18_24_pct",
    "sponsored_posts_count": "brand_deals_count",
    "brand_deals_count": "brand_deals_count",
    "days_since_last_post": "last_post_days",
}


class EnrichmentError(RuntimeError):
    """A call was attempted and did not produce usable data."""


def is_enabled() -> bool:
    """Enrichment runs only with the toggle on AND a key present."""
    return bool(config.ENRICHMENT_ENABLED and config.API_KEY)


def _endpoint(handle: str, platform: str) -> str:
    base = config.API_BASE_URLS.get(config.API_PROVIDER)
    if not base:
        raise EnrichmentError(f"unknown provider {config.API_PROVIDER!r}")
    query = urllib.parse.urlencode({"handle": handle, "platform": platform})
    return f"{base}/creators/lookup?{query}"


def _request(url: str) -> dict:
    """One HTTP GET. Isolated so tests can patch it without a network."""
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {config.API_KEY}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=config.API_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _translate(payload: dict) -> dict[str, Any]:
    """Provider payload -> our schema. Drops anything unrecognised or non-numeric."""
    out: dict[str, Any] = {}
    for raw_key, value in (payload or {}).items():
        field = FIELD_MAP.get(str(raw_key).strip().lower())
        if field is None or field not in ENRICHABLE_FIELDS:
            continue
        if value is None:
            continue
        try:
            out[field] = float(value)
        except (TypeError, ValueError):
            # A value we cannot parse is a missing value, not a zero.
            continue
    return out


def enrich_creator(handle: str, platform: str) -> dict:
    """Look one creator up with the configured provider.

    Returns a dict of metrics in OUR schema — `{}` when enrichment is off, and
    `{}` when the provider had nothing. Never returns invented numbers.

    Raises EnrichmentError when a call was attempted and failed, so the caller
    can flag the row UNVERIFIED rather than silently continuing.
    """
    if not is_enabled():
        return {}
    if not handle:
        raise EnrichmentError("no handle to look up")

    try:
        payload = _request(_endpoint(handle, platform))
    except urllib.error.HTTPError as exc:
        raise EnrichmentError(f"{config.API_PROVIDER} returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise EnrichmentError(f"{config.API_PROVIDER} unreachable: {exc.reason}") from exc
    except (TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise EnrichmentError(f"{config.API_PROVIDER} call failed: {exc}") from exc

    if isinstance(payload, dict) and "data" in payload:
        payload = payload["data"]
    if not isinstance(payload, dict):
        raise EnrichmentError(f"{config.API_PROVIDER} returned an unexpected shape")
    return _translate(payload)


def apply_enrichment(creator: dict) -> dict:
    """Fill a creator's metric GAPS from the provider. Called by build_shortlist.

    Present values are never overwritten — `data/creators.json` carries an audit
    trail (`sourced_from`, `sourced_date`) that an API number would quietly
    invalidate. Enrichment adds what is missing and nothing else.
    """
    creator = dict(creator)
    flags = list(creator.get("flags") or [])

    if not is_enabled():
        creator["source"] = creator.get("source") or "manual"
        creator["flags"] = flags
        return creator

    handle = creator.get("handle") or creator.get("name") or ""
    platform = (creator.get("platforms") or [""])[0]

    try:
        fetched = enrich_creator(handle, platform)
    except EnrichmentError as exc:
        # Fall back to whatever was already on the row and say so. The row is
        # still usable; it is just no longer provider-confirmed.
        if FLAG_UNVERIFIED not in flags:
            flags.append(FLAG_UNVERIFIED)
        creator["source"] = creator.get("source") or "manual"
        creator["flags"] = flags
        creator["enrichment_error"] = str(exc)
        return creator

    filled = []
    for field, value in fetched.items():
        if creator.get(field) is None:
            creator[field] = value
            filled.append(field)

    if filled:
        creator["source"] = config.API_PROVIDER
        creator["enriched_fields"] = filled
    else:
        creator["source"] = creator.get("source") or "manual"

    creator["flags"] = flags
    return creator
