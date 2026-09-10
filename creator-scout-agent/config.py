"""Configuration for the Creator Campaign Scout Agent.

Everything the skill calls a "Campaign Slot" value lives here as a default. The web
form overrides these per-run; the scheduler reads them for unattended runs.

Do NOT change SCORING_WEIGHTS. They are fixed by creator-campaign-scout.md.
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
AGENTS_DIR = os.path.join(BASE_DIR, "agents")

# The skill file is the spec of record for the scoring model. It is checked in so
# the app can load and display it at runtime — see agent_spec.py.
SPEC_FILE = os.path.join(AGENTS_DIR, "creator-campaign-scout.md")

CREATOR_DATA = os.path.join(DATA_DIR, "creators.json")
CREATOR_CSV = CREATOR_DATA  # legacy alias

# Uploaded creator pools are parked here so an Export CSV re-run scores the same
# rows the screen showed. Ephemeral by design — see UPLOAD_RETENTION_HOURS.
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
UPLOAD_MAX_BYTES = 4 * 1024 * 1024
UPLOAD_RETENTION_HOURS = 6
PIPELINE_INTEL = os.path.join(DATA_DIR, "pipeline_intel.json")
SCHEDULE_STATE = os.path.join(DATA_DIR, "schedule_state.json")
SCHEDULER_LOG = os.path.join(LOGS_DIR, "scheduler.log")


# --------------------------------------------------------------------------
# API enrichment — see enricher.py
# --------------------------------------------------------------------------
ENRICHMENT_ENABLED = False  # Set to True when API credentials are available
API_PROVIDER = "favikon"    # or "modash"
API_KEY = ""

API_TIMEOUT_SECONDS = 10
API_BASE_URLS = {
    "favikon": "https://api.favikon.com/v1",
    "modash": "https://api.modash.io/v1",
}


# --------------------------------------------------------------------------
# Discovery — Steps 2 and 3 of creator-campaign-scout.md
# See DISCOVERY_PLAN.md. Nothing here fabricates a creator: a source adapter
# returns what it got, and an absent field stays absent.
# --------------------------------------------------------------------------
DISCOVERY_DIR = os.path.join(DATA_DIR, "discovery")

# YouTube Data API v3 — the free tier, and the only source that is official,
# permitted and returns real audience-side numbers. Off until a key is present.
# Never commit a key: this reads the environment.
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"

# Quota is the binding constraint, so it is modelled rather than discovered by
# failing. Defaults are Google's published costs; a project starts at 10,000/day.
YOUTUBE_QUOTA_PER_DAY = 10_000
YOUTUBE_QUOTA_COSTS = {
    "search": 100,   # search.list — expensive, ~100 calls/day is the whole budget
    "channels": 1,   # channels.list — batches up to 50 ids
    "videos": 1,     # videos.list — batches up to 50 ids
    "commentThreads": 1,
}
YOUTUBE_BATCH_SIZE = 50          # ids per channels.list / videos.list call
YOUTUBE_VIDEOS_SAMPLED = 10      # recent videos used for the median view count

# How many candidates a single discovery run may return per source. A cap that
# is hit must be reported, never silently truncated — see discovery.py.
DISCOVERY_MAX_PER_SOURCE = 200

# Confidence a source's output carries. This is about the SOURCE, not the
# creator: it records how the row was obtained so a reader can weigh it.
CONFIDENCE_MEASURED = "measured"    # a real metric from an official API
CONFIDENCE_REPORTED = "reported"    # self-reported (media kit, bio)
CONFIDENCE_CANDIDATE = "candidate"  # a handle with no metrics attached yet


# --------------------------------------------------------------------------
# Scoring model — Step 5 of creator-campaign-scout.md
# LOCKED. Do not modify. See CLAUDE.md.
# --------------------------------------------------------------------------
SCORING_WEIGHTS = {
    "audience_match": 0.30,
    "content_match": 0.25,
    "engagement_score": 0.25,
    "geo_score": 0.10,
    "commercial_maturity": 0.10,
}

# The skill states the same model in points out of 100. Sub-scores are held on a
# 1-5 scale for display; weighted_score * 20 == the skill's /100 total exactly.
DIMENSION_POINTS = {
    "audience_match": 30,
    "content_match": 25,
    "engagement_score": 25,
    "geo_score": 10,
    "commercial_maturity": 10,
}

SCORE_TIERS = [
    (75, "Tier 1 — Priority Outreach"),
    (55, "Tier 2 — Strong Candidates"),
    (35, "Tier 3 — Stretch / Backup"),
    (0, "Below Tier — Do Not Pitch"),
]

# Role assignment cut (Step 5a). Applied to the 1-5 sub-scores.
ROLE_THRESHOLD = 4.0

# --------------------------------------------------------------------------
# Dimension 3 — Audience Resonance
#
# The CONSTRUCT is invariant: how strongly does a creator's audience show up
# for their content? The INSTRUMENT that measures it is not. Platforms are not
# commensurable:
#
#   - Feed video (TikTok, Reels, Shorts, YouTube) exposes a view count, so
#     resonance is measured as views / followers ON THAT PLATFORM.
#   - Static and text formats (Instagram carousels, LinkedIn posts) expose no
#     view count at all, so resonance is measured as interactions / followers.
#
# A raw rate is therefore MEANINGLESS across instruments: 30% view rate on
# TikTok, 30% on YouTube and 30% interaction rate on LinkedIn are three
# different events. Each instrument carries its own bands and normalises to the
# same 1-5 scale. Only the NORMALISED score is comparable — never the raw rate.
#
# `bands` are (min_rate, score_1_5) evaluated high-to-low; anything below the
# last band scores 1. `bands: None` means the instrument is NOT YET CALIBRATED:
# the engine refuses to score it rather than inventing a number.
# --------------------------------------------------------------------------
METRIC_VIEW_RATE = "view_rate"              # avg views of last 5 posts / followers
METRIC_INTERACTION_RATE = "interaction_rate"  # (reactions+comments+reposts) / followers

INSTRUMENTS = {
    "tiktok": {
        "metric": METRIC_VIEW_RATE,
        "label": "View rate",
        # The product owner's own ladder, restored 2026-09-10. A refit was
        # attempted and REVERTED: the sheet's rates use inconsistent
        # denominators (8 rows divide one platform's views by followers summed
        # across ALL platforms, 11 rows use a single platform), so the rates are
        # not comparable to each other and cannot be ranked against fitted
        # bands. Refitting demoted Harper Carroll from 1st to 10th on what was a
        # denominator artifact, not a weakness.
        # KNOWN LIMITATION: this ladder saturates — it is an engagement-rate
        # ladder fed view-rate data, so 14 of 20 creators score 5/5 and a
        # quarter of the total does little discriminating work. Fixing it needs
        # per-platform follower counts. See HANDOVER.md.
        "bands": [(8.0, 5), (5.0, 4), (3.0, 3), (1.0, 2)],
        "calibration": "owner-ladder-known-saturating",
    },
    "instagram": {
        "metric": METRIC_VIEW_RATE,
        "label": "View rate",
        # The product owner's own ladder, restored 2026-09-10. A refit was
        # attempted and REVERTED: the sheet's rates use inconsistent
        # denominators (8 rows divide one platform's views by followers summed
        # across ALL platforms, 11 rows use a single platform), so the rates are
        # not comparable to each other and cannot be ranked against fitted
        # bands. Refitting demoted Harper Carroll from 1st to 10th on what was a
        # denominator artifact, not a weakness.
        # KNOWN LIMITATION: this ladder saturates — it is an engagement-rate
        # ladder fed view-rate data, so 14 of 20 creators score 5/5 and a
        # quarter of the total does little discriminating work. Fixing it needs
        # per-platform follower counts. See HANDOVER.md.
        "bands": [(8.0, 5), (5.0, 4), (3.0, 3), (1.0, 2)],
        "calibration": "owner-ladder-known-saturating",
    },
    "youtube": {
        "metric": METRIC_VIEW_RATE,
        "label": "View rate",
        # Carried over unchanged from the hand-scored sheet, where this ladder
        # discriminated correctly across the YouTube cohort (scores 2-5).
        "bands": [(35.0, 5), (20.0, 4), (10.0, 3), (5.0, 2)],
        "calibration": "sheet-derived",
    },
    "linkedin": {
        "metric": METRIC_INTERACTION_RATE,
        "label": "Interaction rate",
        # NOT CALIBRATED. LinkedIn does not publish impressions, so resonance
        # must come from interactions/followers — and no band boundaries have
        # been fitted against real roster data yet. Until they are, LinkedIn
        # creators return NEEDS_CALIBRATION on D3 instead of a guessed score.
        "bands": None,
        "calibration": "uncalibrated",
    },
}

PLATFORM_SLUGS = tuple(INSTRUMENTS)

GENERIC_COMMENT_PENALTY = 0.6  # D3 comment-quality modifier, on the 1-5 scale


# --------------------------------------------------------------------------
# Step 3 gates — eligibility, decided BEFORE any scoring.
#
# A gate is not a low score. A newsletter cannot shoot a video: it is not a
# weak candidate for this campaign, it is not a candidate at all.
# --------------------------------------------------------------------------
# What a creator can physically produce, by the surfaces they publish on.
FORMAT_CAPABILITIES = {
    "tiktok": {"short_video"},
    "instagram": {"short_video", "static"},
    "youtube": {"long_video", "short_video"},
    "linkedin": {"text", "static", "short_video"},
    "newsletter": {"written"},
    "twitter": {"text"},
    "podcast": {"audio"},
}

# What the Craftly brief actually asks for: 2 original videos + crossposts.
DEFAULT_DELIVERABLE_FORMATS = ("short_video", "long_video")


# --------------------------------------------------------------------------
# Campaign role (Step 5a) — a CLASSIFICATION, not a score.
#
# Role reads the audience's relationship to the campaign's product CATEGORY,
# not the creator's sub-scores. D1xD2 was a lossy proxy for this: it measures
# who the audience is and what the creator makes, then infers readiness. On the
# Craftly set it mislabelled 7 of 18 creators. Readiness is now explicit.
#
# The three levels are invariant. The CATEGORY they are judged against is a
# campaign parameter (see DEFAULT_BRIEF["category"]).
# --------------------------------------------------------------------------
READINESS_ROLES = {
    "unexposed": "Awareness",    # audience has little exposure to the category
    "exposed": "Credibility",    # audience consumes category content, adoption unproven
    "adopted": "Conversion",     # audience demonstrably uses the category
}
READINESS_ORDER = ("unexposed", "exposed", "adopted")

# CPM model — Step 1.
DEFAULT_CPM = 50.0
SPONSOR_DECAY = 0.85       # sponsored content underperforms organic by ~15%
VIDEOS_PER_CREATOR = 2     # deliverable: 2 original videos + crossposts

FOLLOWER_BANDS = {
    "micro": (50_000, 150_000),
    "mid": (150_000, 500_000),
    "macro": (500_000, 750_000),
    "all": (0, 10_000_000_000),
}

SHORTLIST_MIN = 15
SHORTLIST_MAX = 20

# Campaign composition target (Step 5a), for the summary panel.
COMPOSITION_TARGET = {
    "Awareness": (5, 7),
    "Credibility": (2, 4),
    "Conversion": (5, 7),
}

ROLE_COLOURS = {
    "Awareness": "blue",
    "Credibility": "green",
    "Conversion": "orange",
}


# --------------------------------------------------------------------------
# Default Campaign Slot — Craftly for Students
# --------------------------------------------------------------------------
DEFAULT_BRIEF = {
    "brand_name": "Craftly",
    "product_description": (
        "An AI tool that builds a working app from a plain-English description. "
        "Craftly for Students positions it as the tool for university students who "
        "want to build without knowing how to code."
    ),
    "campaign_goal": "awareness",
    # The product CATEGORY that Category Readiness is judged against.
    "category": "AI app-building tools",
    "deliverable_formats": ("short_video", "long_video"),
    "target_audience": (
        "US university students aged 18-24, or creators whose audience skews 18-24 "
        "and US-dominant."
    ),
    "platforms": ["tiktok", "instagram", "youtube"],
    "cpm": DEFAULT_CPM,
    "follower_band": "all",
    "shortlist_size": 18,
    "exclusions": "Bubble, Glide, Adalo, FlutterFlow, Softr",
}


# --------------------------------------------------------------------------
# Scheduler
# --------------------------------------------------------------------------
DEFAULT_CADENCE = "weekly"   # daily | weekly | biweekly
DEFAULT_RUN_DAY = "monday"
DEFAULT_RUN_TIME = "09:00"
CADENCES = ("daily", "weekly", "biweekly")
