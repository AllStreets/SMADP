"""``smadp proxy`` — operator-run MCP recording proxy CLI (Pillar S3.1).

Two subcommands:

* ``proxy record --slug SLUG -- <server cmd...>`` spawns the agent's configured
  MCP server, relays stdio byte-for-byte in both directions, and records every
  JSON-RPC message (secrets redacted) as content-addressed evidence.
* ``proxy synthesize --slug --name --recording sha256:<hash>`` reads a recording
  and stages a ``behavior-observed`` profile stub into
  ``catalog/profiles/_unverified/`` — operator-gated like any other seed.

Kill switch: ``state/PROXY_DISABLED`` aborts ``record`` before any spawn.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import click
import structlog

from smadp.autopilot.bootstrap import _atomic_write
from smadp.config import load_config
from smadp.proxy.jsonrpc import pump_stream
from smadp.proxy.profile import synthesize_behavior_profile
from smadp.proxy.recorder import RecordingSession

log = structlog.get_logger(__name__)


@click.group()
def proxy() -> None:
    """Operator-run MCP recording proxy (observe a closed-source agent's runtime)."""


async def _run_record(slug: str, server_cmd: list[str], session: RecordingSession) -> None:
    proc = await asyncio.create_subprocess_exec(
        *server_cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=None,  # forward child stderr to our own stderr unchanged
    )
    assert proc.stdin is not None and proc.stdout is not None

    loop = asyncio.get_event_loop()
    stdin_reader = asyncio.StreamReader()
    stdin_proto = asyncio.StreamReaderProtocol(stdin_reader)
    await loop.connect_read_pipe(lambda: stdin_proto, _stdin_binary())

    stdout_writer = _StdoutSink()

    # client -> server (our stdin -> child stdin); tee as c2s
    c2s = pump_stream(
        stdin_reader,
        _ChildStdinSink(proc.stdin),
        tee=lambda m: session.observe(m, direction="c2s"),
        direction="c2s",
    )
    # server -> client (child stdout -> our stdout); tee as s2c
    s2c = pump_stream(
        proc.stdout,
        stdout_writer,
        tee=lambda m: session.observe(m, direction="s2c"),
        direction="s2c",
    )
    await asyncio.gather(c2s, s2c)
    await proc.wait()


def _stdin_binary():
    import sys

    return sys.stdin.buffer


class _StdoutSink:
    def write(self, data: bytes) -> None:
        import sys

        sys.stdout.buffer.write(data)

    async def drain(self) -> None:
        import sys

        sys.stdout.buffer.flush()


class _ChildStdinSink:
    def __init__(self, transport: asyncio.StreamWriter) -> None:
        self._w = transport

    def write(self, data: bytes) -> None:
        self._w.write(data)

    async def drain(self) -> None:
        await self._w.drain()


@proxy.command("record")
@click.option("--slug", required=True, help="Agent slug being observed.")
@click.argument("server_cmd", nargs=-1, type=click.UNPROCESSED, required=True)
def record(slug: str, server_cmd: tuple[str, ...]) -> None:
    """Spawn the agent MCP server and record a stdio session as evidence.

    Usage: smadp proxy record --slug acme -- <server> <args...>
    """
    cfg = load_config()
    state_dir = cfg.repo_root / "state"
    if RecordingSession.is_disabled(state_dir=state_dir):
        click.echo("proxy record disabled (state/PROXY_DISABLED present)")
        raise SystemExit(0)

    session = RecordingSession(slug=slug, evidence_dir=cfg.evidence_dir)
    try:
        asyncio.run(_run_record(slug, list(server_cmd), session))
    finally:
        rec = session.finalize()
        log.info(
            "proxy.recording.captured",
            slug=slug,
            sha256=rec.sha256,
            messages=rec.message_count,
        )
        click.echo(f"recorded {rec.message_count} messages -> sha256:{rec.sha256}")
        click.echo(str(rec.path))


@proxy.command("synthesize")
@click.option("--slug", required=True, help="Agent slug.")
@click.option("--name", required=True, help="Human-readable agent name.")
@click.option(
    "--recording",
    "recording_ref",
    required=True,
    help="Recording evidence ref, e.g. sha256:<hash>.",
)
def synthesize(slug: str, name: str, recording_ref: str) -> None:
    """Synthesize a behavior-observed profile stub into _unverified/ from a recording."""
    cfg = load_config()
    sha = recording_ref.split(":", 1)[1] if recording_ref.startswith("sha256:") else recording_ref
    rec_path = cfg.evidence_dir / f"sha256-{sha}.json"
    if not rec_path.exists():
        raise click.ClickException(f"recording not found: {rec_path}")

    blob = json.loads(rec_path.read_text("utf-8"))
    messages = blob.get("messages", [])
    profile = synthesize_behavior_profile(
        slug=slug,
        name=name,
        messages=messages,
        evidence_ref=f"sha256:{sha}",
    )
    staged: Path = cfg.unverified_profiles_dir / f"{slug}.json"
    _atomic_write(staged, profile)
    log.info("proxy.profile.synthesized", slug=slug, evidence_ref=f"sha256:{sha}")
    click.echo(f"staged behavior-observed profile -> {staged}")


__all__ = ["proxy"]
