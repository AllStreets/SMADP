"""Click subcommands for transparency log: verify, export."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from rich.console import Console

from smadp.config import load_config
from smadp.transparency import journal

console = Console()


@click.group(name="transparency")
def transparency_group() -> None:
    """Inspect and verify the transparency log."""


@transparency_group.command(name="verify")
@click.option(
    "--public-key",
    "public_key_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Path to a hex-encoded Ed25519 public key (32 bytes raw).",
)
@click.option(
    "--since",
    type=str,
    default=None,
    help="(ignored in v2-D Plan 1; reserved for time-bounded verify in Plan 5)",
)
def verify(public_key_path: Path, since: str | None) -> None:
    """Walk the journal and verify every signature + chain link."""
    pub_hex = public_key_path.read_text().strip()
    pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex))
    cfg = load_config()
    report = journal.verify_chain(public_key=pub, config=cfg)
    if report.valid:
        console.print("[green]OK[/green] — transparency chain intact.")
        sys.exit(0)
    else:
        console.print(
            f"[red]BREAK[/red] at event id {report.first_break}: {report.reason}"
        )
        sys.exit(1)


@transparency_group.command(name="export")
@click.option(
    "--out",
    "out_path",
    type=click.Path(dir_okay=False, path_type=Path),
    required=True,
    help="Output JSONL file path.",
)
@click.option(
    "--since",
    type=str,
    default=None,
    help="(ignored in v2-D Plan 1; full export only)",
)
def export(out_path: Path, since: str | None) -> None:
    """Export the transparency log to a JSONL file (cold storage)."""
    cfg = load_config()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with out_path.open("w", encoding="utf-8") as fh:
        for ev in journal.iter_events(config=cfg):
            fh.write(
                json.dumps(
                    ev.model_dump(mode="json"),
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            fh.write("\n")
            count += 1
    console.print(f"Exported [cyan]{count}[/cyan] events to {out_path}")


__all__ = ["transparency_group"]
