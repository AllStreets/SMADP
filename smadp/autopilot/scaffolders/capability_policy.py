"""CapabilityPolicy: profile capabilities → docker run flags.

Translates the enriched-profile capability surface into the bounded set of
docker_args that the sandbox runner enforces at launch. The mapping is
deliberately conservative: missing/unknown capability defaults to the most
restrictive option.
"""

from __future__ import annotations

from typing import Any


class CapabilityPolicy:
    @staticmethod
    def to_docker_args(profile: dict[str, Any]) -> dict[str, Any]:
        caps = (profile.get("capabilities") or {}) if isinstance(profile, dict) else {}

        network_egress = caps.get("network_egress")
        if network_egress == "broad":
            network = "host"
        elif network_egress == "allowlisted":
            network = "bridge"
        else:
            network = "none"

        write_fs = bool(caps.get("write_filesystem"))
        volumes: list[str] = []
        volumes.append("/work:rw" if write_fs else "/work:ro")
        if caps.get("modify_git_state"):
            volumes.append("/work/.git:rw")

        return {
            "network": network,
            "volumes": volumes,
            "privileged": False,
            "install_packages_allowed": bool(caps.get("install_packages")),
        }
