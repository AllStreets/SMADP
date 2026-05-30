from __future__ import annotations
from pathlib import Path


def is_paused(state_dir: Path) -> bool:
    return (state_dir / "PAUSED").exists()
