"""The query plan — Step 2 of the spec, implemented literally.

The spec says Step 2 "produces a query plan and candidate pool. It does not
produce verified metrics." That is not a limitation to work around; it is the
honest shape of the problem. TikTok and Instagram expose nothing free about
accounts you do not own, and the spec's strongest passes — competitor
sponsorship audits, subreddit and Discord moderators — are judgement work no
vendor will ever automate.

So this source does not call anything. It builds **real, clickable search URLs**
from the brief, the operator runs them in a browser, and pastes back the handles
they found. That keeps a human in exactly the passes that need one, and it works
today for every platform, with no key and no spend.

Terms carry provenance like everything else here. A term lifted from the spec is
marked `spec`; one derived from the brief is marked `brief`. And spec terms are
only used when the brief is for the campaign the spec was written about — the
same non-transfer rule that governs `readiness_category`, for the same reason:
Craftly's hashtags are evidence about Craftly's campaign, not a tablet's.
"""

from __future__ import annotations

import re
import urllib.parse

import agent_spec
import config
import discovery

NAME = "query_plan"

# Per-platform search surfaces. Each is a real URL a person can click.
TEMPLATES = {
    "youtube": {
        "keyword": "https://www.youtube.com/results?search_query={q}&sp=CAMSAhAB",
        "label": "YouTube search, sorted by view count",
    },
    "tiktok": {
        "keyword": "https://www.tiktok.com/search?q={q}",
        "hashtag": "https://www.tiktok.com/tag/{q}",
        "label": "TikTok — search by content, then sort by views, not account size",
    },
    "instagram": {
        "hashtag": "https://www.instagram.com/explore/tags/{q}/",
        "label": "Instagram Reels by hashtag — filter on view count, not followers",
    },
    "linkedin": {
        "keyword": "https://www.linkedin.com/search/results/content/?keywords={q}",
        "label": "LinkedIn content search",
    },
}

# Search Pass 4 — community discovery. No API surfaces moderators, so these are
# links a person reads.
SUBREDDITS = ("college", "productivity", "nocode", "learnprogramming")

# Words that carry no search signal on their own.
_STOPWORDS = {
    "a", "an", "and", "for", "from", "in", "of", "on", "or", "the", "to", "that",
    "with", "who", "want", "without", "their", "them", "it", "is", "are", "as",
    "by", "be", "into", "at", "this", "plain", "working", "knowing", "build",
    # Words that describe an audience without naming one — "aged 18-24" gave
    # "AI app-building tools for aged", which is not a search anyone would run.
    "aged", "skews", "whose", "dominant", "audience", "creators", "years", "olds",
    "description", "english", "builds", "using", "makes", "where", "which",
    "positions", "wants", "want",
}


def _slug(text: str) -> str:
    """A hashtag-safe token: letters and digits only."""
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def _terms_from_brief(brief: dict) -> list[dict]:
    """Mechanically derive search terms from brief fields.

    Deliberately mechanical rather than model-generated: every term here can be
    traced to a field the operator typed, so the plan is auditable and stable
    across runs. The operator edits what they do not like — these are a starting
    point, not a validated keyword set, and the screen says so.
    """
    terms: list[dict] = []
    seen: set[str] = set()

    def add(text: str, origin: str):
        cleaned = " ".join(str(text or "").split()).strip()
        if cleaned and cleaned.lower() not in seen and len(cleaned) > 2:
            seen.add(cleaned.lower())
            terms.append({"term": cleaned, "origin": origin})

    category = str(brief.get("category") or "").strip()
    add(category, "brief")

    # Category crossed with the audience noun gives the highest-signal queries,
    # e.g. "AI app-building tools for students".
    audience_words = [
        w for w in re.findall(r"[a-zA-Z]{4,}", str(brief.get("target_audience") or ""))
        if w.lower() not in _STOPWORDS
    ]
    for word in audience_words[:3]:
        if category:
            add(f"{category} for {word.lower()}", "brief")

    # Noun-ish phrases from the product description.
    description_words = [
        w.lower() for w in re.findall(r"[a-zA-Z]{5,}", str(brief.get("product_description") or ""))
        if w.lower() not in _STOPWORDS
    ]
    for word in description_words[:4]:
        add(word, "brief")

    return terms


def _spec_terms(brief: dict) -> tuple[list[dict], str]:
    """Seed terms lifted from the spec's Step 2, when the brief is that campaign.

    Returns (terms, note). The spec's hashtags are written for one named
    campaign. Reusing them for a different one would be the discovery equivalent
    of transferring a readiness judgement across categories, so they are used
    only when the brief names that campaign's brand, and a mismatch is reported
    rather than hidden.
    """
    try:
        slot = agent_spec.campaign_slot()
    except Exception:  # noqa: BLE001 — a missing spec must not break discovery
        return [], "spec unavailable"

    # The spec's campaign slot has no explicit category field — it identifies its
    # campaign by BRAND — so the brand is what the seed terms belong to.
    spec_brand = str(slot.get("BRAND") or slot.get("CAMPAIGN") or "").strip()
    brief_brand = str(brief.get("brand_name") or "").strip()
    if not spec_brand or not brief_brand:
        return [], ""
    if brief_brand.lower() not in spec_brand.lower():
        campaign = str(slot.get("CAMPAIGN") or spec_brand)
        return [], (
            f"the spec's seed hashtags were written for “{campaign}”; this brief is "
            f"for “{brief_brand}”, so only terms derived from the brief are used"
        )

    try:
        step2 = agent_spec.sections().get("Step 2 — Discovery Playbook", "")
    except Exception:  # noqa: BLE001
        return [], ""

    terms, seen = [], set()
    for tag in re.findall(r"#([A-Za-z0-9_]{3,})", step2):
        if tag.lower() not in seen:
            seen.add(tag.lower())
            terms.append({"term": tag, "origin": "spec", "hashtag": True})

    for phrase in _keyword_phrases(step2):
        if phrase.lower() not in seen:
            seen.add(phrase.lower())
            terms.append({"term": phrase, "origin": "spec"})
    return terms, ""


def _keyword_phrases(step2: str) -> list[str]:
    """Quoted phrases from the spec's "Priority keywords:" blocks only.

    Taking every quoted string in Step 2 also picks up the method prose — "related
    channels", "similar accounts", "I post about" — which describe how to search,
    not what to search for. Those made the plan look thorough while sending the
    operator after nothing.
    """
    phrases: list[str] = []
    capturing = False
    for line in step2.splitlines():
        stripped = line.strip()
        if re.match(r"(?i)priority keywords\s*:", stripped):
            capturing = True
        elif capturing and not stripped.startswith('"'):
            # The block ends at the first line that is not a continuation.
            capturing = False
        if not capturing:
            continue
        for phrase in re.findall(r'"([^"]{6,60})"', stripped):
            # Placeholders like "[brand] + #ad" are templates, not search terms.
            if "[" in phrase or "]" in phrase:
                continue
            phrases.append(phrase.strip())
    return phrases


def build(brief: dict) -> dict:
    """Build the full click-through plan for a brief."""
    platforms = [p for p in (brief.get("platforms") or []) if p in TEMPLATES]
    spec_terms, spec_note = _spec_terms(brief)
    brief_terms = _terms_from_brief(brief)
    terms = brief_terms + spec_terms

    passes = []

    # --- Pass 1: hashtag and content sweep ---------------------------------
    queries = []
    for platform in platforms:
        template = TEMPLATES[platform]
        for entry in terms:
            is_tag = entry.get("hashtag")
            kind = "hashtag" if is_tag and "hashtag" in template else "keyword"
            if kind not in template:
                continue
            raw = _slug(entry["term"]) if kind == "hashtag" else entry["term"]
            if not raw:
                continue
            queries.append({
                "platform": platform,
                "kind": kind,
                "term": entry["term"],
                "origin": entry["origin"],
                "url": template[kind].format(q=urllib.parse.quote(raw)),
            })
    passes.append({
        "pass": "Pass 1 — hashtag and content sweep",
        "what_to_look_for": (
            "Sort by views, not follower count. A viral post from a smaller account "
            "is the signal; a big account with flat views is not."
        ),
        "queries": queries,
    })

    # --- Pass 2: competitor brand audit ------------------------------------
    exclusions = [
        e.strip() for e in str(brief.get("exclusions") or "").split(",") if e.strip()
    ]
    competitor_queries = []
    for brand in exclusions:
        for platform in platforms:
            site = {"youtube": "youtube.com", "tiktok": "tiktok.com",
                    "instagram": "instagram.com", "linkedin": "linkedin.com"}[platform]
            q = f'site:{site} "{brand}" (#ad OR #sponsored OR #gifted)'
            competitor_queries.append({
                "platform": platform,
                "kind": "competitor",
                "term": brand,
                "origin": "brief",
                "url": "https://www.google.com/search?q=" + urllib.parse.quote(q),
            })
    passes.append({
        "pass": "Pass 2 — competitor brand audit",
        "what_to_look_for": (
            "Creators these brands have already paid are pre-qualified for the niche. "
            "Flag any exclusivity — they may be ineligible, and the engine will drop "
            "them on the exclusion gate anyway."
        ),
        "queries": competitor_queries,
    })

    # --- Pass 4: community and peer discovery ------------------------------
    community = []
    primary = terms[0]["term"] if terms else str(brief.get("category") or "")
    for sub in SUBREDDITS:
        community.append({
            "platform": "reddit",
            "kind": "community",
            "term": f"r/{sub}",
            "origin": "spec",
            "url": (
                f"https://www.reddit.com/r/{sub}/search/?"
                + urllib.parse.urlencode({"q": primary, "restrict_sr": "1", "sort": "top"})
            ),
        })
    passes.append({
        "pass": "Pass 4 — community and peer discovery",
        "what_to_look_for": (
            "Look for people ANSWERING questions, not asking them. Moderators and "
            "frequent helpful posters are the find here — no API exposes them."
        ),
        "queries": community,
    })

    notes = []
    if spec_note:
        notes.append(spec_note)
    if not platforms:
        notes.append("no briefed platform has a known search surface")
    notes.append(
        "These are search queries, not results. Nothing here has been validated — "
        "edit the terms, run what looks useful, and paste back the handles you find."
    )

    return {
        "passes": [p for p in passes if p["queries"]],
        "terms": terms,
        "notes": notes,
        "total_queries": sum(len(p["queries"]) for p in passes),
    }


# ---------------------------------------------------------------------------
# Paste-back — turning what the operator found into candidates
# ---------------------------------------------------------------------------
_HANDLE_LINE = re.compile(
    r"(?:(?P<url>https?://[^\s,]+)|(?P<handle>@?[A-Za-z0-9._-]{2,50}))"
)

_PLATFORM_BY_HOST = {
    "youtube.com": "youtube", "youtu.be": "youtube",
    "tiktok.com": "tiktok", "instagram.com": "instagram",
    "linkedin.com": "linkedin",
}


def _platform_from_url(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")
    return _PLATFORM_BY_HOST.get(host, "")


def _handle_from_url(url: str) -> str:
    path = urllib.parse.urlparse(url).path.strip("/")
    if not path:
        return ""
    first = path.split("/")[0]
    return discovery.normalise_handle(first)


def parse_pasted(text: str, platform: str = "", search_source: str = "manual paste") -> list[dict]:
    """Turn pasted handles or profile URLs into candidates.

    Produces rows with a handle, a platform and provenance — and deliberately no
    metrics. A pasted handle is a lead, not a measurement, so every row here is
    NEEDS_REFRESH until something real fills the numbers in. That is the correct
    and honest outcome, not a shortcoming of the paste box.
    """
    rows, seen = [], set()
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip().strip(",;")
        if not line or line.startswith("#"):
            continue

        match = _HANDLE_LINE.search(line)
        if not match:
            continue

        if match.group("url"):
            url = match.group("url")
            row_platform = _platform_from_url(url) or platform
            handle = _handle_from_url(url)
            if not handle:
                continue
        else:
            handle = discovery.normalise_handle(match.group("handle"))
            row_platform = platform
            if not row_platform:
                # Without a platform the engine cannot pick a D3 instrument, so
                # the row would be unscoreable. Better to say so than to guess.
                continue

        key = (handle.lower(), row_platform)
        if not handle or key in seen:
            continue
        seen.add(key)

        rows.append(discovery.candidate(
            name=handle,
            handle=handle,
            platform=row_platform,
            source=NAME,
            search_source=search_source,
            confidence=config.CONFIDENCE_CANDIDATE,
        ))
    return rows


class QueryPlanSource:
    """Adapter form, so the plan appears in a discovery run alongside real sources.

    It never returns candidates on its own — it is the pass that hands work to a
    person. Reporting that honestly is more useful than omitting it, because an
    operator reading a results list should see that the manual passes exist and
    have not been run.
    """

    name = NAME

    def available(self) -> tuple[bool, str]:
        return True, ""

    def search(self, brief: dict) -> discovery.SourceResult:
        plan = build(brief)
        return discovery.SourceResult(
            source=self.name,
            candidates=[],
            notes=[
                f"{plan['total_queries']} searches to run by hand across "
                f"{len(plan['passes'])} passes — this source produces a plan, not creators"
            ] + plan["notes"],
            queries_run=0,
        )
