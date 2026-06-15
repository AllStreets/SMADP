"""The proxy CLI group is registered and synthesize stages into _unverified/."""
from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from smadp.cli import cli
from smadp.proxy.recorder import RecordingSession


def test_proxy_group_registered() -> None:
    assert "proxy" in cli.commands
    sub = cli.commands["proxy"].commands  # type: ignore[attr-defined]
    assert {"record", "synthesize"} <= set(sub)


def test_synthesize_stages_behavior_observed_into_unverified(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path
    catalog = repo / "catalog"
    evidence_dir = catalog / "_evidence"
    (catalog / "profiles" / "_unverified").mkdir(parents=True)
    evidence_dir.mkdir(parents=True)

    session = RecordingSession(slug="acme", evidence_dir=evidence_dir)
    session.observe(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "read_file", "arguments": {"path": "/etc/hosts"}},
        },
        direction="c2s",
    )
    rec = session.finalize()

    monkeypatch.setenv("SMADP_REPO_ROOT", str(repo))
    monkeypatch.chdir(repo)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "proxy",
            "synthesize",
            "--slug",
            "acme",
            "--name",
            "Acme",
            "--recording",
            f"sha256:{rec.sha256}",
        ],
    )
    assert result.exit_code == 0, result.output
    staged = catalog / "profiles" / "_unverified" / "acme.json"
    assert staged.exists()
    data = json.loads(staged.read_text("utf-8"))
    assert data["evidence_level"] == "behavior-observed"
    assert "read_file" in data["onexus"]["behavior"]["observed_tools"]
    # never wrote a published profile
    assert not (catalog / "profiles" / "acme.json").exists()
