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

CREATOR_CSV = os.path.join(DATA_DIR, "sample_creators.csv")
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

# Engagement floors — a gate, not a tiebreaker (Step 3 / Hard Rules).
ENGAGEMENT_FLOORS = {
    "tiktok": 3.5,
    "instagram": 3.5,
    "youtube": 1.5,
}

# Engagement rubric: (min_rate, points) evaluated high-to-low, per Dimension 3.
ENGAGEMENT_RUBRIC = {
    "tiktok": [(8.0, 25), (5.0, 19), (3.5, 13)],
    "instagram": [(8.0, 25), (5.0, 19), (3.5, 13)],
    "youtube": [(4.0, 25), (2.0, 19), (1.5, 13)],
}
GENERIC_COMMENT_PENALTY = 3  # Dimension 3 comment-quality modifier

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
