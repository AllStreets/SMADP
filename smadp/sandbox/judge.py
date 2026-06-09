"""Sandbox-judge: turn a completed run's transcript into real sub-verdicts.

``promote_from_run`` historically only flipped ``evidence_level`` and appended
the run to ``sandbox_runs[]`` — every newly-sandbox-validated verdict carried
``composite_score=0.0`` + ``model.id="sandbox-seed"`` + empty rationales. This
module wires an LLM call to actually GRADE the transcript, producing real
sub-verdict severities, a real composite, and a concrete headline.

Public entry point: :func:`grade_sandbox_run`. It is best-effort: if the
LLM is unreachable or returns malformed output, the verdict is left as-is
and the caller logs a warning rather than failing the promote.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
from collections.abc import Awaitable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import structlog

from smadp.analyzer.scoring import composite_score
from smadp.catalog.repo import CatalogRepo, NotFoundError
from smadp.config import Config
from smadp.llm.client import LLMClient
from smadp.llm.prompts import sandbox_judge
from smadp.schemas.verdict import Citation, SubVerdict, SubVerdicts, Verdict, VerdictModel

log = structlog.get_logger(__name__)

_RUBRIC_RELATIVE = ("catalog", "_meta", "rubric", "1.0.json")
_SCENARIOS_DIR = ("smadp", "sandbox", "scenarios")
# Transcript bounds — the judge sees first/last N lines per agent. Keeps
# the user message under ~6k tokens even on chatty agents like Aider.
_TRANSCRIPT_HEAD_LINES = 30
_TRANSCRIPT_TAIL_LINES = 30


@dataclass(frozen=True)
class GradeResult:
    """Outcome of one judge call against one run."""

    verdict: Verdict
    composite: float
    confidence: float
    headline: str
    raw_tool_input: dict[str, Any]


class JudgeError(RuntimeError):
    pass


def _load_json_file(path: Path) -> str:
    return path.read_text("utf-8")


def _read_scenario_yaml(repo_root: Path, scenario_name: str) -> str:
    path = repo_root / Path(*_SCENARIOS_DIR) / f"{scenario_name}.yaml"
    if not path.exists():
        return json.dumps({"name": scenario_name, "note": "scenario file not found"})
    # Pass the YAML through as-is; the prompt treats it as documentation, not
    # as a parseable struct. Avoids adding a yaml dep just for this path.
    return path.read_text("utf-8")


def _load_transcript_lines(
    transcript_path: Path,
) -> list[tuple[str, str, str]]:
    """Return (agent_role, stream_kind, text) tuples from a JSONL transcript."""
    out: list[tuple[str, str, str]] = []
    if not transcript_path.exists():
        return out
    with transcript_path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            agent = str(d.get("agent") or "runner")
            # Strip the "smadp-<run_id>-" prefix the runner adds to leave
            # just the role suffix (e.g. "calendar", "email").
            if "-" in agent:
                agent = agent.rsplit("-", 1)[-1]
            kind = str(d.get("event_type") or "stdout")
            payload = d.get("payload") or {}
            text: str
            if isinstance(payload, dict) and "line" in payload:
                text = str(payload.get("line", ""))
            elif kind == "exit" and isinstance(payload, dict):
                text = f"exit code={payload.get('code')}"
            else:
                # internal/start events: keep a tiny crumb so the judge has
                # context but don't bloat the excerpt with argvs.
                text = f"<{kind}>"
            out.append((agent, kind, text))
    return out


def _profile_json_for(repo: CatalogRepo, slug: str) -> str:
    try:
        profile = repo.load_profile(slug)
    except NotFoundError:
        return json.dumps({"slug": slug, "_note": "profile not found"})
    return profile.model_dump_json(indent=2, exclude_none=True)


def _build_input(
    *,
    verdict: Verdict,
    repo: CatalogRepo,
    config: Config,
    run_row: dict[str, Any],
) -> sandbox_judge.SandboxJudgeInput:
    repo_root = config.repo_root
    rubric_path = repo_root / Path(*_RUBRIC_RELATIVE)
    rubric_json = _load_json_file(rubric_path) if rubric_path.exists() else "{}"

    slug_a, slug_b = (
        verdict.pair if verdict.pair else (verdict.participants[0], verdict.participants[1])
    )
    profile_a_json = _profile_json_for(repo, slug_a)
    profile_b_json = _profile_json_for(repo, slug_b)

    scenario_name = run_row.get("scenario", "")
    scenario_json = _read_scenario_yaml(repo_root, str(scenario_name))

    failures_raw = run_row.get("failures") or []
    if isinstance(failures_raw, str):
        try:
            failures = json.loads(failures_raw)
        except json.JSONDecodeError:
            failures = [failures_raw]
    else:
        failures = list(failures_raw) if isinstance(failures_raw, list) else []
    run_summary = {
        "run_id": run_row.get("run_id") or run_row.get("id"),
        "scenario": scenario_name,
        "outcome": run_row.get("outcome"),
        "started_at": run_row.get("started_at"),
        "completed_at": run_row.get("completed_at"),
        "exit_codes": run_row.get("exit_codes"),
        "failures": failures,
    }
    run_summary_json = sandbox_judge.serialize_run_summary(run_summary)

    transcript_path_raw = run_row.get("transcript_path")
    transcript_path = Path(transcript_path_raw) if transcript_path_raw else None
    lines: list[tuple[str, str, str]] = (
        _load_transcript_lines(transcript_path) if transcript_path else []
    )
    excerpt = sandbox_judge.build_transcript_excerpt(
        lines,
        head=_TRANSCRIPT_HEAD_LINES,
        tail=_TRANSCRIPT_TAIL_LINES,
    )

    return sandbox_judge.SandboxJudgeInput(
        rubric_json=rubric_json,
        profile_a_json=profile_a_json,
        profile_b_json=profile_b_json,
        scenario_json=scenario_json,
        run_summary_json=run_summary_json,
        transcript_excerpt=excerpt or "<empty transcript>",
    )


def _citation_from_dict(d: dict[str, Any]) -> Citation:
    # The sandbox-judge schema allows profile_field, evidence_ref,
    # transcript_line, policy_check, or quote. The Citation Pydantic model
    # only knows profile_field, evidence_ref, and quote — fold the extras
    # into `quote` so they're preserved in the saved verdict.
    quote_parts: list[str] = []
    if d.get("transcript_line"):
        quote_parts.append(f"transcript: {d['transcript_line']}")
    if d.get("policy_check"):
        quote_parts.append(f"policy: {d['policy_check']}")
    if d.get("quote"):
        quote_parts.append(str(d["quote"]))
    quote = " | ".join(quote_parts) or None
    return Citation(
        profile_field=d.get("profile_field"),
        evidence_ref=d.get("evidence_ref") or None,
        quote=quote,
    )


def _sub_from_dict(d: dict[str, Any]) -> SubVerdict:
    citations = [_citation_from_dict(c) for c in (d.get("citations") or [])]
    return SubVerdict(
        severity=d.get("severity", "none"),
        rationale=d.get("rationale", ""),
        citations=citations,
        conditions=list(d.get("conditions") or []),
        mitigations=list(d.get("mitigations") or []),
    )


def apply_judgment(verdict: Verdict, tool_input: dict[str, Any], *, model_id: str) -> Verdict:
    """Fold the LLM's tool-input into a Verdict copy with computed composite."""
    sub_payload = tool_input.get("sub_verdicts") or {}
    new_subs = SubVerdicts(
        A_prompt_injection=_sub_from_dict(sub_payload.get("A_prompt_injection") or {}),
        B_data_leakage=_sub_from_dict(sub_payload.get("B_data_leakage") or {}),
        C_capability_conflict=_sub_from_dict(sub_payload.get("C_capability_conflict") or {}),
        D_cascading_error=_sub_from_dict(sub_payload.get("D_cascading_error") or {}),
        E_compliance=_sub_from_dict(sub_payload.get("E_compliance") or {}),
    )
    composite = composite_score(new_subs)
    confidence = float(tool_input.get("confidence") or 0.0)
    headline = str(tool_input.get("headline") or "")[:240]
    framework_mappings = tool_input.get("framework_mappings") or {}
    model = VerdictModel(
        id=model_id,
        name=model_id,
        rubric_version="1.0",
    )
    return verdict.model_copy(
        update={
            "sub_verdicts": new_subs,
            "composite_score": composite,
            "confidence": confidence,
            "headline": headline,
            "framework_mappings": framework_mappings,
            "model": model,
        }
    )


_T = TypeVar("_T")


def _run_sync(coro: Awaitable[_T]) -> _T:
    """Run an async coroutine from a sync caller, even if already in a loop.

    ``promote_from_run`` is called from both the CLI (no loop) and the
    asyncio sandbox worker (loop running). ``asyncio.run()`` only works in
    the former. When a loop is already running we punt the coroutine into
    a fresh thread that owns its own loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)  # type: ignore[arg-type]
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()  # type: ignore[arg-type]


def _ensure_env_loaded(config: Config) -> None:
    """Best-effort .env autoload so the worker process sees OPENAI_API_KEY.

    The sandbox worker is launched by launchd / `smadp sandbox work`, neither
    of which sources .env automatically. Mirrors what scaffold-tick does so
    the judge call lands authed without the operator setting env per-shell.
    """
    import os

    if os.environ.get("OPENAI_API_KEY"):
        return
    env_path = config.repo_root / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text("utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def grade_sandbox_run(
    *,
    verdict: Verdict,
    config: Config,
    run_row: dict[str, Any],
    client: LLMClient | None = None,
    model: str = "gpt-5-mini",
) -> GradeResult:
    """Run the LLM judge over a completed run's transcript.

    Returns a ``GradeResult`` whose ``verdict`` is the input verdict copied
    with real sub-verdicts, composite, confidence, headline, and model.id
    set. The caller is responsible for persisting the new verdict.

    Raises :class:`JudgeError` on transport or schema failures so the
    caller can decide whether to swallow + log or propagate.
    """
    _ensure_env_loaded(config)
    # Re-instantiate Config so its openai_api_key field captures the value
    # we just loaded from .env. The Config the caller passed was frozen
    # at process start with openai_api_key=None.
    from smadp.config import Config as _Config

    llm_config = _Config() if client is None else config
    repo = CatalogRepo(config)
    payload = _build_input(verdict=verdict, repo=repo, config=config, run_row=run_row)
    llm_client = client or LLMClient(config=llm_config)
    try:
        result = _run_sync(llm_client.judge_sandbox_run(payload))
    except Exception as exc:
        raise JudgeError(f"sandbox-judge LLM call failed: {exc}") from exc

    tool_input = result.tool_input or {}
    if not isinstance(tool_input, dict) or "sub_verdicts" not in tool_input:
        raise JudgeError(f"sandbox-judge returned malformed tool input: {tool_input!r}")

    new_verdict = apply_judgment(verdict, tool_input, model_id=model)
    log.info(
        "sandbox.judge.graded",
        run_id=run_row.get("run_id") or run_row.get("id"),
        composite=new_verdict.composite_score,
        confidence=new_verdict.confidence,
    )
    return GradeResult(
        verdict=new_verdict,
        composite=new_verdict.composite_score,
        confidence=new_verdict.confidence,
        headline=new_verdict.headline,
        raw_tool_input=tool_input,
    )
