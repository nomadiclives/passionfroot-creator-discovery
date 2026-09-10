# passionfroot-creator-discovery

Creator discovery and scoring for paid UGC and awareness campaigns. Give it a campaign
brief; it returns a scored, role-assigned creator shortlist ready for outreach — with its
gaps labelled rather than filled in.

The working project lives in **[`creator-scout-agent/`](creator-scout-agent/)**.

```bash
cd creator-scout-agent
pip install -r requirements.txt
python app.py                 # http://localhost:5000
python -m pytest tests/       # 86 tests
```

Full documentation: [`creator-scout-agent/README.md`](creator-scout-agent/README.md).

## What it does

Five scored dimensions (audience, content, resonance, geography, commercial maturity),
combined under weights fixed by the skill spec, plus eligibility gates that run *before*
scoring and override it. Output is a ranked shortlist with a campaign role per creator,
a composition panel against target, CPM-modelled budget, and a CSV export.

It ships with a real campaign — **Craftly for Students** — and 20 creators sourced from
the product owner's sheet, plus a 5-creator LinkedIn cohort awaiting metrics.

## The idea it is built around

Most shortlisting tools optimise for looking complete. This one optimises for being
trustworthy, which means it is built to **refuse**:

- **It never invents a metric.** A missing number is reported as a gap (`NEEDS_REFRESH`),
  never estimated. Every metric carries its source and sourced date.
- **It never invents a judgement.** Dimensions a human must score, and the category
  readiness that assigns campaign role, come back `NEEDS_REVIEW` when absent — and a
  readiness judgement is evidence about *one named category*, so it does not transfer to
  a brief about something else.
- **It never invents a scale.** A platform whose resonance instrument has no fitted bands
  returns `NEEDS_CALIBRATION` rather than a guessed band. LinkedIn is uncalibrated today.
- **It never hides a refusal.** Every evaluated creator stays on screen with its reason.
  A row that disappears is indistinguishable from a creator nobody sourced.

The corollary is that an empty result can be the correct answer, and the app is built to
say so on screen instead of looking broken.

It also agrees with expert judgement rather than quietly re-ranking: the engine
reproduces **16 of 17** hand-scored rows from the product owner's sheet exactly, and adds
gates on top. The one divergence is the sheet applying its own ladder inconsistently,
pinned in a test rather than papered over.

## Repository layout

| Path | What it is |
|---|---|
| [`creator-scout-agent/`](creator-scout-agent/) | The app — engine, web UI, scheduler, tests |
| [`creator-scout-agent/agents/`](creator-scout-agent/agents/) | The skill spec of record, checked in and loaded at runtime |
| [`creator-scout-agent/HANDOVER.md`](creator-scout-agent/HANDOVER.md) | Build state, what is verified, what is still open |
| [`.claude/agents/`](.claude/agents/) | Subagents used to build this, vendored from [agency-agents](https://github.com/msitarzewski/agency-agents) (MIT) |
| [`CLAUDE.md`](CLAUDE.md) | Contributor rules — read before changing scoring |

⚠️ Note the naming collision: `.claude/agents/` holds **subagents you can invoke**, while
`creator-scout-agent/agents/` holds the **scoring spec of record**. Different things — do
not merge them.

## Before you change anything

Two rules break the product if violated, and both are guarded by tests:

1. **Never fabricate creator metrics.** Emit a gap and flag the row.
2. **Never modify the scoring weights** (.30 / .25 / .25 / .10 / .10). They are locked in
   two directions — a test pins the values, and the app fails its suite if `config.py`
   and the spec drift apart.

The full set is in [`CLAUDE.md`](CLAUDE.md) and
[`creator-scout-agent/CLAUDE.md`](creator-scout-agent/CLAUDE.md).

## Known limitation

Dimension 3's TikTok/Instagram ladder saturates — it is an engagement-rate ladder being
fed view-rate data, so 14 of 20 creators score 5/5. A refit was attempted and reverted
because the source rates use inconsistent denominators. The fix is per-platform follower
counts, not new bands; a test keeps the weakness visible until then. See
[`HANDOVER.md`](creator-scout-agent/HANDOVER.md).
