"""Tests for CapabilityPolicy.to_docker_args."""

from __future__ import annotations

from smadp.autopilot.scaffolders.capability_policy import CapabilityPolicy


def _profile(**caps) -> dict:
    return {"capabilities": caps}


def test_broad_network_means_host_network() -> None:
    args = CapabilityPolicy.to_docker_args(_profile(network_egress="broad"))
    assert args["network"] == "host"


def test_allowlisted_network_means_bridge() -> None:
    args = CapabilityPolicy.to_docker_args(_profile(network_egress="allowlisted"))
    assert args["network"] == "bridge"


def test_no_network_means_none() -> None:
    args = CapabilityPolicy.to_docker_args(_profile(network_egress="none"))
    assert args["network"] == "none"


def test_unset_network_defaults_to_none() -> None:
    args = CapabilityPolicy.to_docker_args(_profile())
    assert args["network"] == "none"


def test_write_filesystem_true_mounts_work_rw() -> None:
    args = CapabilityPolicy.to_docker_args(_profile(write_filesystem=True))
    assert "/work:rw" in args["volumes"]


def test_write_filesystem_false_mounts_work_ro() -> None:
    args = CapabilityPolicy.to_docker_args(_profile(write_filesystem=False))
    assert "/work:ro" in args["volumes"]


def test_privileged_is_always_false() -> None:
    args = CapabilityPolicy.to_docker_args(_profile(execute_shell=True))
    assert args["privileged"] is False


def test_modify_git_state_mounts_git() -> None:
    args = CapabilityPolicy.to_docker_args(_profile(modify_git_state=True))
    assert any(".git" in v for v in args["volumes"])


def test_no_capabilities_dict_returns_safe_defaults() -> None:
    args = CapabilityPolicy.to_docker_args({})
    assert args["network"] == "none"
    assert args["privileged"] is False
    assert "/work:ro" in args["volumes"]
