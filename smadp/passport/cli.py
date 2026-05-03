"""Click subcommands for passports: verify."""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console

from smadp.passport.verify import verify_passport

console = Console()


@click.group(name="passport")
def passport_group() -> None:
    """Inspect and verify SMADP passports."""


@passport_group.command(name="verify")
@click.argument(
    "passport_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def verify(passport_path: Path) -> None:
    """Verify a passport HTML file offline."""
    html = passport_path.read_bytes()
    result = verify_passport(html)
    if result.valid:
        console.print("[green]OK[/green] - passport signature + payload intact.")
        sys.exit(0)
    else:
        console.print(f"[red]INVALID[/red] - {result.reason}")
        sys.exit(1)


__all__ = ["passport_group"]
