"""API: WS run event stream (transcript tail) + operator-gated halt endpoint."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smadp.api.server import create_app
from smadp.config import Config
from smadp.sandbox import queue
from smadp.sandbox.runner import transcript_path_for
from smadp.sandbox.transcripts import TranscriptWriter

TOKEN = "operator-secret"


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    catalog = tmp_path / "catalog"
    cache = tmp_path / "cache"
    catalog.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    # Seed the two profiles the queue/route validate against.
    import shutil

    seed = Path(__file__).resolve().parents[2] / "catalog"
    shutil.copytree(seed, catalog, dirs_exist_ok=True)
    monkeypatch.setenv("SMADP_CATALOG", str(catalog))
    monkeypatch.setenv("SMADP_CACHE_DIR", str(cache))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


def _completed_run(cfg: Config) -> str:
    run_id = queue.enqueue_sandbox_run(
        slug_a="aider", slug_b="continue-dev", scenario="calendar_email", config=cfg
    )
    path = transcript_path_for(run_id, config=cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = TranscriptWriter(path)
    writer.emit(
        agent=f"smadp-{run_id}-calendar",
        event_type="stdout",
        direction="agent_to_env",
        payload={"line": "hello from calendar"},
    )
    writer.emit(
        agent=f"smadp-{run_id}-email",
        event_type="exit",
        direction="internal",
        payload={"code": 0},
    )
    writer.close()
    queue.mark_completed(run_id, outcome="pass", transcript_path=str(path), config=cfg)
    return run_id


def test_ws_stream_replays_then_terminal_frame(env: Config) -> None:
    cfg = env
    run_id = _completed_run(cfg)
    client = TestClient(create_app(cfg))
    frames = []
    with client.websocket_connect(f"/api/sandbox/runs/{run_id}/stream") as ws:
        while True:
            frame = ws.receive_json()
            frames.append(frame)
            if frame.get("kind") == "lifecycle" and frame.get("payload", {}).get("state"):
                break

    kinds = [f["kind"] for f in frames]
    assert "agent_output" in kinds
    # last frame is the terminal lifecycle frame carrying state + outcome.
    terminal = frames[-1]
    assert terminal["kind"] == "lifecycle"
    assert terminal["payload"]["state"] in {"completed", "failed"}
    assert terminal["payload"]["outcome"] == "pass"


def test_halt_503_without_token(env: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = env
    run_id = queue.enqueue_sandbox_run(
        slug_a="aider", slug_b="continue-dev", scenario="calendar_email", config=cfg
    )
    monkeypatch.delenv("SMADP_API_TOKEN", raising=False)
    client = TestClient(create_app(cfg))
    r = client.post(f"/api/sandbox/runs/{run_id}/halt")
    assert r.status_code == 503


def test_halt_401_with_wrong_token(env: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = env
    run_id = queue.enqueue_sandbox_run(
        slug_a="aider", slug_b="continue-dev", scenario="calendar_email", config=cfg
    )
    monkeypatch.setenv("SMADP_API_TOKEN", TOKEN)
    client = TestClient(create_app(cfg))
    r = client.post(
        f"/api/sandbox/runs/{run_id}/halt",
        headers={"Authorization": "Bearer nope"},
    )
    assert r.status_code == 401


def test_halt_202_with_token_sets_flag(env: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = env
    run_id = queue.enqueue_sandbox_run(
        slug_a="aider", slug_b="continue-dev", scenario="calendar_email", config=cfg
    )
    monkeypatch.setenv("SMADP_API_TOKEN", TOKEN)
    client = TestClient(create_app(cfg))
    r = client.post(
        f"/api/sandbox/runs/{run_id}/halt",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert r.status_code == 202
    assert r.json() == {"run_id": run_id, "halt_requested": True}
    row = queue.get_raw_row(run_id, config=cfg)
    assert row is not None and row["halt_requested"] == 1


def test_halt_409_on_terminal_run(env: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = env
    run_id = _completed_run(cfg)
    monkeypatch.setenv("SMADP_API_TOKEN", TOKEN)
    client = TestClient(create_app(cfg))
    r = client.post(
        f"/api/sandbox/runs/{run_id}/halt",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert r.status_code == 409


def test_halt_404_on_unknown_run(env: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = env
    monkeypatch.setenv("SMADP_API_TOKEN", TOKEN)
    client = TestClient(create_app(cfg))
    r = client.post(
        "/api/sandbox/runs/no-such-run/halt",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert r.status_code == 404
