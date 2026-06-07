# Design: MCP Adapter Scaffolder

**Date:** 2026-06-07
**Status:** Draft — supersedes the deferred "Out of scope" line from `2026-06-06-profile-enrichment-pivot-design.md`
**Spec ID:** `2026-06-07-adapter-scaffolder-design`

## Summary

A code generator that turns an enriched SMADP profile + its GitHub source into a runnable MCP adapter at `adapters/<slug>/{Dockerfile, mcp.json, entrypoint.sh}`. Once an adapter exists, the existing sandbox runner can execute the agent against scenarios and produce `sandbox-validated` verdicts — the true differentiator SMADP was designed for.

This is the path from "220 docs-only profiles" to "thousands of sandbox-validated verdicts." The pivot's profile enrichment gave us *what an agent does*; the scaffolder gives us *the artifact that lets us actually run it.*

## Goals

1. **Cover the runnable subset** — any ONEXUS profile with `source.github` set + at least one of (Python, Node, Go, Rust) detected language → scaffoldable.
2. **One-command bootstrap** — `smadp adapters scaffold --from-profile <slug>` produces the three files atomically. No half-formed adapter dirs.
3. **Sandbox-runnable by construction** — every scaffolded adapter passes `docker build .` AND the existing `smadp sandbox runnability-check` smoke before commit.
4. **Honest capability declaration** — `mcp.json` capabilities are derived from the enriched profile, NOT inferred again. Whatever the LLM declared is what the sandbox enforces.
5. **Reversible** — a bad scaffold is just an extra dir on disk; no daemons started, no commits made until verified.

## Non-goals

- **Auto-fixing broken upstream agents.** If `pip install -e .` fails on the agent's repo, the scaffolder records the failure and stops; no patching the agent.
- **Runtime orchestration changes.** Existing `smadp sandbox runner.py`, `queue.py`, `worker.py` stay unchanged.
- **Cross-agent adapter sharing.** Each slug gets its own dir even when agents share a base image — duplication is cheap, lookups are clearer.
- **Closed-source agent adapters.** Cursor/GitHub-Copilot/Claude-Code etc. can't be scaffolded automatically — they need bespoke API-shim adapters (separate spec, deferred).
- **GUI/browser agents** in the first pass. ComfyUI, browser-use, etc. need display servers — punt to a v2.

## Architecture

```
┌──────────────────┐  ┌──────────────────┐  ┌────────────────────┐  ┌───────────────────┐
│ Profile Loader   │→ │ Language Detector│→ │ Dockerfile/MCP     │→ │ Verification      │
│ (enriched JSON)  │  │ (README + repo)  │  │ Template Renderer  │  │ (docker build +   │
│                  │  │                  │  │                    │  │  mcp.json schema) │
└──────────────────┘  └──────────────────┘  └────────────────────┘  └───────────────────┘
                              │
                              ▼
                     ┌────────────────────┐
                     │ Capability Policy  │
                     │ (caps → cgroups +  │
                     │  network + mounts) │
                     └────────────────────┘
```

### File layout (new pieces)

```
smadp/autopilot/
  scaffolders/
    __init__.py
    base.py                 # Scaffolder ABC
    language_detector.py    # GithubMetadataLanguageDetector
    mcp_adapter.py          # MCPAdapterScaffolder
    capability_policy.py    # capabilities dict → docker run flags
    templates/
      python.Dockerfile
      node.Dockerfile
      go.Dockerfile
      rust.Dockerfile
      entrypoint.sh
      mcp.json.tmpl
adapters/                   # existing — output lands here
  <slug>/
    Dockerfile              # NEW per scaffold
    mcp.json                # NEW per scaffold
    entrypoint.sh           # NEW per scaffold
    .scaffolded.json        # provenance: spec_id, profile_sha, template_version, scaffolded_at
```

### Component interfaces

```python
class LanguageDetector(ABC):
    @abstractmethod
    def detect(self, *, github_source: str) -> Language: ...
        # Returns Language enum: PYTHON | NODE | GO | RUST | UNSUPPORTED.

class Scaffolder(ABC):
    name: str
    @abstractmethod
    def scaffold(self, profile: dict, *, target_dir: Path) -> ScaffoldResult: ...

@dataclass(frozen=True)
class ScaffoldResult:
    target_dir: Path
    files_written: list[Path]
    language: Language
    sha256: str       # over the concatenation of all written files
    success: bool
    reason: str       # "ok" | "no_github_source" | "unsupported_language" | …
```

### Data flow

```
$ smadp adapters scaffold --from-profile gpt-researcher

  ① Load catalog/profiles/gpt-researcher.json. Require:
     - evidence_level >= "docs-only"
     - onexus.source_github present (or repo_url derivable to owner/repo)
  ② LanguageDetector fetches the repo's GitHub API metadata (cached) — primary
     language + presence of pyproject.toml / package.json / go.mod / Cargo.toml.
  ③ Pick a Dockerfile template per language; render with:
     - {{slug}}, {{repo_url}}, {{commit_pin}} (HEAD SHA at scaffold time)
     - install command derived from language (pip install -e . / npm install / etc.)
  ④ Render entrypoint.sh from the template — accepts SMADP_AGENT_TASK env var,
     invokes the agent CLI, streams stdout/stderr to the sandbox transcript.
  ⑤ Render mcp.json from the enriched profile's capabilities + io_surfaces +
     data_classes_touched + sandboxing. The schema matches existing hand-crafted
     adapters/aider/mcp.json by construction.
  ⑥ Write all 4 files atomically (tempdir + os.rename). Write .scaffolded.json
     with provenance.
  ⑦ Run verification:
     - Docker build (build-arg DOCKER_BUILDKIT=1, no-cache off so iteration is
       fast; cache key is the SHA of the entire adapter dir).
     - mcp.json schema validation against smadp/schemas/adapter_mcp.json.
     - "Runnability check": `docker run --rm <image> --version` (or smoke command
       from the template). Records exit code + stdout into the .scaffolded.json.
  ⑧ Print summary: success + path, or failure + reason.
```

### Per-language Dockerfile templates

Each template is a Jinja2 file at `smadp/autopilot/scaffolders/templates/<lang>.Dockerfile`. Minimum surface:

```dockerfile
# python.Dockerfile (the most common path)
FROM python:3.11-slim

ARG REPO_URL
ARG COMMIT_PIN

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN git clone "$REPO_URL" . && git checkout "$COMMIT_PIN"

# Install: prefer pyproject.toml, fall back to requirements.txt, fall back to setup.py.
RUN if [ -f pyproject.toml ]; then pip install --no-cache-dir -e .; \
    elif [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; \
    elif [ -f setup.py ]; then pip install --no-cache-dir -e .; \
    else echo "no installable manifest"; exit 1; fi

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
```

Node, Go, Rust variants follow the same skeleton with their respective install commands.

### Capability policy

`smadp/autopilot/scaffolders/capability_policy.py` translates the profile's `capabilities` dict into `docker run` constraints embedded in `mcp.json`:

| Profile capability | mcp.json field | Default if true | Default if false |
| --- | --- | --- | --- |
| `network_egress: broad` | `docker_args.network` | `host` | `none` |
| `network_egress: allowlisted` | `docker_args.network` | `bridge` | — |
| `execute_shell: true` | `docker_args.privileged` | `false` (still no!) | — |
| `write_filesystem: true` | `docker_args.volumes` | `["/work:rw"]` | `["/work:ro"]` |
| `read_filesystem: true` | `docker_args.volumes` | (read-only mount) | — |
| `install_packages: true` | adds `pip install`/`apt-get` allowed during entrypoint | — | — |
| `modify_git_state: true` | mounts `.git` from /work | — | — |

The policy is encoded as a Python dataclass so it's testable in isolation.

### mcp.json template

The output matches the existing schema (see `adapters/aider/mcp.json`):

```json
{
  "slug": "{{slug}}",
  "name": "{{name}}",
  "scaffolded": true,
  "scaffolded_at": "{{now_iso}}",
  "image": "smadp/agent/{{slug}}:{{commit_pin_short}}",
  "image_digest_pinned": false,
  "command": ["sh", "-c", "/entrypoint.sh"],
  "env_required": [{{ env_required_from_profile }}],
  "env_optional": [],
  "capabilities": {{ capabilities_from_profile }},
  "io_surfaces": {{ io_surfaces_from_profile }},
  "trust_floor": {{ trust_floor }},
  "docker_args": {{ docker_args_from_policy }}
}
```

## Error handling

- **No github source** → fail-fast with `reason: "no_github_source"`. No files written.
- **Unsupported language** (UI agents, ComfyUI etc.) → `reason: "unsupported_language"`. Profile gets a `scaffold_attempted` field on disk to avoid re-attempting until a v2 detector lands.
- **Docker build fails** → `.scaffolded.json` records the build log tail; adapter dir kept for debugging but marked `success: false`.
- **mcp.json schema invalid** → adapter dir deleted; emit error log; do not commit.
- **GitHub API rate-limited / repo gone** → record + skip. Cache layer is the same one the README fetcher uses (`state/enrichment_cache/`).

## Testing

- Unit:
  - `LanguageDetector.detect` against fixture GitHub API responses (Python / Node / Go / unsupported)
  - `CapabilityPolicy.to_docker_args` against a matrix of (network_egress, write_filesystem, execute_shell) combos
  - `MCPAdapterScaffolder.scaffold` against a fixture enriched profile — assert files written, schema validates
- Integration:
  - End-to-end against 3 stable Python agents (`autogpt`, `gpt-researcher`, `crewai`): scaffold → docker build → docker run --version → record results.
  - Cap test at one Node agent (`continue-dev`) to verify the multi-language path.
- Smoke (the deliverable):
  - 5 scaffolds, all succeed docker build, all produce a valid mcp.json. Tally below.

## Cost & runtime model

- **No LLM calls.** Scaffolder is pure code generation off an already-enriched profile.
- **GitHub API**: 1 call per scaffold (metadata). Authed limit 5,000/hr is plenty.
- **Docker build**: 30-90s per agent depending on dependency tree. Local CPU only.
- **Disk**: ~200-500MB per built image. Plan for ~50-100 GB if we scaffold the full 220 docs-only set.

## Configuration additions

```yaml
# config/autopilot.yaml

scaffolders:
  mcp_adapter:
    enabled: true
    templates_dir: smadp/autopilot/scaffolders/templates
    output_dir: adapters
    image_namespace: smadp/agent
    docker_build_timeout_s: 600
    require_runnability_check: true
    trust_floor_by_evidence:
      docs-only: 0.3
      profile-verified: 0.5
      sandbox-validated: 0.7
```

## Sequencing

1. `LanguageDetector` + tests (Python / Node / Go / Rust / unsupported).
2. `CapabilityPolicy` + tests.
3. Template files (python.Dockerfile, entrypoint.sh, mcp.json.tmpl, then node/go/rust).
4. `MCPAdapterScaffolder.scaffold` + tests against fixture profile.
5. CLI: `smadp adapters scaffold --from-profile <slug>`.
6. Docker build verification helper + tests against a tiny fixture repo.
7. 5-agent smoke: scaffold `gpt-researcher`, `autogpt`, `crewai`, `langgraph`, `continue-dev`. Commit only the ones that survive docker build + runnability check.
8. After smoke: optional `smadp adapters scaffold-batch --top-n N` for bulk.

## Open questions

- **Trust floor**: a docs-only adapter trusted at 0.3 is what default? Profile-verified jumps to 0.5? Need a calibration. Initial defaults above are placeholders.
- **Image registry**: do we push built images to a registry (Docker Hub / GHCR) or keep them local? Initial answer: local only; registry push is a v2 once we have a CI account.
- **Closed-source agents** (Cursor, Claude-Code, GH Copilot): adapter pattern differs — they're API shims, not container processes. Separate spec; not blocked by this work.
- **Browser/GUI agents**: Xvfb in the Docker image works for some (ComfyUI) but not all (Cursor IDE). Punt to v2.
- **Re-scaffold cadence**: if upstream repo gets new commits, do we re-scaffold? Initial answer: only on manual `--force`; otherwise scaffolds are pinned to `commit_pin`.

## Acceptance criteria

- 5-agent smoke: each scaffold produces `Dockerfile`, `mcp.json`, `entrypoint.sh`, `.scaffolded.json`.
- All 5 `docker build` calls return 0.
- All 5 `mcp.json` files validate against the existing adapter schema.
- At least 3 of 5 pass the runnability check (`docker run --rm <image> --version` returns 0).
- One sandbox smoke: pick `aider × gpt-researcher` (existing aider adapter + new scaffold), run one scenario, get a sandbox-tier verdict on disk. This is the proof the scaffolder actually wires into the real pipeline.

If acceptance passes, the door opens to scaffolding the long tail at autopilot speed.

## Out of scope (explicitly deferred)

- Closed-source agent shims (API adapters)
- Browser / GUI agents (Xvfb compositor pipeline)
- Image registry push / cross-machine sharing
- Chain (3+ agent) scaffolding
- Auto-re-scaffolding on upstream changes
