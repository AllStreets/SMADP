from __future__ import annotations

from pathlib import Path

from smadp.catalog.chronicle import Chronicle
from smadp.catalog.repo import CatalogRepo, NotFoundError
from smadp.config import Config


class ApproveError(RuntimeError):
    pass


def approve(*, key: str, repo_root: Path) -> None:
    pending = repo_root / "catalog" / "pending" / f"{key}.json"
    verdicts = repo_root / "catalog" / "verdicts" / f"{key}.json"
    if not pending.exists():
        raise ApproveError(f"no pending verdict at {pending}")
    verdicts.parent.mkdir(parents=True, exist_ok=True)
    try:
        pending.rename(verdicts)
    except OSError as exc:
        raise ApproveError(f"could not move {pending} -> {verdicts}: {exc}") from exc
    sentinel = repo_root / "report" / ".rebuild-requested"
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.touch()


def approve_chain(*, repo_root: Path, chain_id: str) -> None:
    """Promote a composed chain candidate (pending/chains -> catalog/chains).

    Mirrors the pairwise ``approve`` operator gate but for ``Chain`` models:
    loads the pending candidate, saves it into ``catalog/chains/``, removes the
    pending file, and records a ``chain.created`` chronicle entry by ``operator``.
    """
    config = Config(repo_root=repo_root)
    repo = CatalogRepo(config)
    try:
        chain = repo.load_pending_chain(chain_id)
    except NotFoundError as exc:
        raise ApproveError(f"no pending chain {chain_id!r}: {exc}") from exc

    repo.save_chain(chain)
    pending_path = repo.pending_chain_path(chain_id)
    try:
        pending_path.unlink()
    except OSError as exc:
        raise ApproveError(f"could not remove pending chain {pending_path}: {exc}") from exc

    Chronicle(config).record(
        "chain.created",
        by="operator",
        details={"chain_id": chain_id, "promoted": True},
    )
