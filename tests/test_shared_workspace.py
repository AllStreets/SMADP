"""The pair shares one workspace, and it is still a sandbox.

The adversarial scenarios are premised on an attacker planting a file a victim
reads. Every container previously received a private tmpfs at its working
directory, so the attacker planted into its own filesystem, the victim read an
empty one, and the run graded as though no attack succeeded. That is
indistinguishable in the record from a victim that resisted.
"""
from __future__ import annotations

from smadp.sandbox.isolation import (
    ContainerSpec,
    RuntimeBackend,
    build_run_command,
    build_shared_workspace_create_command,
    build_shared_workspace_remove_command,
)
from smadp.sandbox.policy import APPROVED_IMAGES

BACKEND = RuntimeBackend.DOCKER
DIGEST = next(iter(APPROVED_IMAGES.values()))


def _spec(volume: str | None) -> ContainerSpec:
    return ContainerSpec(
        name="smadp-test-agent",
        image_digest=DIGEST,
        args=["sh", "-c", "true"],
        env={},
        working_dir="/work",
        shared_workspace_volume=volume,
    )


def test_without_a_volume_the_workspace_stays_private() -> None:
    argv = build_run_command(_spec(None), BACKEND)
    joined = " ".join(argv)
    assert "--tmpfs /work:rw,noexec,nosuid,nodev" in joined
    assert "type=volume" not in joined


def test_with_a_volume_both_agents_mount_the_same_one() -> None:
    argv = build_run_command(_spec("smadp-run-work"), BACKEND)
    joined = " ".join(argv)
    assert "type=volume,source=smadp-run-work,target=/work" in joined
    # The private tmpfs for the working directory must not also be mounted, or
    # it would shadow the shared volume and restore the original bug silently.
    assert "--tmpfs /work:" not in joined


def test_the_shared_volume_keeps_the_private_tmpfs_hardening() -> None:
    """Shared must not mean more permissive. The options mirror the private
    tmpfs exactly, so the only difference is that two containers see it."""
    argv = build_shared_workspace_create_command(
        "smadp-run-work", size_mb=256, user="65534:65534", backend=BACKEND)
    joined = " ".join(argv)
    assert "type=tmpfs" in joined and "device=tmpfs" in joined
    for opt in ("noexec", "nosuid", "nodev", "size=256m", "uid=65534", "gid=65534"):
        assert opt in joined, f"{opt} missing from the shared workspace options"


def test_the_shared_volume_never_touches_the_host_filesystem() -> None:
    """The module forbids host bind mounts. A tmpfs-backed local volume keeps
    contents in memory, so the rule holds and the data is gone when the last
    container unmounts."""
    argv = build_shared_workspace_create_command(
        "smadp-run-work", size_mb=256, user="65534:65534", backend=BACKEND)
    joined = " ".join(argv)
    assert "type=tmpfs" in joined
    assert "/" not in joined.split("--opt o=")[1].split()[0]  # no host path in opts
    # And the run command uses --mount, never -v with a host path.
    run = " ".join(build_run_command(_spec("smadp-run-work"), BACKEND))
    assert " -v " not in run


def test_removal_is_forced_so_a_name_is_never_reused() -> None:
    argv = build_shared_workspace_remove_command("smadp-run-work", BACKEND)
    assert argv[1:] == ["volume", "rm", "-f", "smadp-run-work"]


def test_every_other_hardening_flag_survives_the_shared_mount() -> None:
    joined = " ".join(build_run_command(_spec("smadp-run-work"), BACKEND))
    for flag in ("--cap-drop ALL", "--read-only", "--user", "no-new-privileges"):
        assert flag in joined, f"{flag} lost when the workspace became shared"
    # /tmp stays private per container.
    assert "--tmpfs /tmp:" in joined
