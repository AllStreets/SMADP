from pathlib import Path
from smadp.autopilot.config import load_autopilot_config


def test_loads_caps(tmp_path: Path) -> None:
    cfg_file = tmp_path / "autopilot.yaml"
    cfg_file.write_text("runs_per_day: 7\ndollars_per_day: 3.50\n")
    cfg = load_autopilot_config(cfg_file)
    assert cfg.runs_per_day == 7
    assert cfg.dollars_per_day == 3.50


def test_defaults_when_file_missing(tmp_path: Path) -> None:
    cfg = load_autopilot_config(tmp_path / "missing.yaml")
    assert cfg.runs_per_day == 10
    assert cfg.dollars_per_day == 5.0
