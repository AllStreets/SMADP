# SMADP — Press Kit

Everything you need to write about, link to, or post SMADP. Last updated for the
v2 ("Proving Ground") launch. Copy freely.

**Live catalog (no account):** https://allstreets.github.io/SMADP/
**Repo:** https://github.com/AllStreets/SMADP

---

## One-liner

SMADP is a public, evidence-grounded catalog that answers one question for every
pair of AI agents: can they safely share a runtime — and if not, exactly why?

## Boilerplate (three lengths)

**Short (tweet-length):**
> A public safety catalog for multi-agent systems. SMADP scores every pair of AI
> agents on whether they can safely share a runtime, grounds each finding in
> evidence, and publishes the reasoning. 587 verdicts, browsable with no account.

**Medium (one paragraph):**
> SMADP is an open catalog of pairwise risk between AI agents. For any two agents
> that might share a workspace — passing files, calling each other over MCP,
> reading each other's output — it scores five risk categories independently
> (including prompt injection between agents, secret leakage across a handoff,
> and privilege escalation through a partner's authority). Scores are
> deterministic and reproducible, every claim is grounded in the agents' profile
> evidence, and confidence is shown on an explicit five-rung ladder. It is
> entirely open and browsable with no account.

**Long (for an article intro):**
> As teams move from single AI agents to multi-agent systems, a new and largely
> unmeasured risk appears: the interaction between agents that share a runtime.
> One agent can inject instructions into another through a shared file; sensitive
> data can cross an agent handoff into a different model backend; an agent can
> act through a partner's broader permissions. SMADP is the first public,
> structured catalog of this risk. It profiles agents, then for each pair scores
> a fixed five-category rubric — with the per-category severities proposed by an
> LLM at temperature zero and the composite score computed deterministically in
> code, so verdicts reproduce. Every claim points to specific agent profile
> fields, backed by content-addressed evidence. An autopilot continuously judges
> new pairs while a human gate decides what gets published. Today there are 587
> published verdicts over 6,000+ agent profiles, all open, with a 3-D interactive
> risk atlas and a per-verdict causal-risk graph.

---

## Key facts

| | |
|---|---|
| What it is | Public catalog of pairwise risk between AI agents |
| Live now | 587 published verdicts · 6,000+ agent profiles · 1,293 evidence chunks |
| Risk model | 5 categories scored independently; severities `none → critical` |
| Reproducible | Composite score computed in code; LLM emits severities/rationales at temp 0 |
| Evidence ladder | 5 rungs: `docs-only` → `behavior-observed` → `profile-verified` → `sandbox-validated` (+ unverified) |
| Engine | Autopilot judges pairs continuously; human gate publishes |
| Visuals | 3-D WebGL risk atlas; per-verdict causal-risk graph |
| License / access | Open source; browsable with no account |
| Engineering | ~960 tests, CI-gated (ruff + mypy + pytest) |

## The story / what's novel

There are plenty of single-model evals. There was nothing for the *interaction*
between two agents in the same runtime. SMADP is that missing dataset — closer to
a CVE catalog for agent combinations than to a benchmark. The novelty is the unit
of analysis (the pair) plus the rigor: deterministic scoring, evidence grounding,
and an honest confidence ladder that labels low-evidence verdicts as such instead
of overclaiming.

## Screenshots

All in [`assets/`](assets/). Captions are press-ready.

- **`assets/smadp-risk-atlas.png`** — "The agent web": the 3-D risk atlas, every
  published verdict as an edge (colored by worst sub-verdict severity) between
  agents (colored by evidence tier). The hero image.
- **`assets/smadp-verdict.png`** — A single pairwise verdict: composite score,
  confidence, and the five risk categories with severity bars.
- **`assets/smadp-evidence.png`** — The "Grounded in" evidence section: each
  claim tied to the exact agent profile fields it rests on.
- **`assets/smadp-verdicts-index.png`** — The catalog wall: hundreds of published
  verdicts, filterable by tier and confidence.
- **`assets/smadp-home.png`** — The landing page.

## Links

- Live catalog: https://allstreets.github.io/SMADP/
- Risk atlas: https://allstreets.github.io/SMADP/risk-atlas/
- Methodology: https://allstreets.github.io/SMADP/methodology/
- Repo: https://github.com/AllStreets/SMADP

## Maker quote

> "People are wiring AI agents together and nobody had a reference for which
> combinations are dangerous. SMADP is that reference — and the methodology is
> open precisely so people can argue with it."

## Brand notes

- Name is **SMADP** (all caps).
- No emoji in any official copy; the aesthetic is dark, precise, systems-grade.
- Always pair a claim with the access path ("browsable, no account") — the
  zero-friction catalog is the conversion.
- Be honest about the evidence ladder; most verdicts are `docs-only` and that is
  a feature of the methodology, not a caveat to hide.
