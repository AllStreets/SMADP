"""Synthesize a runtime behavior-observed profile from an MCP recording.

Deterministic, pure-Python: reads the recorded (redacted) JSON-RPC messages and
derives the observed runtime surfaces — tools actually called, filesystem paths
touched, network hosts contacted. The result is a profile stub at
``evidence_level: "behavior-observed"`` that lands in
``catalog/profiles/_unverified/`` and passes through the operator gate exactly
like a docs-only or ONEXUS seed. No LLM, no numbers that rank.

The stub is a *full* Safety Profile (validates against ``schemas.profile.Profile``):
the behavior-observed rung sits above ``unverified-profile``, so it cannot use
the minimal unverified-stub schema. We fill the schema's required fields with
honest placeholders — ``source_type: closed-source`` (the proxy exists precisely
to observe closed-source agents) and ``verification.method: auto-only`` (no human
reviewed it; it is machine-observed) — and carry the real observations under
``onexus.behavior``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import urlparse

from smadp.utils.time import utcnow

_FILE_ARG_KEYS = ("path", "file", "filename", "dir", "directory")
_URL_ARG_KEYS = ("url", "endpoint", "uri", "host")


def _iter_tool_calls(messages: list[dict[str, Any]]) -> Iterator[tuple[Any, dict[str, Any]]]:
    for entry in messages:
        msg = entry.get("message", {})
        if msg.get("method") == "tools/call":
            params = msg.get("params", {})
            yield params.get("name"), params.get("arguments", {}) or {}


def synthesize_behavior_profile(
    *, slug: str, name: str, messages: list[dict[str, Any]], evidence_ref: str
) -> dict[str, Any]:
    observed_tools: list[str] = []
    file_paths: list[str] = []
    network_hosts: list[str] = []
    for tool_name, args in _iter_tool_calls(messages):
        if tool_name and tool_name not in observed_tools:
            observed_tools.append(tool_name)
        for k, v in args.items():
            if isinstance(v, str):
                if k in _FILE_ARG_KEYS and v not in file_paths:
                    file_paths.append(v)
                if k in _URL_ARG_KEYS:
                    host = urlparse(v).netloc or v
                    if host and host not in network_hosts:
                        network_hosts.append(host)

    now = utcnow().isoformat(timespec="seconds").replace("+00:00", "Z")
    behavior = {
        "observed_tools": sorted(observed_tools),
        "file_paths": sorted(file_paths),
        "network_hosts": sorted(network_hosts),
        "source": "mcp-recording-proxy",
    }
    return {
        "schema_version": "1.2",
        "slug": slug,
        "name": name,
        # Required full-Profile fields, honest placeholders for a machine-observed
        # closed-source agent. The operator gate enriches these before publish.
        "vendor": {"type": "org", "handle": slug},
        "source_type": "closed-source",
        "category": "observed-runtime",
        "verification": {
            "status": "unverified",
            "verified_at": now,
            "method": "auto-only",
        },
        "evidence_level": "behavior-observed",
        "evidence_refs": [evidence_ref],
        "first_seen_at": now,
        "last_refreshed_at": now,
        "onexus": {"behavior": behavior},
    }


__all__ = ["synthesize_behavior_profile"]
