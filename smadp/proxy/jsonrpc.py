"""Minimal newline-delimited stdio JSON-RPC passthrough.

No ``mcp`` package is available (see plan Spec deviation 1), so this module
implements the common MCP stdio transport directly: one JSON object per line.
The proxy's contract is byte-for-byte passthrough — we never re-serialize a
relayed message, only parse a copy to tee for recording. A malformed line is
relayed unchanged and teed as nothing, so the wrapped server is never broken
by our observation.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol

import structlog

log = structlog.get_logger(__name__)

Tee = Callable[[dict[str, Any]], None]


class _Writable(Protocol):
    def write(self, data: bytes) -> None: ...
    async def drain(self) -> None: ...


async def pump_stream(
    reader: Any,
    writer: _Writable,
    *,
    tee: Tee,
    direction: str,
) -> None:
    """Relay newline-framed messages from ``reader`` to ``writer`` unmodified.

    For every complete line that parses as a JSON object, call ``tee`` with the
    parsed dict (the original bytes are what gets relayed). EOF ends the pump.
    ``direction`` is a label ("c2s"/"s2c") for logs.
    """
    while True:
        line = await reader.readline()
        if not line:  # EOF
            return
        writer.write(line)  # passthrough fidelity: relay original bytes verbatim
        await writer.drain()
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            log.debug("proxy.jsonrpc.unparseable", direction=direction)
            continue
        if isinstance(parsed, dict):
            tee(parsed)


__all__ = ["Tee", "pump_stream"]
