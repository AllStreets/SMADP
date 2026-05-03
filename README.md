<p align="center">
  <img src="https://img.shields.io/badge/SMADP-v0.1.0-7C3AED?style=for-the-badge" alt="Version"/>&nbsp;<img src="https://img.shields.io/badge/Python-3.11+-yellow?style=for-the-badge&logo=python&logoColor=white" alt="Python"/>&nbsp;<img src="https://img.shields.io/badge/License-Apache_2.0-22C55E?style=for-the-badge" alt="License"/>&nbsp;<img src="https://img.shields.io/badge/status-alpha-EA580C?style=for-the-badge" alt="Status"/>
</p>

<p align="center">
  <a href="https://allstreets.github.io/SMADP/">
    <img src="https://readme-typing-svg.demolab.com?font=JetBrains+Mono&weight=700&size=64&duration=1&pause=99999&color=7C3AED&center=true&vCenter=true&width=900&height=100&lines=S+M+A+D+P" alt="SMADP"/>
  </a>
</p>
<p align="center"><strong>Safe Multi-Agent Deployment Platform</strong></p>
<p align="center"><em>Auditable, evidence-cited verdicts on whether AI agents can safely run together.</em></p>

---

## What this is

You install Claude Code, then Cursor, then a calendar agent, then a notes agent, then an email-drafter. They share your filesystem, your clipboard, your OAuth scopes, your MCP servers. Nobody has systematically studied what happens when they interact — and the casual composition is becoming dangerous.

**SMADP publishes the matrix.** For every pair of popular agents (open-source from the [ONEXUS-Agents](https://github.com/AllStreets/ONEXUS-Agents) catalog plus the major closed-source ones — Claude Code, Cursor, ChatGPT Desktop, Perplexity, Windsurf, Devin, Replit Agent, Copilot, Gemini CLI, Notion AI), we publish a verdict: can these two run in the same environment, and if not, why not?

Every verdict is:

- **evidence-cited** — every claim points to a verbatim quote from the agent's docs, source, or ToS, with the source URL preserved
- **risk-typed** — five risk categories evaluated independently (prompt injection, data leakage, capability conflicts, cascading errors, compliance)
- **severity-tiered** — `none` / `low` / `medium` / `high` / `critical` per risk
- **conditional** — "safe IF you scope OAuth like X" rather than vague binary verdicts
- **mitigated** — every flagged risk includes concrete steps to make the pair safe
- **reproducible** — verdict carries the model version, rubric version, and content hashes
- **layered** — `evidence_level` field tells you whether this is `docs-only`, `profile-verified`, or `sandbox-validated`

The product is the catalog of verdicts. The dashboard, API, and CLI are surfaces on top of it.

---

## Quickstart

```bash
# Clone
git clone https://github.com/AllStreets/SMADP.git
cd SMADP

# Install
pip install -e ".[dev]"

# Lint the catalog (works offline against the seed data)
smadp lint

# Generate a verdict for a pair
smadp verdict claude-code cursor

# Submit a new agent for unverified profiling
smadp submit https://github.com/some-org/some-agent

# Start the local dashboard + API
smadp serve
```

---

## Risk taxonomy

| ID | Risk | Quick example |
|----|------|---------------|
| **A** | Prompt injection between agents | Email-drafter returns text that the note-taker ingests as a command |
| **B** | Data leakage / scope violations | Spreadsheet agent reads HR data; PowerPoint agent then exports a slide containing it |
| **C** | Capability / permission conflicts | Both agents authorized over the same Gmail account; one's writes break the other's assumptions |
| **D** | Cascading errors / hallucination amplification | Agent A confidently emits wrong fact; Agent B treats it as ground truth and compounds the error |
| **E** | Compliance / policy violations from composition | Each agent fine alone, but the combination violates GDPR / HIPAA / org policy |

B/C/D/E are weighted higher in the composite score; A is always evaluated.

---

## How verdicts are produced

Three layers of evidence, each with its own audit trail. Verdicts are tagged with `evidence_level` so readers know which layer(s) supported them.

```
                         +-----------+
                         |   USER    |
                         +-----+-----+
                               |
                       browse / submit / query
                               v
+==============================================================+
|                          S M A D P                           |
|                                                              |
|    +---------------------------------------------------+     |
|    |        Web Dashboard  /  REST API  /  CLI         |     |
|    +-------+-------------------+----------------+------+     |
|            |                   |                |            |
|         browse              submit           verdict         |
|            v                   v                v            |
|    +---------------------------------------------------+     |
|    |               CATALOG  (git-backed)               |     |
|    |   profiles/<slug>.json      verdicts/a__b.json    |     |
|    |   _evidence/      _meta/    _chronicle/           |     |
|    +-------+--------------------+----------------------+     |
|            ^                    ^                            |
|            |                    |                            |
|    +-------+--------+    +------+---------+                  |
|    |    Profiler    |    |    Pairwise    |                  |
|    |  (LLM + ext.)  |--->|    Analyzer    |                  |
|    +----------------+    |  (LLM-judge)   |                  |
|                          +--------+-------+                  |
|                                   |                          |
|                                   v                          |
|                          +----------------+                  |
|                          |    Sandbox     |                  |
|                          |   Validator    |                  |
|                          | (airtight, OS) |                  |
|                          +--------+-------+                  |
+===================================|==========================+
                                    |
                           +--------+----------+
                           |  Open-source MCP  |
                           |   agent runtime   |
                           |  (gVisor / Fcrk)  |
                           +-------------------+

   Sources for the Profiler:  GitHub / HuggingFace / vendor docs / user submissions.
```

1. **Static profile (always)** — a structured Safety Profile per agent: capabilities, IO surfaces, network egress, OAuth scopes, data classes, sandboxing model. Hand-verified for the seed catalog; auto-generated and flagged `unverified` for user-submitted agents.

2. **LLM-judge over profiles + cited evidence (always)** — Claude Sonnet 4.6 reasons over both profiles and the evidence bundle to produce per-risk sub-verdicts. Every claim cites a profile field and an evidence ID; every evidence ID is a content-addressed snippet of source material with the source URL preserved.

3. **Sandbox validation (open-source pairs only, v1)** — for open-source pairs with MCP adapters, both agents are run in an airtight container (rootless Podman + gVisor `runsc`, `--network none`, ephemeral tmpfs, `cap-drop ALL`) through scenario tasks. Observed behavior either confirms or contradicts the LLM-judge's verdict; the verdict is updated and `evidence_level` is promoted to `sandbox-validated`.

**Closed-source agents stay at `docs-only` in v1.** This is intentional — overclaiming kills credibility. Capability adapters for closed-source agents (driving Claude Code via the Anthropic API + the CLI binary in a container, etc.) are on the v2 roadmap.

---

## Catalog format

The catalog is a git repository. The git history *is* the audit log.

```
catalog/
├── profiles/                    # one JSON per agent
│   ├── claude-code.json
│   ├── cursor.json
│   ├── chatgpt-desktop.json
│   ├── perplexity.json
│   ├── ...
│   └── _unverified/             # user-submitted, not yet promoted
├── verdicts/                    # one JSON per alphabetized pair
│   ├── claude-code__cursor.json
│   └── ...
├── _evidence/                   # content-addressed source snippets
│   └── sha256-<hash>.json
├── _meta/
│   ├── categories.json
│   ├── risk-taxonomy.json
│   ├── frameworks.json          # NIST AI RMF + ISO 42001 mappings
│   ├── rubric/1.0.json          # LLM-judge rubric
│   └── schema/1.0/              # JSON Schemas
└── _chronicle/                  # YYYY-MM-DD.jsonl audit log
```

See [`docs/superpowers/specs/2026-05-02-smadp-design.md`](docs/superpowers/specs/2026-05-02-smadp-design.md) for the complete design.

---

## Verdict format

```json
{
  "schema_version": "1.0",
  "pair": ["claude-code", "cursor"],
  "verdict_id": "v_2026-05-02_claude-code__cursor_a3f1",
  "evidence_level": "docs-only",
  "confidence": 0.78,
  "composite_score": 0.42,
  "headline": "Caution — overlapping filesystem write surfaces and uncoordinated git state.",
  "sub_verdicts": {
    "A_prompt_injection": { "severity": "low", "rationale": "...", "citations": [...], "mitigations": [...] },
    "B_data_leakage": { "severity": "medium", "rationale": "...", "citations": [...], "mitigations": [...] },
    "C_capability_conflict": { "severity": "high", "rationale": "...", "citations": [...], "mitigations": [...] },
    "D_cascading_error": { "severity": "low", "rationale": "...", "citations": [...], "mitigations": [...] },
    "E_compliance": { "severity": "low", "rationale": "...", "citations": [...], "mitigations": [...] }
  },
  "framework_mappings": {
    "nist_ai_rmf": ["MEASURE-2.7", "MANAGE-2.3"],
    "iso_42001": ["A.7.4"]
  },
  "reproducibility": {
    "rubric_url": "/_meta/rubric/1.0.json",
    "profile_a_hash": "sha256:...",
    "profile_b_hash": "sha256:...",
    "evidence_bundle_hash": "sha256:..."
  }
}
```

---

## Composite score

Lower is safer. Severity → numeric: `none=0.0  low=0.2  medium=0.5  high=0.8  critical=1.0`.

```
composite = 0.30*B + 0.25*C + 0.20*D + 0.15*E + 0.10*A
```

Sub-verdicts are authoritative; the composite is informational and sortable.

---

## Submitting an agent

```bash
smadp submit https://github.com/your-org/your-agent
```

Or open a pull request:

1. Fork the repo
2. Add `catalog/profiles/<your-agent>.json` matching the schema in `_meta/schema/1.0/profile.schema.json`
3. Add evidence references for every populated field
4. Open a PR using the **Agent submission** template

CI runs `smadp lint` against your file. If schema and citation validation pass, an admin reviews and merges.

---

## Project layout

```
smadp/                Python package (Profiler, Analyzer, Sandbox, CLI, API)
catalog/              The catalog itself (profiles, verdicts, evidence, chronicle)
adapters/             MCP adapters for sandbox-runnable open-source agents
site/                 Astro 4 + Tailwind v4 dashboard
tests/                Test suite
docs/                 Methodology, threat model, evidence policy, framework mappings
```

---

## Design principles

**Evidence-first.** No claim without a citation. No citation without a verbatim quote and a source URL. No verdict without reproducibility hashes. If we cannot prove a claim, we leave the field empty rather than guess.

**Honest evidence levels.** A `docs-only` verdict and a `sandbox-validated` verdict look different in the UI on purpose. Overclaiming is fatal for a security platform.

**Git as audit log.** The catalog is a git repository. Every mutation is a commit. Reverting is a `git revert`. There is no separate "audit database" to fall out of sync.

**Closed-source asymmetry is honest.** v1 cannot sandbox Claude Code or Cursor. We say so prominently. Capability adapters land in v2.

**Open by default, paid never.** v1 is open-source self-host + a free hosted dashboard. There is no SaaS upsell path. The catalog must always be redistributable.

**Sibling, not successor.** SMADP is a sibling to [NEXUS](https://github.com/AllStreets/ONEXUS) and [ONEXUS-Agents](https://github.com/AllStreets/ONEXUS-Agents). Same DNA — local-first, transparent scoring, immutable audit, JSON-as-source-of-truth — different mission.

---

## License

Apache-2.0. The catalog is publicly redistributable. Each profiled agent retains its upstream license — see the `vendor` field on every catalog entry.

---

<p align="center"><sub>Built by <a href="https://github.com/AllStreets">Connor Evans</a></sub></p>
