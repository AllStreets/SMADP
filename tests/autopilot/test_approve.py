from pathlib import Path

import pytest

from smadp.autopilot.approve import ApproveError, approve


def test_approve_moves_pending_to_verdicts(tmp_path: Path) -> None:
    pending = tmp_path / "catalog" / "pending"
    verdicts = tmp_path / "catalog" / "verdicts"
    pending.mkdir(parents=True)
    verdicts.mkdir(parents=True)
    (pending / "alice__bob.json").write_text('{"participants": ["alice", "bob"]}')

    approve(key="alice__bob", repo_root=tmp_path)

    assert (verdicts / "alice__bob.json").exists()
    assert not (pending / "alice__bob.json").exists()


def test_approve_writes_rebuild_sentinel(tmp_path: Path) -> None:
    pending = tmp_path / "catalog" / "pending"
    verdicts = tmp_path / "catalog" / "verdicts"
    pending.mkdir(parents=True)
    verdicts.mkdir(parents=True)
    (pending / "alice__bob.json").write_text('{"participants": ["alice", "bob"]}')

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
    (pending / "alice__bob.json").write_text("{}")

    def boom(self: Path, target: Path) -> Path:
        raise OSError("simulated cross-device move")

    monkeypatch.setattr(Path, "rename", boom)
    with pytest.raises(ApproveError, match="could not move"):
        approve(key="alice__bob", repo_root=tmp_path)
