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


def test_s2_defaults_when_keys_absent(tmp_path: Path) -> None:
    cfg_file = tmp_path / "autopilot.yaml"
    cfg_file.write_text("runs_per_day: 7\n")
    cfg = load_autopilot_config(cfg_file)
    assert cfg.chain_composition_enabled is True
    assert cfg.chain_publish_confidence_threshold == 0.6
    assert cfg.chain_judge_batch_max == 10
    assert cfg.triage_enabled is True


def test_s2_nested_blocks_parsed(tmp_path: Path) -> None:
    cfg_file = tmp_path / "autopilot.yaml"
    cfg_file.write_text(
        "chain_composition:\n"
        "  enabled: false\n"
        "  publish_confidence_threshold: 0.8\n"
        "  judge_batch_max: 3\n"
        "triage:\n"
        "  enabled: false\n"
    )
    cfg = load_autopilot_config(cfg_file)
    assert cfg.chain_composition_enabled is False
    assert cfg.chain_publish_confidence_threshold == 0.8
    assert cfg.chain_judge_batch_max == 3
    assert cfg.triage_enabled is False
