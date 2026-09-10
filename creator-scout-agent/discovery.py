"""Discovery — Steps 2 and 3 of creator-campaign-scout.md.

The app has always scored creators you already had. This is the half that finds
them. It produces CANDIDATES, never scored creators: a candidate carries whatever
metrics its source actually returned, plus provenance saying where it came from,
and no judgement whatsoever.

That division is the whole design. Discovery is allowed to be mechanical and
wide; judgement stays human and narrow. A candidate flows into the same pool a
CSV upload produces, so it lands on the judging screen and then the scorer —
source → judge → score, with the never-invent rule intact at every hop.

Three rules a source adapter must not break:

1. **Return what you got, never what you inferred.** An absent field stays
   absent and becomes NEEDS_REFRESH downstream. No estimating a follower count
   from a view count, no inferring audience age from content.
2. **Say where it came from.** Every candidate carries `search_source` (which
   pass and query found it), `sourced_date`, and a `source_confidence` recording
   whether a number was measured by an API or merely self-reported.
3. **Report a cap you hit.** A source that returns 50 of 500 possible matches
   because it ran out of quota must say so. A short list that looks complete is
   the failure this codebase exists to prevent.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Iterable, Protocol

import config
import scorer

# A handle is compared case-insensitively and without a leading @, because the
# same creator surfacing from three passes must dedupe to one row.
_HANDLE_CLEAN = re.compile(r"^[@/\s]+|[/\s]+$")


class DiscoveryError(RuntimeError):
    """A source could not run. Never raised to mean 'found nothing'."""


class Source(Protocol):
    """What a discovery source must provide.

    `name` is recorded on every candidate it produces, so a row can always be
    traced back to the adapter that made it.
    """

    name: str

    def available(self) -> tuple[bool, str]:
        """(is_usable, why_not). A source without credentials is not an error."""

    def search(self, brief: dict) -> "SourceResult":
        """Run this source against a brief."""


class SourceResult:
    """What one source returned, including what it could not return.

    `truncated` and `notes` exist so a partial run is legible. A source that
    silently returns fewer rows than it found is indistinguishable from a niche
    with fewer creators in it, and those are very different facts.
    """

    def __init__(
        self,
        source: str,
        candidates: list[dict] | None = None,
        truncated: bool = False,
        notes: list[str] | None = None,
        queries_run: int = 0,
        quota_spent: int = 0,
    ):
        self.source = source
        self.candidates = candidates or []
        self.truncated = truncated
        self.notes = notes or []
        self.queries_run = queries_run
        self.quota_spent = quota_spent

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "found": len(self.candidates),
            "truncated": self.truncated,
            "notes": list(self.notes),
            "queries_run": self.queries_run,
            "quota_spent": self.quota_spent,
        }


def today() -> str:
    return _dt.date.today().isoformat()


def normalise_handle(handle: str) -> str:
    """Strip @ and surrounding punctuation. Case-insensitive for comparison."""
    return _HANDLE_CLEAN.sub("", str(handle or "")).strip()


def candidate(
    *,
    name: str,
    platform: str,
    source: str,
    search_source: str,
    handle: str = "",
    confidence: str = config.CONFIDENCE_CANDIDATE,
    **metrics,
) -> dict:
    """Build one candidate row.

    Metrics are passed through only when present. A caller that has no follower
    count simply does not pass one — there is deliberately no default, because a
    default here would be an invented metric wearing a keyword argument.
    """
    if not name and not handle:
        raise DiscoveryError("a candidate needs a name or a handle")

    row = {
        "name": name or handle,
        "handle": normalise_handle(handle),
        "platform": platform,
        "source": source,
        "search_source": search_source,
        "sourced_from": source,
        "sourced_date": today(),
        "source_confidence": confidence,
        "discovered": True,
    }
    for key, value in metrics.items():
        if value is not None:
            row[key] = value
    return row


def _key(row: dict) -> tuple[str, str]:
    """Identity for dedupe: handle if there is one, else name, plus platform."""
    handle = normalise_handle(row.get("handle") or "").lower()
    name = str(row.get("name") or "").strip().lower()
    platform = str(row.get("platform") or "").strip().lower()
    return (handle or name, platform)


def merge(rows: Iterable[dict]) -> list[dict]:
    """Dedupe candidates, recording corroboration rather than discarding it.

    The same creator surfacing from three passes is a SIGNAL — it means three
    independent queries agree this person is in the niche. Collapsing that to one
    row and throwing away the other two loses the strongest free evidence
    discovery produces, so the passes that found them are kept in
    `corroborated_by` and counted in `corroboration`.

    Where two sources disagree on a metric, the more confident one wins and the
    disagreement is recorded — never averaged, which would invent a third number
    that no source reported.
    """
    order = {
        config.CONFIDENCE_MEASURED: 3,
        config.CONFIDENCE_REPORTED: 2,
        config.CONFIDENCE_CANDIDATE: 1,
    }
    merged: dict[tuple[str, str], dict] = {}

    for row in rows:
        key = _key(row)
        if key not in merged:
            row = dict(row)
            row["corroborated_by"] = [row.get("search_source", "")]
            row["corroboration"] = 1
            merged[key] = row
            continue

        existing = merged[key]
        incoming_rank = order.get(row.get("source_confidence"), 0)
        existing_rank = order.get(existing.get("source_confidence"), 0)

        for field, value in row.items():
            if field in {"corroborated_by", "corroboration"} or value is None:
                continue
            if field not in existing or existing[field] in (None, "", []):
                existing[field] = value
            elif field in scorer.NUMERIC_FIELDS and existing[field] != value:
                # Two sources measured the same thing differently. Keep the more
                # confident number and say so, rather than averaging them into a
                # figure neither source would stand behind.
                if incoming_rank > existing_rank:
                    existing.setdefault("metric_conflicts", []).append(
                        f"{field}: kept {value} ({row.get('source')}) over "
                        f"{existing[field]} ({existing.get('source')})"
                    )
                    existing[field] = value
                else:
                    existing.setdefault("metric_conflicts", []).append(
                        f"{field}: kept {existing[field]} ({existing.get('source')}) "
                        f"over {value} ({row.get('source')})"
                    )

        pass_name = row.get("search_source", "")
        if pass_name and pass_name not in existing["corroborated_by"]:
            existing["corroborated_by"].append(pass_name)
            existing["corroboration"] = len(existing["corroborated_by"])
        if incoming_rank > existing_rank:
            existing["source_confidence"] = row["source_confidence"]

    return list(merged.values())


def exclude_known(candidates: list[dict], known: Iterable[dict]) -> tuple[list[dict], int]:
    """Drop candidates already in the pool. Returns (new_rows, skipped_count).

    Re-surfacing someone already sourced is not a find, and presenting them as
    one would inflate every discovery run with people you already have.
    """
    seen = {_key(scorer.normalise_creator(row)) for row in known}
    fresh = [c for c in candidates if _key(c) not in seen]
    return fresh, len(candidates) - len(fresh)


def run(brief: dict, sources: list[Source], known: Iterable[dict] | None = None) -> dict:
    """Run every available source against a brief and merge the results.

    An unavailable source is reported, not skipped silently — "no candidates from
    YouTube" and "no YouTube key configured" look identical in a result list and
    mean completely different things.
    """
    results, all_rows, unavailable = [], [], []

    for source in sources:
        ok, why = source.available()
        if not ok:
            unavailable.append({"source": source.name, "reason": why})
            continue
        try:
            result = source.search(brief)
        except DiscoveryError as exc:
            unavailable.append({"source": source.name, "reason": str(exc)})
            continue
        except Exception as exc:  # noqa: BLE001
            # One adapter blowing up must not take the run down with it. This is
            # reporting the failure, not swallowing it — the exception text goes
            # straight into the result where a reader will see it.
            unavailable.append({
                "source": source.name,
                "reason": f"{type(exc).__name__}: {exc}",
            })
            continue
        results.append(result.as_dict())
        all_rows.extend(result.candidates)

    candidates = merge(all_rows)
    skipped = 0
    if known is not None:
        candidates, skipped = exclude_known(candidates, known)

    candidates.sort(
        key=lambda c: (-c.get("corroboration", 1), str(c.get("name", "")).lower())
    )

    return {
        "candidates": candidates,
        "sources": results,
        "unavailable": unavailable,
        "already_known": skipped,
        "counts": {
            "found": len(candidates),
            "with_metrics": sum(1 for c in candidates if c.get("followers") is not None),
            "corroborated": sum(1 for c in candidates if c.get("corroboration", 1) > 1),
            "sources_run": len(results),
            "sources_unavailable": len(unavailable),
        },
        "brief_category": brief.get("category", ""),
        "run_date": today(),
    }
