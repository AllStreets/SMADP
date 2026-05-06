# Architecture

This document describes the SMADP system architecture: the layers, what each does, and the data flow for a typical request. For the production methodology behind the verdicts the architecture serves, see [`methodology.md`](methodology.md). For the canonical design, see the spec at [`docs/superpowers/specs/2026-05-02-smadp-design.md`](superpowers/specs/2026-05-02-smadp-design.md).

---

## 1. System diagram

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

---

## 2. Layers

**Sources.** The catalog is built from external sources: GitHub repositories (READMEs, source code, configuration), HuggingFace model and space cards, vendor documentation pages, vendor terms of service, and user submissions. Sources are not hosted by SMADP; the Profiler fetches from them on demand and on a refresh schedule (spec §14). Every fetched chunk is content-addressed and stored under `catalog/_evidence/`.

**Profiler.** Code at `smadp/profiler/`. Takes a slug or URL and produces a Safety Profile by chunking source content, hashing each chunk into an evidence record, calling `gpt-5.4-mini` to extract a structured profile JSON with citations, then validating the schema and re-checking each citation's quote at its source URL. Output is `profiles/<slug>.json` (or `profiles/_unverified/<slug>.json` for user submissions). Full pipeline in [`methodology.md`](methodology.md) §2.

**Pairwise Analyzer.** Code at `smadp/analyzer/`. Takes two profile slugs, assembles a single context bundle containing both profiles plus all referenced evidence, loads the active rubric from `catalog/_meta/rubric/`, calls the LLM-judge to produce per-risk sub-verdicts with citations, validates the result, deterministically computes the composite score, deterministically computes framework mappings, and writes `verdicts/<a>__<b>.json`. The rubric, scoring formula, and framework-mapping logic are all out-of-LLM so the verdict's quantitative parts are reproducible and auditable. Full pipeline in [`methodology.md`](methodology.md) §3.

**Sandbox Validator.** Code at `smadp/sandbox/`. Open-source pairs only in v1. A queue worker pulls a pending job, builds an isolated container (rootless Podman + gVisor `runsc`, `--network none` by default, ephemeral tmpfs, `--cap-drop ALL`, restrictive seccomp, cgroups v2 caps, 5-minute wall-clock kill), runs both agents through scripted scenarios, captures the transcript, and updates the verdict's `sandbox_runs[]` and `evidence_level`. Full isolation model in [`sandbox-isolation.md`](sandbox-isolation.md).

**Catalog.** Filesystem-backed, git-versioned, schema-validated. The git history is the audit log; the chronicle JSONL files in `_chronicle/` are a structured second source of truth for events. Code at `smadp/catalog/` covers git operations, an FTS index for search, and the chronicle event logger. The catalog is the product; everything else is a surface.

**Surfaces.** The dashboard (`site/` — Astro 4 + Tailwind v4, static), the REST API (`smadp/api/` — FastAPI), and the CLI (`smadp/cli.py`) all read from and write to the catalog. The dashboard is fully static and rebuilds on catalog changes; the API serves the same JSON the dashboard renders, plus search, evaluation, and submission endpoints; the CLI is the operator interface and powers the contributor workflow.

---

## 3. Data flow: "user submits a list of agents to evaluate"

The most useful end-to-end flow. A reviewer wants verdicts for a set of agents they are considering composing.

1. **Request.** The reviewer hits `POST /api/evaluate` with a body of `{"agents": ["claude-code", "cursor", "gemini-cli"]}` (or runs `smadp evaluate claude-code cursor gemini-cli`).
2. **Slug resolution.** The API resolves each input to a profile slug. Slugs that exist in `catalog/profiles/` proceed. Inputs that look like URLs are routed through the Profiler to produce an unverified profile under `catalog/profiles/_unverified/`. Slugs the Profiler cannot resolve are returned in the response's `missing` array.
3. **Pair enumeration.** The API enumerates all unique pairs from the resolved slug set, alphabetizing each pair to its canonical filename (`claude-code__cursor.json`, etc.).
4. **Cache check.** For each pair, the Analyzer hashes the inputs (profile A, profile B, evidence bundle, rubric URL) and checks for an existing verdict whose `reproducibility` hashes match. Cache hits are returned directly and recorded in the chronicle as `verdict.cache_hit`.
5. **Generation.** Cache misses run through the full Pairwise Analyzer pipeline: bundle assembly → rubric load → LLM-judge call → schema and citation validation → composite computation → framework mapping → write.
6. **Sandbox queueing (open-source pairs only).** If both agents in a pair have MCP adapters under `adapters/<slug>/mcp.json`, the validator enqueues a sandbox run. The verdict is returned at `evidence_level: docs-only` immediately; the sandbox run completes asynchronously and the verdict is updated to `sandbox-validated` later, with a chronicle event marking the change.
7. **Response.** The API returns the verdict bundle (one entry per pair, plus `missing` and `regenerated` arrays).
8. **Audit trail.** Every cache hit, generation, sandbox enqueue, and sandbox completion writes an event to `catalog/_chronicle/YYYY-MM-DD.jsonl` and produces a git commit on the catalog. The reviewer can audit the entire flow after the fact via `git log` or the `/api/chronicle` endpoint.

---

## 4. Repo layout summary

The full layout is in spec §13 and in the README. The main directories:

| Path | Contents |
|------|----------|
| `smadp/` | Python package: Profiler, Analyzer, Sandbox, CLI, API, schemas, LLM client, utilities. |
| `catalog/` | The catalog itself: `profiles/`, `verdicts/`, `_evidence/`, `_meta/`, `_chronicle/`. Git-versioned. |
| `adapters/` | MCP adapters per open-source agent slug. Required for sandbox runs. |
| `site/` | Astro 4 + Tailwind v4 static dashboard. Rebuilds on catalog changes. |
| `tests/` | Unit, integration, and golden-file tests. CI runs them on every PR. |
| `docs/` | This documentation set. The design spec lives under `docs/superpowers/specs/`. |
| `.github/` | CI workflow (`workflows/ci.yml`) and PR templates (`PULL_REQUEST_TEMPLATE/`). |

The codebase is intentionally small. The product is the catalog; the code is the minimal surface needed to produce, validate, and serve it.

---

Last updated: 2026-05-02
