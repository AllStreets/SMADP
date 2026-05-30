"""Container isolation primitives for the Sandbox Validator.

==============================================================================
THREAT MODEL  (read this before changing anything in this file)
==============================================================================

The Sandbox Validator runs untrusted, third-party agent code (open-source MCP
adapters from the catalog) in order to *observe* whether two agents will
mis-behave when composed. The sandbox itself MUST NOT become the attack
surface — a leaky sandbox would defeat the entire premise of SMADP and would
be catastrophic. The defenses below are layered intentionally so that the
failure of any single layer does not produce host compromise or data exfil.

Layer 1 — Runtime
    Prefer rootless **Podman** with the **gVisor** (`runsc`) OCI runtime for
    syscall-level isolation. Fall back to Docker + gVisor; warn loudly if
    gVisor is unavailable; refuse to run in unsandboxed `runc` mode unless an
    explicit operator override is set (not exposed in this v1 module — the
    runner refuses).

Layer 2 — Network
    Default ``--network none``. Each scenario explicitly allow-lists outbound
    endpoints (typically just the agent's required inference API). Egress
    flows through a recording HTTP/HTTPS proxy that audits every request and
    rejects anything not on the allow-list. The container has no DNS resolver
    other than the proxy.

Layer 3 — Filesystem
    Read-only root (`--read-only`); a small tmpfs is mounted at the working
    directory. **No host bind mounts, ever.** Transcripts are streamed out via
    container stdout/stderr, not via shared volumes.

Layer 4 — Capabilities
    `--cap-drop ALL`, `--security-opt no-new-privileges`, restrictive seccomp
    profile (`runtime/default` at minimum; gVisor enforces a much smaller
    syscall surface on top of that). Container runs as `--user 65534:65534`
    (`nobody:nogroup`).

Layer 5 — Resources
    Cgroups v2 limits on CPU (`--cpus`), memory (`--memory`,
    `--memory-swap`), PIDs (`--pids-limit`), and IO. Wall-clock kill at 5
    minutes (`timeout_s`).

Layer 6 — Lifetime
    Containers are ephemeral and destroyed at scenario end (`--rm`). State is
    not persisted; only the structured transcript is kept.

Layer 7 — Supply chain
    Images are pinned by digest (``image@sha256:...``) — never `:latest` — and
    must appear in the allowlist enforced by ``smadp.sandbox.policy``. Image
    pulls happen via the runtime's content-trust verifier when available.

Layer 8 — Secrets
    Only synthetic secrets prefixed with ``SMADP_TEST_`` /
    ``synthetic-test-only-`` are accepted. The queue (``smadp.sandbox.queue``)
    rejects any value that pattern-matches a real key; this module provides
    one more check immediately before invoking the runtime.

==============================================================================

This module does not actually *execute* containers; it only:

  * detects which runtime is available and whether gVisor is present
  * builds a fully-validated argv list for the runtime CLI
  * validates the spec against ``policy.py`` before returning the argv

Execution itself happens in :mod:`smadp.sandbox.runner` via
``asyncio.create_subprocess_exec`` (never ``shell=True`` — the argv is a list).
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

import structlog

from smadp.sandbox.policy import (
    assert_egress_allowlist_ok,
    assert_image_approved,
    assert_safe_secrets,
)

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Runtime detection
# ---------------------------------------------------------------------------


class RuntimeBackend(StrEnum):
    """Identifies the (engine, runtime) pair the sandbox will use."""

    PODMAN_RUNSC = "podman+runsc"
    PODMAN = "podman"
    DOCKER_RUNSC = "docker+runsc"
    DOCKER = "docker"


# Order of preference: stronger isolation first.
_PREFERRED_ORDER: tuple[RuntimeBackend, ...] = (
    RuntimeBackend.PODMAN_RUNSC,
    RuntimeBackend.DOCKER_RUNSC,
    RuntimeBackend.PODMAN,
    RuntimeBackend.DOCKER,
)


class RuntimeUnavailableError(RuntimeError):
    """Raised when no suitable container runtime is present on the host."""


def _engine_binary(backend: RuntimeBackend) -> str:
    return "podman" if backend.value.startswith("podman") else "docker"


def _has_binary(name: str) -> bool:
    return shutil.which(name) is not None


def _runsc_available_for(engine: str) -> bool:
    """Return True if the engine reports ``runsc`` as a registered runtime."""
    if not _has_binary(engine):
        return False
    # ``info --format`` is supported by both docker and podman.
    try:
        proc = subprocess.run(
            [engine, "info", "--format", "{{json .}}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if proc.returncode != 0:
        return False
    # Cheap substring test rather than parsing — both engines emit "runsc"
    # when it's available either as a runtime or in the OCI runtimes list.
    return "runsc" in proc.stdout


def detect_runtime() -> RuntimeBackend:
    """Return the strongest available container backend.

    Raises :class:`RuntimeUnavailableError` if neither podman nor docker is
    present. Logs a structured warning when only an unsandboxed (no-gVisor)
    runtime is available.
    """
    have_podman = _has_binary("podman")
    have_docker = _has_binary("docker")
    podman_runsc = have_podman and _runsc_available_for("podman")
    docker_runsc = have_docker and _runsc_available_for("docker")

    available: dict[RuntimeBackend, bool] = {
        RuntimeBackend.PODMAN_RUNSC: podman_runsc,
        RuntimeBackend.DOCKER_RUNSC: docker_runsc,
        RuntimeBackend.PODMAN: have_podman,
        RuntimeBackend.DOCKER: have_docker,
    }

    for backend in _PREFERRED_ORDER:
        if available[backend]:
            if backend in (RuntimeBackend.PODMAN, RuntimeBackend.DOCKER):
                log.warning(
                    "sandbox.runtime.no_gvisor",
                    backend=backend.value,
                    message=(
                        "gVisor (runsc) not detected. Falling back to native "
                        "OCI runtime. Sandbox isolation guarantees are reduced; "
                        "do NOT use this configuration for production runs."
                    ),
                )
            else:
                log.info("sandbox.runtime.detected", backend=backend.value)
            return backend

    raise RuntimeUnavailableError(
        "Neither 'podman' nor 'docker' is available on PATH. "
        "Install podman (preferred) and gVisor (runsc) before running the "
        "Sandbox Validator."
    )


# ---------------------------------------------------------------------------
# Container spec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContainerSpec:
    """Fully-resolved spec for one sandbox container.

    Validated by :func:`build_run_command` before any argv is produced; the
    runner constructs one of these per agent in a scenario.
    """

    name: str
    """Container name; should be unique within a run (used for transcripts)."""

    image_digest: str
    """Pinned image reference of the form ``name@sha256:<64-hex>``."""

    args: tuple[str, ...]
    """Command + args to run inside the container (replaces ENTRYPOINT)."""

    env: Mapping[str, str] = field(default_factory=dict)
    """Environment variables. Values must pass ``policy.is_safe_secret`` if
    keyed by anything resembling a credential; the runner enforces this."""

    working_dir: str = "/work"
    """Path inside the container for the tmpfs working directory."""

    network_mode: str = "none"
    """Either ``none`` or ``bridge``. ``bridge`` requires a non-empty
    ``allow_egress`` list and a recording proxy in front."""

    allow_egress: tuple[str, ...] = ()
    """Hostnames the container is permitted to reach via the egress proxy."""

    cpu_limit: float = 1.0
    """Cgroup v2 CPU cap (number of cores)."""

    mem_limit_mb: int = 1024
    """Cgroup v2 memory cap, MiB."""

    pids_limit: int = 256
    """Maximum number of processes/threads."""

    tmpfs_size_mb: int = 256
    """Size of the working-directory tmpfs."""

    timeout_s: int = 300
    """Wall-clock kill (seconds). The runner also enforces this externally."""

    read_only_root: bool = True

    user: str = "65534:65534"  # nobody:nogroup
    """Numeric uid:gid the container runs as. Never root."""

    seccomp_profile: str | None = None
    """Path to a custom seccomp JSON. ``None`` => engine default
    (which is already restrictive)."""

    extra_labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Lightweight invariant checks; full validation runs in
        # ``build_run_command`` where we also have the backend.
        if not self.args:
            raise ValueError("ContainerSpec.args must not be empty")
        if self.network_mode not in {"none", "bridge"}:
            raise ValueError(f"network_mode must be 'none' or 'bridge', got {self.network_mode!r}")
        if self.network_mode == "none" and self.allow_egress:
            raise ValueError("allow_egress requires network_mode='bridge'")
        if self.network_mode == "bridge" and not self.allow_egress:
            raise ValueError(
                "network_mode='bridge' requires a non-empty allow_egress list "
                "(an empty list means 'no egress' — use network_mode='none' instead)"
            )
        if self.cpu_limit <= 0 or self.cpu_limit > 8:
            raise ValueError(f"cpu_limit must be in (0, 8], got {self.cpu_limit}")
        if self.mem_limit_mb <= 0 or self.mem_limit_mb > 8192:
            raise ValueError(f"mem_limit_mb must be in (0, 8192], got {self.mem_limit_mb}")
        if self.timeout_s <= 0 or self.timeout_s > 1800:
            raise ValueError(f"timeout_s must be in (0, 1800], got {self.timeout_s}")
        if self.pids_limit <= 0 or self.pids_limit > 4096:
            raise ValueError(f"pids_limit must be in (0, 4096], got {self.pids_limit}")
        if not self.user or self.user.startswith("0") or self.user.startswith("root"):
            raise ValueError(f"Container must not run as root; got user={self.user!r}")


# ---------------------------------------------------------------------------
# argv construction
# ---------------------------------------------------------------------------


def _runtime_flag(backend: RuntimeBackend) -> list[str]:
    """Return the engine-specific flags that select gVisor when applicable."""
    if backend in (RuntimeBackend.PODMAN_RUNSC, RuntimeBackend.DOCKER_RUNSC):
        # Both engines accept ``--runtime runsc``.
        return ["--runtime", "runsc"]
    return []


def build_run_command(spec: ContainerSpec, backend: RuntimeBackend) -> list[str]:
    """Build the validated argv list for ``<engine> run ...``.

    Performs a final policy check against ``smadp.sandbox.policy`` so that the
    spec cannot reach the runtime if it has been tampered with after
    construction. Returns a flat list suitable for
    :func:`asyncio.create_subprocess_exec` (never pass to a shell).
    """
    # Defense-in-depth: re-run policy validations even if the runner already
    # did them. Cheap and prevents a future code path from skipping them.
    assert_image_approved(spec.image_digest)
    assert_safe_secrets(dict(spec.env))
    if spec.allow_egress:
        assert_egress_allowlist_ok(spec.allow_egress)

    engine = _engine_binary(backend)
    argv: list[str] = [engine, "run", "--rm", "--name", spec.name]

    # Runtime selection (gVisor if available)
    argv.extend(_runtime_flag(backend))

    # ---- Hardening flags (every container, every time) -------------------
    argv.extend(
        [
            "--user",
            spec.user,
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(spec.pids_limit),
            "--cpus",
            f"{spec.cpu_limit:.2f}",
            "--memory",
            f"{spec.mem_limit_mb}m",
            "--memory-swap",
            f"{spec.mem_limit_mb}m",  # disable swap
        ]
    )
    if spec.read_only_root:
        argv.append("--read-only")

    # tmpfs for the working directory; noexec/nosuid; size-capped.
    # Pass uid/gid from spec.user so the mount root is owned by the container's
    # non-root user. (mode=1777 alone is silently ignored when --cap-drop ALL
    # is set, leaving the tmpfs at 0755 root-owned and unwritable.)
    uid_str, _, gid_str = spec.user.partition(":")
    tmpfs_owner = f"uid={uid_str},gid={gid_str or uid_str}"
    argv.extend(
        [
            "--tmpfs",
            f"{spec.working_dir}:rw,noexec,nosuid,nodev,size={spec.tmpfs_size_mb}m,{tmpfs_owner}",
        ]
    )
    # /tmp also as tmpfs so the read-only root works for tools that scribble.
    argv.extend(
        [
            "--tmpfs",
            f"/tmp:rw,noexec,nosuid,nodev,size=64m,{tmpfs_owner}",  # noqa: S108 — inside container
        ]
    )

    # Workdir
    argv.extend(["--workdir", spec.working_dir])

    # Network: 'none' is hard-isolated. 'bridge' is only chosen when an
    # egress proxy is configured by the runner; this module just sets the
    # mode and trusts the runner to place the proxy in front.
    argv.extend(["--network", spec.network_mode])

    # Seccomp
    if spec.seccomp_profile:
        argv.extend(["--security-opt", f"seccomp={spec.seccomp_profile}"])
    # Else: engine default profile (already restrictive)

    # Env vars (only synthetic secrets reach this point — see
    # assert_safe_secrets above; extra defense at runner level).
    for key, value in sorted(spec.env.items()):
        if "=" in key:
            raise ValueError(f"Invalid env var name (contains '='): {key!r}")
        argv.extend(["--env", f"{key}={value}"])

    # Labels (used by the runner / external observability tools).
    for key, value in sorted(spec.extra_labels.items()):
        argv.extend(["--label", f"{key}={value}"])

    # Override the image's ENTRYPOINT with args[0]. Without this, docker
    # treats spec.args as positional args appended to the image's ENTRYPOINT,
    # which silently breaks adapters whose images set ENTRYPOINT (e.g.
    # paulgauthier/aider). The ContainerSpec.args docstring promises the
    # caller's args fully replace ENTRYPOINT — this flag enforces that.
    argv.extend(["--entrypoint", spec.args[0]])

    # Image — last positional before command. Pinned by digest; verified
    # above by ``assert_image_approved``.
    argv.append(spec.image_digest)

    # Remaining args become CMD; together with --entrypoint they form the
    # full command line inside the container.
    argv.extend(spec.args[1:])

    return argv


__all__ = [
    "ContainerSpec",
    "RuntimeBackend",
    "RuntimeUnavailableError",
    "build_run_command",
    "detect_runtime",
]
