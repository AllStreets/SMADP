# Sandbox Isolation

This document specifies the v1 isolation model for the SMADP Sandbox Validator. It is the source of truth for what the validator can and cannot contain, the runtime stack, the network and filesystem policy, and the explicit limits in v1.

The validator exists to produce layer-3 evidence ([`methodology.md`](methodology.md) §1) for open-source pairs. It is not a customer-facing sandbox and does not host live agent workloads. Related reading: [`threat-model.md`](threat-model.md) §4.4.

---

## 1. Threat model

The single overriding threat: **the sandbox MUST NOT be the source of the very leakage, capability-conflict, or data-exfiltration risks SMADP is meant to detect.** A leaky sandbox would invalidate every `sandbox-validated` verdict in the catalog and would itself become a vector for the harms SMADP exists to surface. Spec §11.

Adversaries the sandbox must defend against:

- A malicious or compromised open-source agent submitted for validation that attempts to escalate, escape, or exfiltrate.
- A buggy agent that fork-bombs, fills the disk, or pegs CPU.
- A scenario that accidentally exposes real secrets or production endpoints.
- A supply-chain compromise of an MCP adapter or container image.

The validator host should be considered a high-value target and should not be co-located with sensitive infrastructure.

---

## 2. Runtime stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Container engine (preferred) | **Rootless Podman** | No long-running daemon; user-namespaced; no root on host required. |
| Container engine (fallback) | **Docker** | Used only when rootless Podman is unavailable. Weaker isolation; deployments using the fallback should not co-locate with sensitive infra. |
| Sandbox runtime | **gVisor `runsc`** | User-space kernel; drastically narrows the host syscall surface exposed to the container. Required in both Podman and Docker paths. |
| Host kernel | Linux >= 5.15 with cgroups v2 | Required for the resource-limit profile below. |

Image policy (spec §11, §21):

- Pinned digests only. Images are referenced as `docker.io/library/python@sha256:...`, never by floating tag.
- Allowlist of approved base images stored at `adapters/_meta/image-allowlist.json`. New base images require review.
- Images are signed; signatures are verified at pull time.

---

## 3. Network policy

Default: **`--network none`**. The sandboxed container has no network access at all.

Per-scenario opt-in: a scenario may declare an outbound endpoint allowlist (e.g., the agent's required inference API). Allowlisted endpoints route through an egress proxy that:

- Logs every request (URL, method, request size, timestamp) to the scenario transcript.
- Rejects any request to a host not on the allowlist.
- Strips forwarded auth headers other than the synthetic credentials provisioned for the scenario.
- Enforces a per-scenario egress byte cap.

The proxy log is committed to the catalog as part of the sandbox transcript and is part of the evidence supporting any `sandbox-validated` verdict.

| Scenario type | Default network policy |
|---------------|------------------------|
| Filesystem-only scenario | `--network none` |
| Single-agent inference call | Allowlist: agent's inference API only |
| Two-agent interaction via MCP | Allowlist: each agent's inference API only; MCP transport is local (Unix socket or shared tmpfs) |

Inbound network is never opened.

---

## 4. Filesystem policy

- **Read-only base image.** The container's root filesystem is mounted read-only. Any required scratch space comes from a tmpfs mount.
- **Tmpfs working directory.** Each scenario gets a fresh `tmpfs` mount at the working directory the agents are pointed at. Capped at a per-scenario byte limit (default 256 MiB).
- **No host mounts.** The validator never bind-mounts a host directory into the container. Scenario fixtures (test files, mock repositories) are baked into the scenario image or copied in via `podman cp` at scenario startup.
- **No persistent state.** When the container exits, the tmpfs is gone. Transcripts are persisted; container state is not.

Files the agents create during a scenario are captured into the transcript as part of the post-scenario diff, then discarded.

---

## 5. Capabilities and syscall surface

- **`--user nobody`** — non-root user inside the container.
- **`--cap-drop ALL`** — every Linux capability dropped. Capabilities the agent legitimately needs must be re-granted explicitly per scenario.
- **`--security-opt no-new-privileges`** — `setuid`/`setgid` cannot raise privileges.
- **Restrictive seccomp profile** — the gVisor default seccomp profile narrowed by removing rarely-needed syscalls. Stored at `smadp/sandbox/profiles/seccomp.json`.
- **AppArmor / SELinux profile** — applied where available on the host.

The combined effect is that an agent inside the sandbox sees a Linux that supports normal POSIX file IO, process creation, and network sockets through the egress proxy — and very little else.

---

## 6. Resource limits

Enforced through cgroups v2:

| Resource | Default cap | Notes |
|----------|-------------|-------|
| CPU | 2 vCPU equivalent (cpu.max) | Adjustable per scenario; max 4. |
| Memory | 2 GiB (memory.max) | Hard cap; OOM kills the container. |
| PIDs | 256 (pids.max) | Defends against fork-bombs. |
| IO | 50 MiB/s read, 25 MiB/s write (io.max) | Defends against disk thrashing. |
| Wall-clock | 5 minutes | Hard kill at the scheduler level. |
| Egress bytes | Per-scenario, default 100 MiB | Enforced by the egress proxy, not cgroups. |

Lifetime is ephemeral. Containers are created at scenario start and destroyed at scenario end (success, failure, or timeout). Spec §11.

---

## 7. Secrets policy

- **Synthetic secrets only.** Scenario inputs include synthetic API keys, OAuth tokens, and credentials that match the format vendors expect but are not valid against any real service.
- **Real secrets rejected at the scheduler.** The sandbox queue (`smadp/sandbox/queue.py`) inspects scenario manifests and rejects any whose inputs match the regex shapes of real Anthropic, OpenAI, GitHub, AWS, GCP, Stripe, or major-vendor credentials. The check is intentionally aggressive; false positives are preferable to false negatives.
- **No environment-variable inheritance.** The container inherits no environment from the host other than what the scenario manifest explicitly declares.
- **No host keyring access.** The container is launched in a fresh user namespace with no access to the host's keyring or session bus.

---

## 8. Observability

Every sandbox run emits:

- **stdin/stdout** of each agent, captured per-process to the transcript.
- **File IO log** — every file read or write inside the tmpfs working directory, captured by an auditd-equivalent or LD_PRELOAD shim depending on the scenario type.
- **Network attempts** — captured at the egress proxy. Includes blocked attempts (those become evidence of the agent attempting unauthorized egress).
- **Container logs** — gVisor and Podman/Docker logs.
- **Resource usage** — peak CPU, memory, PID count, IO bytes.

The transcript is the artifact that gets cited in a `sandbox-validated` verdict's `sandbox_runs[]` array. It is committed to the catalog and is part of the public evidence chain.

---

## 9. Queue model

The sandbox queue is SQLite-backed (no external broker) at `validator/queue.db`. One worker process per host. Horizontal scale by adding hosts; each host pulls from the same shared catalog repo via a git remote and coordinates via row-level locks in SQLite.

States: `pending` → `running` → `completed` or `failed`. Spec §11.

A `sandbox.run.started` and `sandbox.run.completed` event is appended to the chronicle for each run.

---

## 10. What is NOT supported in v1

This is the most important section for a security reviewer. SMADP is explicit about what the v1 validator cannot do:

- **Closed-source agents.** No capability adapters exist for Claude Code, Cursor, ChatGPT Desktop, Perplexity, Windsurf, Devin, Replit Agent, Copilot, Gemini CLI, or Notion AI in v1. These pairs stay at `evidence_level: docs-only` regardless of sandbox capacity. Closed-source adapters are on the v2 roadmap (spec §5, §19).
- **GUI-driven IDE agents requiring a desktop UI surface** (Cursor desktop, Windsurf desktop, etc.). The sandbox is a headless container; a scenario that requires the IDE's UI cannot run.
- **Agents requiring elevated privileges** (`sudo`, root, kernel modules). The sandbox enforces `--cap-drop ALL` and `--user nobody`. An agent that does not work without root cannot be sandbox-validated.
- **Agents that require persistent state across invocations** beyond what fits in a 5-minute scenario. Long-running training jobs, background indexers, and similar workloads are out of scope.
- **Three-or-more-agent compositions.** The validator supports pairwise scenarios only. N-agent chains are spec §5 / v2 scope.
- **Customer environments.** The validator is not a hosting service. It does not run a user's own agent stack against a verdict question; it produces evidence for the public catalog only.

For any of these, the verdict honestly reports `evidence_level: docs-only` (or lower) and the dashboard makes the limitation visible. Overclaiming validation when the validator did not (or could not) run is the failure mode SMADP is designed to prevent.

---

Last updated: 2026-05-02
