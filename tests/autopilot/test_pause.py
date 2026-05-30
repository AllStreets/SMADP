from pathlib import Path
from smadp.autopilot.pause import is_paused


def test_paused_when_sentinel_exists(tmp_path: Path) -> None:
    (tmp_path / "PAUSED").touch()
    assert is_paused(tmp_path) is True


def test_not_paused_when_sentinel_absent(tmp_path: Path) -> None:
    assert is_paused(tmp_path) is False
