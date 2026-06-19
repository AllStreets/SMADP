#!/usr/bin/env bash
# scripts/sandbox-validate-host.sh
#
# End-to-end sandbox validation on a host with a real container runtime.
# Builds adapter images from their Dockerfiles, approves them by their local
# image digest, enqueues cooperative + adversarial scenario runs for every
# bindable pair that already has a published verdict, and drains the queue so
# `promote_from_run` bumps each verdict toward `sandbox-validated`.
#
# WHY THIS SCRIPT EXISTS
#   The autopilot loop only DRAINS the sandbox queue (`sandbox work --once
#   --max 3`); nothing auto-enqueues runs, and only ~5 agents have approved
#   images. This script is the manual "go wide" path: build a vetted set of
#   agents, approve them, and validate their pairs.
#
# ADVERSARIAL SCENARIOS NEED gVisor (runsc), WHICH IS LINUX-ONLY.
#   - On Linux with podman + gVisor installed: all 9 scenarios run.
#   - On macOS / no gVisor: cooperative scenarios fall back to plain Docker
#     (reduced isolation); the 4 adversarial scenarios ERROR. Pass
#     COOPERATIVE_ONLY=1 there to skip them cleanly.
#
# USAGE
#   scripts/sandbox-validate-host.sh aider crewai smolagents ...
#   AGENTS="crewai smolagents" scripts/sandbox-validate-host.sh
#   COOPERATIVE_ONLY=1 scripts/sandbox-validate-host.sh crewai smolagents
#   SKIP_BUILD=1 scripts/sandbox-validate-host.sh aider          # reuse approved images
#
# PREREQUISITES
#   - Docker (or podman) running; for adversarial: podman + gVisor (runsc).
#   - ~/.smadp/keys.env (0600) containing OPENAI_API_KEY  (auto-seeded from .env).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [ -d "$REPO_ROOT/.venv" ]; then
  export PATH="$REPO_ROOT/.venv/bin:$PATH"
fi

AGENTS="${AGENTS:-$*}"
if [ -z "${AGENTS// }" ]; then
  echo "usage: $0 <agent-slug> [agent-slug ...]   (or AGENTS=\"a b c\" $0)" >&2
  exit 2
fi

APPROVED_JSON="$REPO_ROOT/smadp/sandbox/approved_images.json"
COOPERATIVE_ONLY="${COOPERATIVE_ONLY:-0}"
SKIP_BUILD="${SKIP_BUILD:-0}"

# ---------------------------------------------------------------- keys.env
# The worker injects allowlisted real keys (only OPENAI_API_KEY) into each
# container from ~/.smadp/keys.env. Seed it from the repo .env if absent.
mkdir -p "$HOME/.smadp"
if [ ! -f "$HOME/.smadp/keys.env" ] && [ -f "$REPO_ROOT/.env" ]; then
  KEY="$(grep -E '^OPENAI_API_KEY=' "$REPO_ROOT/.env" | head -1 || true)"
  if [ -n "$KEY" ]; then
    ( umask 177; printf '%s\n' "$KEY" > "$HOME/.smadp/keys.env" )
    chmod 600 "$HOME/.smadp/keys.env"
    echo "seeded ~/.smadp/keys.env from .env"
  fi
fi

# ---------------------------------------------------------------- build + approve
# Build each adapter image and approve it by its LOCAL image id (sha256:<id>),
# which docker/podman accept as a run reference and which approved_images.json
# validates (the policy regex permits a bare sha256: digest). This avoids
# needing a registry push. On a shared/prod host, prefer pushing to a registry
# and using `smadp sandbox pin-images` so every host validates the same digest.
if [ "$SKIP_BUILD" != "1" ]; then
  for slug in $AGENTS; do
    if [ ! -f "$REPO_ROOT/adapters/$slug/Dockerfile" ]; then
      echo "skip $slug: no adapters/$slug/Dockerfile (uses an upstream image?)" >&2
      continue
    fi
    echo "==> building $slug"
    tag="smadp/agent/$slug:built"
    docker build -t "$tag" "$REPO_ROOT/adapters/$slug"
    iid="$(docker inspect --format '{{.Id}}' "$tag")"   # sha256:<64hex>
    echo "    approving $slug -> $iid"
    # Update approved_images.json[slug] and adapters/<slug>/mcp.json pin atomically.
    python - "$slug" "$iid" "$APPROVED_JSON" "$REPO_ROOT/adapters/$slug/mcp.json" <<'PY'
import json, sys
slug, iid, approved_path, mcp_path = sys.argv[1:5]
approved = json.load(open(approved_path))
approved[slug] = iid
json.dump(approved, open(approved_path, "w"), indent=2, sort_keys=True)
open(approved_path, "a").write("\n")
mcp = json.load(open(mcp_path))
mcp["image"] = f"smadp/agent/{slug}:built"
mcp["image_digest_pinned"] = iid
# Preserve the file's existing (compact) layout as closely as practical.
open(mcp_path, "w").write(json.dumps(mcp, indent=2) + "\n")
print(f"    approved {slug}")
PY
  done
fi

# ---------------------------------------------------------------- enqueue
# Enqueue every bindable (pair x scenario) among the target agents that already
# has a published verdict. Capability binding + scenario set computed in Python.
echo "==> enqueuing runs"
# shellcheck disable=SC2086  # AGENTS is an intentional space-separated arg list
python - "$COOPERATIVE_ONLY" $AGENTS <<'PY'
import itertools, json, glob, sys
from pathlib import Path
from smadp.config import load_config
from smadp.sandbox.binding import bind_scenario, load_adapter_capabilities, ScenarioBindingError
from smadp.sandbox.scenarios import list_builtin_scenarios, load_scenario
from smadp.sandbox.queue import enqueue_sandbox_run

coop_only = sys.argv[1] == "1"
agents = sys.argv[2:]
cfg = load_config()

pub = set()
for p in glob.glob("catalog/verdicts/*.json"):
    if p.endswith(".sig.json"):
        continue
    pr = json.loads(Path(p).read_text()).get("pair")
    if isinstance(pr, list) and len(pr) == 2:
        pub.add(tuple(sorted(pr)))

scens = []
for s in list_builtin_scenarios():
    sc = load_scenario(s)
    if len(sc.agents) != 2:
        continue
    if coop_only and sc.mode != "cooperative":
        continue
    scens.append(s)

caps = {a: load_adapter_capabilities(a) for a in agents}
enq = 0
for a, b in itertools.combinations(sorted(agents), 2):
    if tuple(sorted((a, b))) not in pub:
        continue
    for s in scens:
        try:
            bind_scenario(scenario=load_scenario(s), agents={a: caps[a], b: caps[b]})
        except ScenarioBindingError:
            continue
        try:
            enqueue_sandbox_run(slug_a=a, slug_b=b, scenario=s, config=cfg)
            enq += 1
        except Exception as exc:  # noqa: BLE001
            print(f"    enqueue skip {a}<>{b}/{s}: {exc}")
print(f"    enqueued {enq} runs")
PY

# ---------------------------------------------------------------- drain
# Drain WITHOUT --once (--once stops after a single run). The daily cap
# (config/autopilot.yaml runs_per_day) still applies.
echo "==> draining queue (sandbox work)"
smadp sandbox work --max 500

echo "==> done. Verify with:  smadp lint --catalog catalog   and the homepage sandbox-validated tile."
