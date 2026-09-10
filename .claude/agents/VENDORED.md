# Vendored agents

These subagents come from **[msitarzewski/agency-agents](https://github.com/msitarzewski/agency-agents)**,
MIT licensed. The upstream licence is kept verbatim beside this file as `LICENSE.upstream`.

Upstream commit at time of vendoring: see `Source commit` below.

## What was changed

Each agent's **body is byte-identical to upstream**. Only the YAML frontmatter was
rewritten, because upstream targets its own installer while Claude Code needs a
subagent slug:

| Upstream | Here | Why |
|---|---|---|
| `name: Reality Checker` | `name: reality-checker` | `name` is the `subagent_type` you pass to the Agent tool, so it has to be a slug |
| `description:` (who the agent *is*) | same text + a "Use when…" clause | the description is what selects the agent, so it needs a trigger, not just an identity |
| `color:`, `emoji:`, `vibe:` | dropped | not part of the Claude Code subagent schema |

An HTML comment noting provenance sits at the top of each body.

## The roster

| Agent | Use it for |
|---|---|
| `backend-architect` | Flask routes, API contracts, app structure |
| `frontend-developer` | Jinja templates, markup, client-side behaviour |
| `ui-designer` | screen layout, visual hierarchy, component styling |
| `rapid-prototyper` | standing up a working end-to-end slice fast |
| `code-reviewer` | reviewing a diff before it is committed |
| `technical-writer` | README and developer documentation |
| `reality-checker` | certifying that something is actually done — defaults to NEEDS WORK |
| `evidence-collector` | gathering command output and proof instead of asserting success |

The last two matter most on this project. `HANDOVER.md` carries a **"Verification still
owed"** list, and `CLAUDE.md`'s top constraint is *never fabricate creator metrics* — both
are failure modes of claiming rather than checking.

## What these agents do not override

A vendored agent is a working style, not an authority. The hard constraints in
`creator-scout-agent/CLAUDE.md` win in every case:

1. Never fabricate creator metrics — missing data becomes `NEEDS_REFRESH`.
2. Never modify the scoring weights (.30/.25/.25/.10/.10).
3. Campaign role comes from the D1/D2 relationship, not the total score.

If an agent's generic advice conflicts with those, the project rule stands.

## Re-vendoring

Upstream also ships ~300 more agents across `design/`, `marketing/`, `sales/`,
`product/`, `security/` and others. To add one:

```bash
git clone --depth 1 https://github.com/msitarzewski/agency-agents /tmp/agency-agents
# copy the file into .claude/agents/<slug>.md, then rewrite the frontmatter per the
# table above — slug name, description with a "Use when…" clause, drop color/emoji/vibe
```

---

**Source commit:** `6d29a9b08785a0e49ffc9818bbdd381164c2df5f` (2026-09-08), vendored 2026-09-10.
