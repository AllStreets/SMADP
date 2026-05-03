"""Validate that a Profile's citations resolve and quotes appear at source.

For each evidence sha referenced in ``profile.evidence_refs``:

1. Confirm the evidence file exists in the catalog.
2. Re-fetch the evidence's ``source_url``.
3. Confirm the evidence's ``quote`` substring still appears verbatim in the
   re-fetched body. (Whitespace is normalized for comparison so that minor
   reformatting upstream does not produce false negatives.)

A separate scan flags fields that the spec marks as "requires evidence" but
which are populated without a single supporting evidence ref. This is a
heuristic — the model is supposed to enforce per-field citations in its
prompt, but we double-check at the profile level because the schema allows
any sha to underwrite any field.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import structlog

from smadp.profiler.fetcher import DEFAULT_TIMEOUT_SECONDS, DEFAULT_USER_AGENT
from smadp.schemas.evidence import Evidence
from smadp.schemas.profile import Profile

logger = structlog.get_logger(__name__)

EVIDENCE_FILENAME_TEMPLATE = "sha256-{sha}.json"
_EVIDENCE_PREFIX = "sha256:"
_WS_RE = re.compile(r"\s+")


@dataclass
class CitationReport:
    """Outcome of citation validation against a single Profile."""

    valid: bool
    issues: list[str] = field(default_factory=list)
    fields_missing_evidence: list[str] = field(default_factory=list)


def _fields_with_signal(profile: Profile) -> list[str]:
    """Return names of fields that carry a non-default 'signal' worth citing."""
    signals: list[str] = []
    caps = profile.capabilities
    for attr, default in (
        ("execute_shell", False),
        ("read_filesystem", False),
        ("write_filesystem", False),
        ("spawn_subprocesses", False),
        ("use_mcp", False),
        ("modify_git_state", False),
        ("install_packages", False),
        ("run_browsers", False),
    ):
        if getattr(caps, attr) != default:
            signals.append(f"capabilities.{attr}")
    if caps.network_egress != "none":
        signals.append("capabilities.network_egress")

    io = profile.io_surfaces
    if io.stdin_stdout:
        signals.append("io_surfaces.stdin_stdout")
    if io.clipboard:
        signals.append("io_surfaces.clipboard")
    if io.screen_capture:
        signals.append("io_surfaces.screen_capture")
    if io.audio:
        signals.append("io_surfaces.audio")
    if io.files:
        signals.append("io_surfaces.files")
    if io.calls_apis:
        signals.append("io_surfaces.calls_apis")

    perms = profile.permissions_requested
    if perms.oauth_scopes:
        signals.append("permissions_requested.oauth_scopes")
    if perms.secrets_handled:
        signals.append("permissions_requested.secrets_handled")
    if perms.elevated_privileges:
        signals.append("permissions_requested.elevated_privileges")

    if profile.data_classes_touched:
        signals.append("data_classes_touched")

    sb = profile.sandboxing
    if sb.self_isolation:
        signals.append("sandboxing.self_isolation")
    if sb.subagent_model:
        signals.append("sandboxing.subagent_model")
    if sb.tool_use_pattern:
        signals.append("sandboxing.tool_use_pattern")

    cm = profile.concurrency_model
    if cm.session_scope:
        signals.append("concurrency_model.session_scope")
    if cm.shared_state_with_other_instances:
        signals.append("concurrency_model.shared_state_with_other_instances")
    if cm.supports_multiple_instances:
        signals.append("concurrency_model.supports_multiple_instances")
    return signals


def _normalize_for_match(text: str) -> str:
    return _WS_RE.sub(" ", text).strip().lower()


def _evidence_path(evidence_dir: Path, sha: str) -> Path:
    return evidence_dir / EVIDENCE_FILENAME_TEMPLATE.format(sha=sha)


def _load_evidence(evidence_dir: Path, sha: str) -> Evidence | None:
    path = _evidence_path(evidence_dir, sha)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("citations.load_failed", sha=sha, error=str(exc))
        return None
    try:
        return Evidence.model_validate(payload)
    except Exception as exc:  # noqa: BLE001 - pydantic ValidationError surfaces here
        logger.warning("citations.invalid_evidence_file", sha=sha, error=str(exc))
        return None


def validate_citations(
    profile: Profile,
    evidence_dir: Path,
    *,
    refetch: bool = True,
    client: httpx.AsyncClient | None = None,
) -> CitationReport:
    """Validate every evidence_ref on ``profile``; optionally re-fetch sources.

    Args:
        profile: The Profile under test.
        evidence_dir: Directory containing ``sha256-<hash>.json`` files.
        refetch: If True (default), perform live HTTP re-fetches and verify
            quotes still appear at source. If False, only verify local
            evidence files exist and parse.
        client: Optional pre-built httpx client (the function manages its own
            otherwise).

    Returns:
        A :class:`CitationReport`.
    """
    issues: list[str] = []
    refs = list(dict.fromkeys(profile.evidence_refs))  # de-dup, preserve order
    evidences: dict[str, Evidence] = {}
    for ref in refs:
        if not ref.startswith(_EVIDENCE_PREFIX):
            issues.append(f"evidence_ref {ref!r} is not in sha256: form")
            continue
        sha = ref[len(_EVIDENCE_PREFIX) :]
        loaded = _load_evidence(evidence_dir, sha)
        if loaded is None:
            issues.append(f"evidence file missing or invalid for {ref}")
            continue
        if loaded.sha256 != sha:
            issues.append(f"evidence file at {ref} has mismatched sha {loaded.sha256!r}")
            continue
        evidences[sha] = loaded

    if refetch and evidences:
        try:
            asyncio.get_running_loop()
            running_in_loop = True
        except RuntimeError:
            running_in_loop = False
        if running_in_loop:
            issues.append(
                "validate_citations cannot re-fetch from inside a running event loop "
                "(call from a thread or pass refetch=False)."
            )
        else:
            refetch_issues = asyncio.run(_refetch_and_verify(evidences, client=client))
            issues.extend(refetch_issues)

    fields_missing = _fields_with_signal(profile) if not profile.evidence_refs else []
    valid = not issues and not fields_missing
    return CitationReport(
        valid=valid,
        issues=issues,
        fields_missing_evidence=fields_missing,
    )


async def _refetch_and_verify(
    evidences: dict[str, Evidence],
    *,
    client: httpx.AsyncClient | None,
) -> list[str]:
    """Re-fetch each evidence's source and verify its quote still appears."""
    issues: list[str] = []
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "*/*"},
            timeout=DEFAULT_TIMEOUT_SECONDS,
            follow_redirects=True,
        )
    try:
        # De-duplicate by URL so we make at most one request per source.
        urls: dict[str, list[Evidence]] = {}
        for ev in evidences.values():
            urls.setdefault(str(ev.source_url), []).append(ev)
        results = await asyncio.gather(
            *(client.get(url) for url in urls),
            return_exceptions=True,
        )
        for (url, evs), result in zip(urls.items(), results, strict=True):
            if isinstance(result, BaseException):
                for ev in evs:
                    issues.append(
                        f"refetch failed for sha256:{ev.sha256} ({url}): {result}"
                    )
                continue
            try:
                result.raise_for_status()
            except httpx.HTTPStatusError as exc:
                for ev in evs:
                    issues.append(
                        f"refetch HTTP {exc.response.status_code} for sha256:{ev.sha256} ({url})"
                    )
                continue
            body_norm = _normalize_for_match(result.text)
            for ev in evs:
                if _normalize_for_match(ev.quote) not in body_norm:
                    issues.append(
                        f"quote for sha256:{ev.sha256} no longer appears at {url}"
                    )
    finally:
        if owns_client:
            await client.aclose()
    return issues
