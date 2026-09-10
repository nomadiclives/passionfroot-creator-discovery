"""YouTube Data API v3 — the free tier, and the only honest automated source.

Official, permitted, free, and it returns real audience-side numbers. The spec
says to start with YouTube and the reasoning holds: content is search-indexed,
has a long shelf life, and exposes a public view count.

**Wired but inert**, exactly like `enricher.py`. With no `YOUTUBE_API_KEY` the
adapter reports itself unavailable and returns nothing — it never falls back to
a plausible-looking result, because a discovery source that invents creators is
worse than one that invents metrics.

## The quota shape is the design

`search.list` costs 100 units and a project starts at 10,000/day, so the entire
daily budget is ~100 searches. `channels.list` and `videos.list` cost 1 unit and
batch 50 ids per call. Search is therefore precious and enrichment is nearly
free, which dictates the strategy:

    few searches  ->  harvest channel ids from VIDEO results  ->  batch-enrich

Searching videos rather than channels is deliberate. `type=channel` matches
channel names and descriptions; `type=video` finds channels by what they
actually publish, which is what the brief is about, and one call yields up to 50
videos across many channels.

## resonance_rate is computed, and reproducible

D3 for YouTube is a view rate: median views over recent videos ÷ subscribers.
Both numbers come from the API in the same run and are recorded alongside the
rate, so unlike the three `rate_reproducible: false` rows in the bundled data,
this rate can always be recomputed from the columns stored next to it.

Median, not mean: one viral video would drag a mean far above what a sponsor can
expect to reach, and the CPM model already applies its own decay to a figure
that is supposed to be typical.
"""

from __future__ import annotations

import json
import statistics
import urllib.error
import urllib.parse
import urllib.request

import config
import discovery

NAME = "youtube"


class QuotaBudget:
    """Tracks unit spend so a run stops before Google does.

    Hitting the quota mid-run yields a partial list that looks complete, which is
    the failure mode this whole codebase is built against. Budgeting up front
    means the run can say "I stopped at 60 of 120 queries" instead.
    """

    def __init__(self, limit: int | None = None):
        self.limit = config.YOUTUBE_QUOTA_PER_DAY if limit is None else limit
        self.spent = 0

    def can_afford(self, call: str) -> bool:
        return self.spent + config.YOUTUBE_QUOTA_COSTS.get(call, 1) <= self.limit

    def charge(self, call: str) -> None:
        self.spent += config.YOUTUBE_QUOTA_COSTS.get(call, 1)

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.spent)


def _get(path: str, params: dict, timeout: int | None = None) -> dict:
    """One GET against the API. Patched wholesale in tests, as enricher.py is."""
    query = urllib.parse.urlencode(
        {**params, "key": config.YOUTUBE_API_KEY}, doseq=True
    )
    url = f"{config.YOUTUBE_API_BASE}/{path}?{query}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(
            request, timeout=timeout or config.API_TIMEOUT_SECONDS
        ) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = "quota exceeded" if exc.code == 403 else f"HTTP {exc.code}"
        raise discovery.DiscoveryError(f"YouTube API {detail}") from exc
    except urllib.error.URLError as exc:
        raise discovery.DiscoveryError(f"YouTube unreachable: {exc.reason}") from exc
    except (ValueError, KeyError) as exc:
        raise discovery.DiscoveryError(f"YouTube returned an unexpected shape: {exc}") from exc


def _chunks(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _int(value) -> int | None:
    """API counts arrive as strings, and can be absent when a channel hides them.

    Absent stays absent. A hidden subscriber count is not zero subscribers, and
    writing 0 would be inventing the most consequential metric in the model.
    """
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def search_channel_ids(terms: list[str], budget: QuotaBudget, per_query: int = 50) -> tuple[list[str], list[str], bool]:
    """Find channel ids by searching for videos. Returns (ids, notes, truncated)."""
    ids: list[str] = []
    seen: set[str] = set()
    notes: list[str] = []
    truncated = False

    for index, term in enumerate(terms):
        if not budget.can_afford("search"):
            truncated = True
            notes.append(
                f"stopped after {index} of {len(terms)} searches — quota budget spent "
                f"({budget.spent} units). The rest were not run."
            )
            break
        payload = _get("search", {
            "part": "snippet",
            "q": term,
            "type": "video",
            "order": "viewCount",
            "maxResults": min(per_query, 50),
            "relevanceLanguage": "en",
        })
        budget.charge("search")
        for item in payload.get("items", []):
            channel_id = (item.get("snippet") or {}).get("channelId")
            if channel_id and channel_id not in seen:
                seen.add(channel_id)
                ids.append(channel_id)

    return ids, notes, truncated


def fetch_channels(channel_ids: list[str], budget: QuotaBudget) -> dict[str, dict]:
    """Batch-fetch channel statistics. 1 unit per 50 ids."""
    out: dict[str, dict] = {}
    for batch in _chunks(channel_ids, config.YOUTUBE_BATCH_SIZE):
        if not budget.can_afford("channels"):
            break
        payload = _get("channels", {
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(batch),
            "maxResults": config.YOUTUBE_BATCH_SIZE,
        })
        budget.charge("channels")
        for item in payload.get("items", []):
            out[item["id"]] = item
    return out


def recent_view_median(uploads_playlist: str, budget: QuotaBudget) -> tuple[float | None, int]:
    """Median view count over recent uploads. Returns (median, sample_size).

    Two calls: playlistItems for the ids, videos for the counts. Both 1 unit.
    """
    if not uploads_playlist or not budget.can_afford("videos"):
        return None, 0

    payload = _get("playlistItems", {
        "part": "contentDetails",
        "playlistId": uploads_playlist,
        "maxResults": config.YOUTUBE_VIDEOS_SAMPLED,
    })
    budget.charge("videos")
    video_ids = [
        (item.get("contentDetails") or {}).get("videoId")
        for item in payload.get("items", [])
    ]
    video_ids = [v for v in video_ids if v]
    if not video_ids or not budget.can_afford("videos"):
        return None, 0

    payload = _get("videos", {"part": "statistics", "id": ",".join(video_ids)})
    budget.charge("videos")
    views = [
        _int((item.get("statistics") or {}).get("viewCount"))
        for item in payload.get("items", [])
    ]
    views = [v for v in views if v is not None]
    if not views:
        return None, 0
    return float(statistics.median(views)), len(views)


def _to_candidate(item: dict, search_source: str, budget: QuotaBudget) -> dict:
    """One API channel object -> one candidate row."""
    snippet = item.get("snippet") or {}
    stats = item.get("statistics") or {}
    uploads = ((item.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads", "")

    subscribers = _int(stats.get("subscriberCount"))
    median_views, sample = recent_view_median(uploads, budget)

    metrics: dict = {}
    if subscribers is not None:
        metrics["followers"] = float(subscribers)
    if median_views is not None:
        metrics["avg_views"] = median_views
    # The rate is only meaningful when BOTH numbers are real, and it is stored
    # next to them so it can always be recomputed — unlike the bundled rows
    # flagged rate_reproducible: false.
    if subscribers and median_views is not None and subscribers > 0:
        metrics["resonance_rate"] = round(median_views / subscribers * 100, 2)
        metrics["rate_reproducible"] = True
        metrics["followers_scope"] = "youtube"
        metrics["resonance_sample_size"] = sample

    return discovery.candidate(
        name=snippet.get("title") or "",
        handle=(snippet.get("customUrl") or "").lstrip("@"),
        platform="youtube",
        source=NAME,
        search_source=search_source,
        confidence=(
            config.CONFIDENCE_MEASURED if metrics.get("resonance_rate") is not None
            else config.CONFIDENCE_CANDIDATE
        ),
        channel_id=item.get("id", ""),
        location=snippet.get("country", ""),
        notes=(snippet.get("description") or "")[:280],
        **metrics,
    )


class YouTubeSource:
    """discovery.Source over the YouTube Data API."""

    name = NAME

    def __init__(self, terms: list[str] | None = None, budget: QuotaBudget | None = None):
        self._terms = terms
        self._budget = budget

    def available(self) -> tuple[bool, str]:
        if not config.YOUTUBE_API_KEY:
            return False, (
                "no YOUTUBE_API_KEY set — this source is wired but has never made a "
                "real call. Set the environment variable to enable it."
            )
        return True, ""

    def terms_for(self, brief: dict) -> list[str]:
        """Search terms, reusing the query plan so both sources agree."""
        if self._terms is not None:
            return self._terms
        from sources import query_plan

        plan = query_plan.build(brief)
        return [
            q["term"] for q in plan["passes"][0]["queries"]
            if q["platform"] == "youtube"
        ] if plan["passes"] else []

    def search(self, brief: dict) -> discovery.SourceResult:
        budget = self._budget or QuotaBudget()
        terms = self.terms_for(brief)
        if not terms:
            return discovery.SourceResult(
                source=self.name, notes=["no YouTube search terms derived from the brief"]
            )

        channel_ids, notes, truncated = search_channel_ids(terms, budget)
        if len(channel_ids) > config.DISCOVERY_MAX_PER_SOURCE:
            notes.append(
                f"{len(channel_ids)} channels found; capped at "
                f"{config.DISCOVERY_MAX_PER_SOURCE}. The rest were not enriched."
            )
            channel_ids = channel_ids[:config.DISCOVERY_MAX_PER_SOURCE]
            truncated = True

        channels = fetch_channels(channel_ids, budget)
        if len(channels) < len(channel_ids):
            truncated = True
            notes.append(
                f"enriched {len(channels)} of {len(channel_ids)} channels before the "
                f"quota budget ran out."
            )

        search_source = f"youtube search: {len(terms)} terms"
        candidates = [
            _to_candidate(item, search_source, budget) for item in channels.values()
        ]

        return discovery.SourceResult(
            source=self.name,
            candidates=candidates,
            truncated=truncated,
            notes=notes,
            queries_run=len(terms) if not truncated else len(terms) - 1,
            quota_spent=budget.spent,
        )
