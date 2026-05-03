# SMADP v2 Backlog

Out of scope for v1 — to be brainstormed and specified separately.

## Items

- **Live user-facing Lab** — interactive sandbox UI where end users (not just CI/operators) can submit two agents and watch a transcript stream live, scrub through events, and replay. v1 is batch-only with static evidence files.

- **Capability adapters for closed-source agents** (path B from Q6) — wrappers that let SMADP profile/sandbox agents whose source code isn't available, by intercepting their tool-call surface (HTTP, MCP, stdio) and synthesizing a static profile from observed behavior + declared manifest. v1 only profiles open-source agents we can read.

- **Multi-agent chains of 3+ agents** — verdicts on N-way deployment topologies (A→B→C, fan-out, mesh). Requires extending the risk model from pairwise composition to graph composition. v1 is strictly pairwise.

- **Audience C/D coverage** — anything in scope from the C (compliance/auditor) and D (executive/buyer) audiences that v1's A/B (developer/operator) cuts didn't address.

## Process

Each of these gets its own brainstorm → spec → plan cycle. Don't bundle.
