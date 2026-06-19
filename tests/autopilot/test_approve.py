from pathlib import Path

import pytest

from smadp.autopilot.approve import ApproveError, approve
from tests.autopilot._verdict_factory import valid_verdict_json


def test_approve_moves_pending_to_verdicts(tmp_path: Path) -> None:
    pending = tmp_path / "catalog" / "pending"
    verdicts = tmp_path / "catalog" / "verdicts"
    pending.mkdir(parents=True)
    verdicts.mkdir(parents=True)
    (pending / "alice__bob.json").write_text(valid_verdict_json("alice", "bob"))

    approve(key="alice__bob", repo_root=tmp_path)

    assert (verdicts / "alice__bob.json").exists()
    assert not (pending / "alice__bob.json").exists()


def test_approve_writes_rebuild_sentinel(tmp_path: Path) -> None:
    pending = tmp_path / "catalog" / "pending"
    verdicts = tmp_path / "catalog" / "verdicts"
    pending.mkdir(parents=True)
    verdicts.mkdir(parents=True)
    (pending / "alice__bob.json").write_text(valid_verdict_json("alice", "bob"))

    approve(key="alice__bob", repo_root=tmp_path)

    assert (tmp_path / "report" / ".rebuild-requested").exists()


def test_approve_errors_on_missing_pending(tmp_path: Path) -> None:
    (tmp_path / "catalog" / "pending").mkdir(parents=True)
    (tmp_path / "catalog" / "verdicts").mkdir(parents=True)
    with pytest.raises(ApproveError, match="no pending verdict"):
        approve(key="alice__bob", repo_root=tmp_path)


def test_approve_wraps_rename_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pending = tmp_path / "catalog" / "pending"
    verdicts = tmp_path / "catalog" / "verdicts"
    pending.mkdir(parents=True)
    verdicts.mkdir(parents=True)
    (pending / "alice__bob.json").write_text(valid_verdict_json("alice", "bob"))

    def boom(self: Path, target: Path) -> Path:
        raise OSError("simulated cross-device move")

    monkeypatch.setattr(Path, "rename", boom)
    with pytest.raises(ApproveError, match="could not move"):
        approve(key="alice__bob", repo_root=tmp_path)


def test_approve_rejects_schema_invalid_verdict(tmp_path: Path) -> None:
    """The gate must NOT publish a verdict that fails Verdict-schema validation."""
    from smadp.autopilot.pending import PendingValidationError, approve_one

    pending = tmp_path / "catalog" / "pending"
    verdicts = tmp_path / "catalog" / "verdicts"
    pending.mkdir(parents=True)
    verdicts.mkdir(parents=True)
    (pending / "alice__bob.json").write_text('{"participants": ["alice", "bob"]}')

    with pytest.raises(PendingValidationError):
        approve_one(key="alice__bob", repo_root=tmp_path)
    # Left in pending, never published.
    assert (pending / "alice__bob.json").exists()
    assert not (verdicts / "alice__bob.json").exists()


def test_approve_batch_skips_invalid_keeps_valid(tmp_path: Path) -> None:
    from smadp.autopilot.pending import approve_batch

    pending = tmp_path / "catalog" / "pending"
    verdicts = tmp_path / "catalog" / "verdicts"
    pending.mkdir(parents=True)
    verdicts.mkdir(parents=True)
    (pending / "alice__bob.json").write_text(valid_verdict_json("alice", "bob"))
    (pending / "carol__dave.json").write_text('{"corrupt": true}')

    moved = approve_batch(repo_root=tmp_path, keys=["alice__bob", "carol__dave"])

    assert len(moved) == 1
    assert (verdicts / "alice__bob.json").exists()
    # Invalid one is skipped, not published, and stays in pending for re-judging.
    assert not (verdicts / "carol__dave.json").exists()
    assert (pending / "carol__dave.json").exists()
