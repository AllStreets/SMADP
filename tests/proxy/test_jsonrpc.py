"""The stdio passthrough relays bytes unmodified and tees parsed messages."""

from __future__ import annotations

import asyncio
import json

import pytest

from smadp.proxy.jsonrpc import pump_stream


@pytest.mark.asyncio
async def test_pump_relays_unmodified_and_tees_each_message() -> None:
    src = asyncio.StreamReader()
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "read_file"}]}},
    ]
    raw = b"".join((json.dumps(m, separators=(",", ":")) + "\n").encode("utf-8") for m in msgs)
    src.feed_data(raw)
    src.feed_eof()

    relayed = bytearray()
    teed: list[dict] = []

    class _Sink:
        def write(self, b: bytes) -> None:
            relayed.extend(b)

        async def drain(self) -> None:
            return None

    await pump_stream(src, _Sink(), tee=teed.append, direction="c2s")

    assert bytes(relayed) == raw
    assert teed == msgs


@pytest.mark.asyncio
async def test_pump_passes_through_unparseable_lines_without_crashing() -> None:
    src = asyncio.StreamReader()
    src.feed_data(b"not json\n")
    src.feed_eof()
    relayed = bytearray()
    teed: list[dict] = []

    class _Sink:
        def write(self, b: bytes) -> None:
            relayed.extend(b)

        async def drain(self) -> None:
            return None

    await pump_stream(src, _Sink(), tee=teed.append, direction="s2c")
    assert bytes(relayed) == b"not json\n"
    assert teed == []
