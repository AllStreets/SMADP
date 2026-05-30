from __future__ import annotations
from pathlib import Path


class ApproveError(RuntimeError):
    pass


def approve(*, key: str, repo_root: Path) -> None:
    pending = repo_root / "catalog" / "pending" / f"{key}.json"
    verdicts = repo_root / "catalog" / "verdicts" / f"{key}.json"
    if not pending.exists():
        raise ApproveError(f"no pending verdict at {pending}")
    verdicts.parent.mkdir(parents=True, exist_ok=True)
    pending.rename(verdicts)
    sentinel = repo_root / "report" / ".rebuild-requested"
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.touch()
