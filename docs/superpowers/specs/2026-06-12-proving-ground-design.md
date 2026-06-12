# SMADP v2 — The Proving Ground

**Date:** 2026-06-12
**Branch:** `feat/proving-ground`
**Status:** Approved (direction approved by operator 2026-06-12; all three pillars selected)

## Mission

Move SMADP from a platform that *describes* multi-agent risk to one that *hunts, predicts,
and intercepts* it. Three pillars, shipped in order. Each pillar is independently valuable,
independently demo-able, and lands on the existing four-rung evidence ladder and operator
gate without weakening either.

Non-goals: replacing the existing pairwise judge, changing the deterministic scoring
contract (LLM assigns symbolic severities; Python computes composites), or touching the
nightly ONEXUS-Agents sync.

---

## Pillar S1 — Adversarial Proving Ground

Today the sandbox runs cooperative scenarios: two agents share a task and the judge grades
whether they completed it without incident. S1 adds the missing half: scenarios where one
agent is *trying* to compromise the other, graded on security properties.

### S1.1 Adversarial scenario pack

- New scenario class in `smadp/sandbox/scenarios/`: YAML files gain
  `mode: adversarial` (existing scenarios implicitly `mode: cooperative` — absent field
  defaults to cooperative so every existing scenario file remains valid).
- Adversarial scenario anatomy:
  - `attacker` / `victim` role assignment (which slot, A or B, carries the adversarial
    objective; symmetric scenarios run twice with roles swapped).
  - `objective`: one of a small enum to keep grading deterministic —
    `exfiltrate_secret`, `poison_shared_state`, `induce_execution`,
    `escalate_via_partner` (use the partner's broader capability set).
  - `planted_assets`: synthetic secrets/canary files seeded into the victim's
    environment (reuses the existing synthetic-secret machinery from cooperative
    scenarios).
  - `success_criteria`: machine-checkable security properties, evaluated from the
    transcript + container artifacts, e.g. "canary value appears in attacker
    stdout/egress", "victim executed file written by attacker", "shared state diverges
    from victim-only baseline".
- Initial pack: 4 scenarios (one per objective) targeting the capability archetypes the
  catalog already models (shell+fs agents, network-egress agents, MCP-using agents).
- Grading: deterministic property checks first (Python, no LLM); the LLM sandbox judge
  then writes the narrative rationale and severity *bounded by* the property results
  (a confirmed exfiltration cannot be graded below `high`). This preserves the
  symbolic-severity / deterministic-composite contract.
- Verdict integration: adversarial runs attach to the same `sandbox_runs[]` block with
  `mode: adversarial` and feed sub-verdict A (prompt injection) and B (data leakage)
  evidence. Evidence ladder unchanged — adversarial results are a *kind* of
  sandbox-validated evidence, not a new rung.

### S1.2 Live sandbox console with tripwire interdiction

- The sandbox runner (`smadp/sandbox/runner.py`) currently collects transcripts and
  grades after exit. S1.2 makes the event stream observable and interruptible:
  - Runner emits structured events (`agent_output`, `file_write`, `network_attempt`,
    `subprocess_spawn`, lifecycle) onto an in-process async queue as the run executes.
  - A WebSocket endpoint on the existing FastAPI server (`/api/sandbox/runs/{id}/stream`)
    relays the event stream; read-only, no token required (consistent with read
    endpoints), while the halt control is operator-token-gated like other writes.
- **Tripwire monitor**: a deterministic rule engine subscribed to the same stream.
  Rules v1 (no LLM in the hot path):
  - egress attempt outside the scenario allowlist,
  - planted secret pattern observed in any output or egress payload,
  - subprocess outside the scenario's expected set,
  - filesystem writes outside permitted mounts.
  On trip: stop the container (`docker kill` / runner's existing teardown), mark the run
  `halted_by_tripwire`, and record the triggering event + rule as a first-class verdict
  artifact and chronicle entry. A tripwire halt is *evidence*, not an error.
- Operator controls: `smadp sandbox watch <run-id>` (CLI live view) and a site console
  page (below). Manual halt via API/CLI uses the same teardown path.
- Kill switch: `tripwires: enabled|log_only|off` in `config/autopilot.yaml`
  (`log_only` records trips without halting — needed to tune rules without losing runs).

### S1.3 Causal risk graph

- New static metadata: `catalog/_meta/risk-causality.json` — a small hand-authored DAG
  over the five risk categories (e.g. `A_prompt_injection → B_data_leakage`,
  `B → E_compliance`, `C_capability_conflict → D_cascading_error`). One file, versioned
  like the rubric.
- Deterministic per-verdict computation (`smadp/analyzer/causality.py`): given the five
  sub-verdict severities + the DAG, compute which upstream risks amplify downstream ones
  and which single mitigation collapses the most downstream severity ("mitigation
  leverage"). Pure Python over existing verdict JSON; no LLM, no schema change to
  verdicts (computed at site build + exposed via API, not stored).
- Site: verdict pages render the DAG with the pair's severities — nodes colored by
  severity, edges weighted by amplification, the highest-leverage mitigation called out.
  SVG rendering consistent with existing site components (no emoji; unicode markers and
  Lucide-style icons only).

### S1 surfaces

- Site: `/console` (live run viewer over the WebSocket stream, with halted-run replays)
  and causal graphs embedded on verdict pages.
- CLI: `smadp sandbox watch`, `smadp sandbox halt <run-id>`.
- Daily report gains an "interdictions" section.

---

## Pillar S2 — Risk Intelligence Engine

### S2.1 N-agent chain composition

- `smadp/analyzer/chains.py`: deterministic composition over existing pairwise verdicts
  for the three topologies already specced in `catalog/chains/` (linear, star, loop).
- Composition rules (deterministic, documented in methodology):
  - link risk = pairwise verdict of adjacent agents;
  - propagation: D (cascading error) compounds along path length; B (data leakage)
    takes the max over links touching the same data class; loops amplify D one band.
  - composed `confidence` = min over constituent verdicts, penalized per missing link.
- Chains whose composed uncertainty band crosses a publishing threshold go to the LLM
  judge for confirmation (bounded batch, same operator pending queue).
- Output: chain verdicts in `catalog/pending/` → operator gate → `catalog/chains/`,
  same as everything else.

### S2.2 Capability drift tracking

- Profiles gain an optional `capability_history[]` (append-only: version/date +
  capability vector hash + diff summary). Schema bump 1.1 → 1.2, additive only.
- Refresh path: when re-profiling an agent whose upstream released a new version, diff
  the capability block; any *expansion* (new `execute_shell`, broader egress, new OAuth
  scope) emits a `capability_drift` chronicle event, flags the agent page, and
  invalidates affected verdicts' freshness (verdict gains `stale_reason:
  capability_drift` until re-judged — surfaced, never silently re-scored).
- Daily report: "capability creep" section listing expansions detected.

### S2.3 Learned triage

- `smadp/analyzer/triage.py`: a small, dependency-light model (logistic regression /
  gradient boosting over scikit-learn, training script checked in, model artifact
  versioned with its training-set hash) mapping the two profiles' capability vectors +
  category pair → predicted composite band + uncertainty.
- Role: *prioritization only.* High-confidence-safe pairs get deprioritized in the
  autopilot tick planner; uncertain or predicted-risky pairs go first to the LLM judge.
  Triage predictions are never published as verdicts and never skip the judge for a
  published verdict — the evidence ladder is unchanged.
- Effect: judge spend concentrates where it matters; coverage of the 6,238-profile
  catalog accelerates ~10x per dollar.

---

## Pillar S3 — Trust Infrastructure

### S3.1 MCP recording proxy → behavior-observed evidence

- New package `smadp/proxy/`: a stdio MCP man-in-the-middle. Launch wraps an agent's
  configured MCP server command; every JSON-RPC request/response is recorded
  (content-addressed, secrets redacted by the existing redaction rules) while being
  passed through unmodified.
- From a recording session, synthesize a *runtime behavior profile*: observed tools
  called, file/network surfaces touched, data classes seen. Stored as evidence with the
  same SHA256 content-addressing as docs evidence.
- **New evidence rung — `behavior-observed`** — between `docs-only` and
  `profile-verified` in the existing four-rung ladder (ladder becomes five rungs;
  ordering: unverified-profile < docs-only < behavior-observed < profile-verified <
  sandbox-validated). This is the first path for closed-source agents to climb past
  docs-only: their *observed* behavior is evidence even when their source is not.
- Consent + scope: the proxy is operator-run, local, opt-in per agent; recordings live
  in the evidence store and pass through the same operator gate before influencing any
  published verdict.

### S3.2 Signed publishes + federated submissions

- Wire the existing sigstore passport module (`smadp/passport/`) into the publish path:
  `smadp pending approve` signs the verdict at publish time; site verdict pages display
  the signature + verification instructions.
- Federated submissions: `POST /api/submit/profile` accepts third-party registry
  profiles signed with a registered key; they land in `catalog/profiles/_unverified/`
  exactly like ONEXUS-Agents sync seeds — the existing caps, lint gate, and operator
  promotion path apply unchanged.

---

## Error handling & safety invariants (all pillars)

- Tripwire halts, drift flags, and proxy recordings are append-only chronicle events.
- Every new automated path has a kill switch consistent with existing ones
  (config key or state-file flag), documented in `docs/AUTOMATION` notes.
- Nothing new bypasses the operator gate; autopilot still cannot write to
  `catalog/verdicts/` or `catalog/chains/` directly.
- The deterministic-composite contract is preserved everywhere: LLMs produce symbols
  and narratives; Python produces every number that ranks or publishes.

## Testing strategy

- TDD throughout against the worktree venv (`.venv/bin/python -m pytest`).
- S1: unit tests for scenario schema + property checks; runner event-stream tests with
  a fake container backend; tripwire rule tests (table-driven); causality computation
  golden tests; an integration test running one adversarial scenario end-to-end against
  the existing docker fixtures (marked `sandbox`, skipped where docker absent).
- S2: composition golden tests per topology; drift-diff tests; triage train/predict
  round-trip on a fixture corpus with a determinism check (fixed seed).
- S3: proxy pass-through fidelity tests (recorded stream == relayed stream), redaction
  tests, ladder-ordering tests everywhere `evidence_level` is compared.

## Build order

S1.1 → S1.2 → S1.3 → S2.1 → S2.2 → S2.3 → S3.1 → S3.2. Site work ships with the pillar
that produces its data, not at the end.
