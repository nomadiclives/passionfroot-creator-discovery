"""Discovery source adapters.

Each module here implements the `discovery.Source` protocol: `available()` says
whether it can run, `search(brief)` returns a `SourceResult`. Adding a source is
adding a file — nothing else in the app changes.

    query_plan  free, no key. Builds click-through searches for a human to run.
    youtube     free, needs YOUTUBE_API_KEY. Real search and real metrics.

See DISCOVERY_PLAN.md for the tiers that are scoped but not built.
"""
