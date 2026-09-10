# passionfroot-creator-discovery

The project lives in [`creator-scout-agent/`](creator-scout-agent/) — see
[`creator-scout-agent/CLAUDE.md`](creator-scout-agent/CLAUDE.md) for the stack, run
commands, and hard constraints (chiefly: never fabricate creator metrics, and never
change the scoring weights).

## Agent library

Subagents for building this project live in [`.claude/agents/`](.claude/agents/),
vendored from [msitarzewski/agency-agents](https://github.com/msitarzewski/agency-agents)
(MIT). See [`.claude/agents/VENDORED.md`](.claude/agents/VENDORED.md) for the roster and
what was adapted.

Note the naming collision: `.claude/agents/` holds **subagents you can invoke**, while
`creator-scout-agent/agents/` holds the **scoring spec of record**
(`creator-campaign-scout.md`). Different things — do not merge them.
