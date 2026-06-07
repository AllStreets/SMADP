"""Adapter scaffolders — turn enriched profiles into runnable MCP adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class ScaffolderResultLike(Protocol):
    target_dir: Path
    files_written: list[Path]
    success: bool
    reason: str


class Scaffolder(Protocol):
    name: str

    def scaffold(self, profile: dict[str, Any], *, target_dir: Path) -> ScaffolderResultLike: ...
