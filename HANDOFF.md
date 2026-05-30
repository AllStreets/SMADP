# SMADP — Project Handoff

**Date:** 2026-05-30
**Author of handoff:** Connor + Claude (working session)
**Audience:** The next operator (likely Connor on a new machine, or a fresh Claude Code session)
**Last commit on `main` at time of writing:** `b9268f1`

---

## TL;DR

SMADP (Safe Multi-Agent Deployment Platform) is a system that **profiles AI coding/operations agents, runs them in pairs and short chains inside an isolated Docker sandbox, and publishes safety verdicts** to a public static report site.

As of 2026-05-30:
- The **autonomous-growth autopilot is fully wired** (v2 spec, 12 commits landed `50baf0e..b9268f1`).
- The **proof-of-life smoke ran end-to-end** through the queue and the worker — the verdict landed in `catalog/pending/aider__autogen__continue-dev.json`.
- But the verdict is a `fail`, because **Docker Desktop was off** AND **only 1 of 4 adapter images (aider) is actually pinned**; autogen, continue-dev, and the node-base image are all `sha256:000…000` stubs.

**Next concrete step:** pin real digests for autogen + continue-dev, start Docker, re-run smoke. Then expand the priority list.

---

## What SMADP is (and isn't)

### Mission

There are hundreds of AI agents shipping to production with vague safety properties. SMADP makes a **public, evidence-backed catalog** of how individual agents and *combinations of agents* behave when given real tasks in a hardened sandbox.

The unit of analysis is the **verdict**: a JSON document with a composite safety score, sub-scores across 5 risk categories (prompt injection, data leakage, capability conflict, cascading error, compliance), framework mappings (NIST AI RMF, ISO 42001, OWASP Top 10 for LLM Apps), and — when sandbox-validated — links to the actual run transcripts.

### Two halves of the system

| Half | What it does | Where it lives |
|------|---|---|
| **Backend (Python)** | Schedules runs, runs adapters in Docker, grades transcripts, writes verdicts | `smadp/`, `adapters/`, `scripts/`, CLI: `smadp …` |
| **Frontend (Astro static site)** | Renders verdicts as Primer / Prospectus / Dossier / Reference layouts + Pending review queue | `report/` (pnpm + Astro + Playwright tests) |

The site is the public face. The backend is the autonomous-growth engine.

### The autonomous-growth loop (just shipped)

```
catalog/priority.yaml ─┐
                       ├─► smadp autopilot tick ─► queue (SQLite)
scenarios + adapters ──┘
                                                       │
                                                       ▼
                       ┌──────  smadp sandbox work  ──────┐
                       │ runs containers, grades, writes  │
                       └────────────┬─────────────────────┘
                                    │
                  first time?       │       seen before?
                       │            ▼            │
                       │     catalog/pending/    │
                       │            │            │
                       │  smadp autopilot approve│
                       │            ▼            ▼
                       └──► catalog/verdicts/  (in place)
                                    │
                                    ▼
                           report/.rebuild-requested
                                    │
                                    ▼
                         launchd rebuilds Astro site
```

---

## Where we are (2026-05-30)

### What's shipped and working

1. **3-layout static report site** at `report/` — Primer (~10 pages), Prospectus (~14 pages), Dossier (~16 pages), plus `/search`, `/references`, `/briefs`, `/pending`. Tested with Playwright. Both HTML and PDF outputs build.
2. **Sandbox runner + queue** — SQLite-backed queue (`state/queue.db`), per-run isolated Docker containers (rootless, network-restricted, read-only FS), JSONL transcripts at `~/Library/Caches/smadp/sandbox-runs/<run_id>/`.
3. **Verdict-promotion module** that accumulates evidence across reruns (first-time → pending, subsequent → in-place verdict mutation).
4. **Autopilot autonomous-growth layer** (the v2 deliverable):
   - `smadp autopilot tick` — picks the next scenario × agent-tuple from `catalog/priority.yaml` + coverage gap, enqueues idempotently, enforces budget (runs/day, dollars/day).
   - `smadp autopilot approve <key>` — moves `catalog/pending/<key>.json` → `catalog/verdicts/<key>.json` and touches `report/.rebuild-requested`.
   - 2 launchd plists at `scripts/launchd/com.smadp.autopilot.{loop,watch}.plist` — `loop` ticks every 5 min, `watch` re-ticks on `scenarios/` or `adapters/` file change.
   - Bash wrapper `scripts/autopilot-loop.sh`.
5. **N-ary scenarios** (length 2–4): existing `coding_browser`, `notes_email`, `calendar_email`, `spreadsheet_powerpoint` (pairs) + new `code_review_chain` (planner / executor / reviewer triple).
6. **105 verdicts** in `catalog/verdicts/` (curated, mostly `docs-only` and `profile-verified` evidence levels) + **31 agent profiles** in `catalog/profiles/`. One pending verdict in `catalog/pending/` (the failed smoke).
7. **MIT-licensed**, license verified live on GitHub.

### What's stubbed / broken / missing

| # | Item | Status | Impact |
|---|---|---|---|
| 1 | `autogen`, `continue-dev`, `node-base` image digests | Stub `sha256:000…000` in `smadp/sandbox/approved_images.json` | Any scenario touching these adapters fails at container start. **Blocks real sandbox verdicts**. |
| 2 | `--max-runs` flag in `scripts/autopilot-loop.sh` and README | Wrong: the actual flag is `--max` | launchd loop fails silently the moment the script runs |
| 3 | `state/budget.json` cost estimator | Stub (returns 0.0) | `dollars_per_day` cap is currently a no-op. `runs_per_day` cap works. |
| 4 | `pip` inside `.venv` | Broken (missing pip module) | Can't `pip install -e .` to repair the venv; have to rebuild it (see "New machine setup") |
| 5 | Python 3.14 `.pth` file processing | Silently does not add the editable-install path | The repo had to be patched into `.venv/bin/smadp` directly (see "Known gotchas") |
| 6 | Promotion log says `pair=(...)` even for 3-agent chains | Cosmetic — only the log line is wrong; the verdict file uses the full chain key | Low priority but should be cleaned up |

---

## Repo tour

```
SMADP/
├── HANDOFF.md                      ◄── this file
├── README.md                       Main developer guide
├── LICENSE                         MIT
├── pyproject.toml                  Python deps + entrypoints
├── adapters/<slug>/mcp.json        Per-agent adapter spec (entrypoint, model, role hints)
├── catalog/
│   ├── verdicts/                   105 published verdicts (filename = "<slug_a>__<slug_b>[__<slug_c>].json")
│   ├── pending/                    First-time verdicts awaiting human approval
│   ├── profiles/                   31 agent profile YAMLs
│   ├── chains/                     (reserved for chain-specific assets)
│   └── priority.yaml               YAML list: { scenario: <name>, agents: [<slug>, ...] }
├── smadp/                          Python package
│   ├── cli.py                      Click entrypoint
│   ├── autopilot/
│   │   ├── tick.py                 Planner
│   │   ├── approve.py              Pending → verdicts mover
│   │   ├── budget.py               runs/day + dollars/day governor
│   │   └── priority.py             Priority-file loader
│   ├── sandbox/
│   │   ├── runner.py               Docker-driver per run
│   │   ├── worker.py               Queue drainer (`smadp sandbox work`)
│   │   ├── queue/                  SQLite queue
│   │   ├── scenarios/              YAML scenario definitions
│   │   ├── binder.py               Scenario × agents capability binder
│   │   ├── promote.py              Verdict writer (handles pending routing)
│   │   └── approved_images.json    Pinned image digests ◄── currently 3-of-4 STUBBED
│   └── … (analyzer, frameworks, llm, etc.)
├── scripts/
│   ├── autopilot-loop.sh           Cron-style wrapper
│   └── launchd/
│       ├── com.smadp.autopilot.loop.plist     5-min interval
│       └── com.smadp.autopilot.watch.plist    fs-change triggered
├── report/                         Astro 4 static site (pnpm)
│   ├── src/lib/catalog.ts          Loads verdicts + profiles from /catalog
│   ├── src/pages/                  index, primer, prospectus, dossier, search, references, briefs, pending
│   ├── tests/routes.spec.ts        Playwright route smoke
│   └── .rebuild-requested          Sentinel file — touch to trigger launchd rebuild
├── state/                          Runtime state (gitignored except .gitkeep)
│   ├── queue.db                    SQLite queue
│   ├── budget.json                 Today's spend
│   └── coverage.json               Already-attempted tuples
├── tests/                          Python test suite (pytest)
├── docs/superpowers/
│   ├── specs/                      6 design specs, dated
│   └── plans/                      Implementation plans, dated
└── .venv/                          Local Python venv (gitignored)
```

---

## New machine setup

### TL;DR — the 4-step migration

On the **old** machine:
```bash
./scripts/export-machine-state.sh
# → writes ~/Desktop/smadp-machine-state.tar.gz (~15 KB)
```

AirDrop / iCloud / USB the `.tar.gz` to the new MacBook, then:

```bash
# On the new MacBook:
git clone https://github.com/AllStreets/SMADP.git
cd SMADP
./scripts/import-machine-state.sh ~/Downloads/smadp-machine-state.tar.gz
./scripts/bootstrap-newmachine.sh
# Start Docker Desktop manually (GUI installer, needs admin).
```

That's it. The bootstrap script installs Homebrew deps (Python 3.12, Node, pnpm), creates the venv, runs `pip install -e ".[dev]"`, installs frontend deps + Playwright browsers, creates `~/.smadp/keys.env` template, and runs `pytest -q` as a smoke check.

### Prerequisites

| Tool | Version | Install on macOS |
|---|---|---|
| Python | **3.12** (NOT 3.13/3.14 — see gotchas) | `brew install python@3.12` |
| Node.js | 20+ | `brew install node` |
| pnpm | 9+ | `corepack enable && corepack prepare pnpm@latest --activate` |
| Docker Desktop | 4.x | https://www.docker.com/products/docker-desktop |
| Git | any | preinstalled |

> **About Python 3.14:** the homebrew Python 3.14 distribution at `/opt/homebrew/Cellar/python@3.14/3.14.3` silently fails to process `.pth` files in venv `site-packages` at interpreter startup. That breaks every `pip install -e .` editable install. Use 3.12 on the new machine to avoid the workaround we currently ship (a hand-patched `.venv/bin/smadp`).

### Clone + bootstrap

```bash
git clone https://github.com/AllStreets/SMADP.git
cd SMADP

# Backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Frontend
cd report && pnpm install && pnpm exec playwright install --with-deps && cd ..

# Smoke-test the install
smadp --help
pytest -q
```

### API keys

The sandbox runner reads API keys from `~/.smadp/keys.env`. Currently only `OPENAI_API_KEY` is required (we swapped from Anthropic to OpenAI at commit cluster around 2026-05-?):

```bash
mkdir -p ~/.smadp
cat > ~/.smadp/keys.env <<'EOF'
OPENAI_API_KEY=sk-...
EOF
chmod 600 ~/.smadp/keys.env
```

### Install autopilot launchd (optional, only when ready to grow autonomously)

```bash
mkdir -p state report
# Edit the plists to replace the repo path with the new machine's path:
sed -i '' "s|REPLACE_WITH_REPO_ROOT|$PWD|g" scripts/launchd/*.plist
cp scripts/launchd/com.smadp.autopilot.*.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.smadp.autopilot.loop.plist
launchctl load ~/Library/LaunchAgents/com.smadp.autopilot.watch.plist
```

(Don't load these until **all 4 adapter image digests are real**, otherwise the autopilot will burn API budget on runs that immediately fail at container start.)

---

## Known gotchas

### 1. Python 3.14 + editable install + paths with spaces = silent breakage

Symptom: `ModuleNotFoundError: No module named 'smadp.cli'` from `.venv/bin/smadp`, despite the package being installed.

Cause: Python 3.14's `site` module's `addpackage()` does not process `.pth` files written by `pip install -e .` for this venv. We confirmed `_editable_impl_smadp.pth` exists with the correct path but is silently ignored at startup. Other `.pth` files (`a1_coverage.pth`) are also ignored. Same Python invoked manually with `site.main()` processes them correctly.

**On this machine** (current laptop), we worked around it by:
1. Deleting stale `.venv/lib/python3.14/site-packages/smadp/` namespace dir
2. Patching `.venv/bin/smadp` to insert the repo onto `sys.path` before importing

**On the new machine**, use Python 3.12 and this whole class of issue goes away.

### 2. The `--max-runs` flag is wrong

`scripts/autopilot-loop.sh`, the README install block, and the smoke instructions all reference `--max-runs=N` but the real flag on `smadp sandbox work` is `--max N`. Fix in one place:

```bash
# scripts/autopilot-loop.sh line: smadp sandbox work --once --max-runs=3
# should be:                      smadp sandbox work --max 3
```

Until this is fixed, launchd `loop` will run the first `tick` successfully and then crash on `work`.

### 3. Only `aider` has a real image digest

In `smadp/sandbox/approved_images.json`:

```json
{
  "aider":        "paulgauthier/aider@sha256:0d54037f...",  ✓ real
  "autogen":      "ghcr.io/microsoft/autogen@sha256:00000…",  ✗ stub
  "continue-dev": "ghcr.io/continuedev/continue@sha256:00000…",  ✗ stub
  "node-base":    "docker.io/library/node:20-bookworm-slim@sha256:00000…"  ✗ stub
}
```

`smadp sandbox pin-images` is the CLI that's supposed to fill these in by pulling each image and recording the actual content digest. Two of these images may not exist at the URLs we're trying — autogen Microsoft's container layout is unusual, and continuedev may publish under a different name. Plan: investigate each registry, find the canonical image, then re-pin.

### 4. The `(base)` conda env is layered on top of `(.venv)` in the shell

When both are active, `which smadp` may resolve to the conda copy on some commands. If you see weird import errors, `conda deactivate` first, or invoke `.venv/bin/smadp` by absolute path.

---

## Immediate next step — finish the proof-of-life smoke

Status as of session end:
- ✓ `smadp autopilot tick` → 1 run enqueued (code_review_chain, aider + autogen + continue-dev)
- ✗ `smadp sandbox work --once` → Docker daemon was off + stub digests → both containers exited 125 → graded as `fail` → published to `catalog/pending/aider__autogen__continue-dev.json`

To actually finish:

```bash
# 1. Start Docker Desktop. Wait for whale icon.

# 2. Pin real digests for the 3 stub adapters
smadp sandbox pin-images --adapter autogen
smadp sandbox pin-images --adapter continue-dev
smadp sandbox pin-images --adapter node-base
# (If pin-images can't find the image, investigate the registry URL and update
#  smadp/sandbox/approved_images.json manually.)

# 3. Wipe the failed pending verdict so the next run isn't accumulated against a bad one
rm catalog/pending/aider__autogen__continue-dev.json

# 4. Re-tick and re-run
smadp autopilot tick
smadp sandbox work --once

# 5. Inspect the pending verdict
cat catalog/pending/aider__autogen__continue-dev.json | jq .

# 6. If it looks right, approve
smadp autopilot approve aider__autogen__continue-dev

# 7. Verify on the report site
cd report && pnpm dev
# open http://localhost:4321/pending  → should now be empty
# open http://localhost:4321/references  → should show the new chain verdict
```

---

## Roadmap

### Near-term (1–2 weeks)

1. **Real image digests for all 4 adapters** (#1 above) — unblocks every other run
2. **Fix `--max-runs` → `--max`** in `autopilot-loop.sh`, README, and any other script
3. **Pin a 5th and 6th adapter** — `cursor`, `plandex`, `swe-agent`, or `claude-code` — to expand the sandbox-runnable matrix beyond the aider triple
4. **First real sandbox-validated verdict** in `catalog/verdicts/` (not pending, not docs-only) — milestone for the report site's "live growth" narrative
5. **Implement the dollar-cost estimator** so `dollars_per_day` cap is real, not a no-op

### Mid-term (1–2 months)

6. **Seed 10–20 pair verdicts as sandbox runs** (task #187, still open)
7. **Scale sandbox-smoke from 1 run to dozens of pairs** (task #188, still open) — this is the v2 success metric: the autopilot grows the catalog without per-step direction
8. **Hand-author 2–3 more chain scenarios** beyond `code_review_chain` (planner/executor/reviewer is the only chain template right now)
9. **Landing-page hub** — main entry point that links into Primer/Prospectus/Dossier and the upcoming weekly index (slice #1 of the product vision)

### Long-term (3+ months)

10. **Weekly market-index report** — auto-generated, cross-agent snapshot, refreshed weekly (slice #2)
11. **User-submittable agent runs** — user enters an agent name → catalog hit shows existing verdicts, miss-but-known triggers a live sandbox run with "agent at work" animation (slice #4)
12. **Semantic catalog search** (slice #5)
13. **Full audit/export pipeline** — every claim on the site links back to its source verdict + transcript, exportable as one bundle (slice #6)

---

## The ultimate vision

> A **public, evidence-backed observatory of cross-agent safety** — every notable AI coding/operations agent profiled, every interesting pair and chain combination tested in a hardened sandbox, every verdict citing the exact transcript line that justifies its score. A user types an agent name, and gets a real answer about how it behaves when wired up with another agent. A regulator pulls one URL and gets the framework mappings (NIST AI RMF, ISO 42001, OWASP-LLM) for a deployment they're auditing.

The static report site at `report/` is **slice 1** of this. The autopilot just landed is the engine that grows the data. Everything else above is downstream of those two things working.

---

## Where to read next

| If you want to understand… | Read |
|---|---|
| The autopilot architecture | `docs/superpowers/specs/2026-05-18-smadp-autonomous-growth-design.md` |
| The original sandbox pipeline | `docs/superpowers/specs/2026-05-04-sandbox-validation-pipeline-design.md` |
| The report site structure | `docs/superpowers/specs/2026-05-14-smadp-report-site-design.md` |
| The very first SMADP design | `docs/superpowers/specs/2026-05-02-smadp-design.md` |
| How a verdict file is shaped | `report/src/lib/types.ts` |
| Day-to-day developer workflow | `README.md` |

## Contact

Repo: https://github.com/AllStreets/SMADP
Owner: Connor Evans (connorevans29@gmail.com)
