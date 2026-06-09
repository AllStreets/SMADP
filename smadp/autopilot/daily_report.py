"""Generate a daily catalog briefing as ``report/YYYY-MM-DD.md``.

Modeled on the ONEXUS-Agents nightly report format. Surfaces:

  * Catalog totals (profiles, verdicts, adapters, pending) with day-over-day deltas.
  * Tier breakdown — how many profiles + verdicts sit at each evidence_level.
  * Today's sandbox runs (pass / fail).
  * Per-risk severity distribution across verdicts created today.
  * Pipeline health (queue depths, autopilot budget).

The report is regenerated end-to-end every call so it always reflects the
current state of disk. Run via ``smadp autopilot daily-report`` or have
``scripts/autopilot-loop.sh`` invoke it at the end of every tick.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CatalogStats:
    profiles: int
    profiles_by_tier: Counter[str]
    verdicts: int
    verdicts_by_tier: Counter[str]
    sandbox_validated_verdicts: int
    pending: int
    rejected: int
    adapters: int


def gather_catalog_stats(repo_root: Path) -> CatalogStats:
    catalog = repo_root / "catalog"
    profiles_dir = catalog / "profiles"
    verdicts_dir = catalog / "verdicts"

    profiles_by_tier: Counter[str] = Counter()
    if profiles_dir.exists():
        for p in profiles_dir.glob("*.json"):
            try:
                d = json.loads(p.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            profiles_by_tier[str(d.get("evidence_level") or "unknown")] += 1

    verdicts_by_tier: Counter[str] = Counter()
    sandbox_validated = 0
    if verdicts_dir.exists():
        for p in verdicts_dir.glob("*.json"):
            try:
                d = json.loads(p.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            tier = str(d.get("evidence_level") or "unknown")
            verdicts_by_tier[tier] += 1
            if tier == "sandbox-validated":
                sandbox_validated += 1

    pending = (
        len(list((catalog / "pending").glob("*.json"))) if (catalog / "pending").exists() else 0
    )
    rejected = (
        len(list((catalog / "_rejected").glob("*.json"))) if (catalog / "_rejected").exists() else 0
    )
    adapters = (
        sum(1 for p in (repo_root / "adapters").iterdir() if p.is_dir())
        if (repo_root / "adapters").exists()
        else 0
    )
    return CatalogStats(
        profiles=sum(profiles_by_tier.values()),
        profiles_by_tier=profiles_by_tier,
        verdicts=sum(verdicts_by_tier.values()),
        verdicts_by_tier=verdicts_by_tier,
        sandbox_validated_verdicts=sandbox_validated,
        pending=pending,
        rejected=rejected,
        adapters=adapters,
    )


def _chronicle_events_for(repo_root: Path, when: date) -> list[dict[str, Any]]:
    path = repo_root / "catalog" / "_chronicle" / f"{when.isoformat()}.jsonl"
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _previous_report_stats(report_dir: Path, today: date) -> tuple[int, int, int] | None:
    """Return (profiles, verdicts, adapters) from yesterday's report, if any.

    Used only for day-over-day deltas. If yesterday's report is missing or
    malformed we just emit deltas as `—`.
    """
    yesterday = today - timedelta(days=1)
    path = report_dir / f"{yesterday.isoformat()}.md"
    if not path.exists():
        return None
    profiles = verdicts = adapters = None
    for line in path.read_text("utf-8").splitlines():
        if line.startswith("- Profiles:"):
            try:
                profiles = int(line.split("**")[1].split("**")[0].replace(",", ""))
            except (IndexError, ValueError):
                continue
        elif line.startswith("- Verdicts:"):
            try:
                verdicts = int(line.split("**")[1].split("**")[0].replace(",", ""))
            except (IndexError, ValueError):
                continue
        elif line.startswith("- Adapters:"):
            try:
                adapters = int(line.split("**")[1].split("**")[0].replace(",", ""))
            except (IndexError, ValueError):
                continue
    if profiles is None or verdicts is None or adapters is None:
        return None
    return (profiles, verdicts, adapters)


def _budget_snapshot(repo_root: Path) -> dict[str, Any] | None:
    path = repo_root / "state" / "budget.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _queue_depth(repo_root: Path, name: str) -> int:
    path = repo_root / "state" / name
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def _delta(curr: int, prev: int | None) -> str:
    if prev is None:
        return "—"
    diff = curr - prev
    if diff == 0:
        return "—"
    return f"+{diff:,}" if diff > 0 else f"{diff:,}"


def render_report(
    *,
    repo_root: Path,
    today: date | None = None,
) -> str:
    today = today or datetime.now(UTC).date()
    stats = gather_catalog_stats(repo_root)
    events = _chronicle_events_for(repo_root, today)
    prev_stats = _previous_report_stats(repo_root / "report", today)
    budget = _budget_snapshot(repo_root)

    sandbox_events = [e for e in events if e.get("event") == "sandbox.run.completed"]
    sandbox_pass = sum(1 for e in sandbox_events if e.get("outcome") == "pass")
    sandbox_fail = sum(1 for e in sandbox_events if e.get("outcome") == "fail")

    # Today's new verdicts — files whose mtime falls on `today`. Cheap proxy
    # since the chronicle only logs sandbox events, not docs-only judge runs.
    verdicts_dir = repo_root / "catalog" / "verdicts"
    today_severities: Counter[str] = Counter()
    new_verdicts_today = 0
    if verdicts_dir.exists():
        cutoff = datetime.combine(today, datetime.min.time(), tzinfo=UTC)
        for p in verdicts_dir.glob("*.json"):
            try:
                stat = p.stat()
            except OSError:
                continue
            if datetime.fromtimestamp(stat.st_mtime, tz=UTC) < cutoff:
                continue
            new_verdicts_today += 1
            try:
                d = json.loads(p.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            subs = d.get("sub_verdicts") or {}
            for risk in (
                "A_prompt_injection",
                "B_data_leakage",
                "C_capability_conflict",
                "D_cascading_error",
                "E_compliance",
            ):
                today_severities[(subs.get(risk) or {}).get("severity") or "none"] += 1

    lines: list[str] = []
    lines.append(f"# Catalog briefing — {today.isoformat()}")
    lines.append("")

    # Headline numbers
    lines.append("## Totals")
    delta_p = _delta(stats.profiles, prev_stats[0] if prev_stats else None)
    delta_v = _delta(stats.verdicts, prev_stats[1] if prev_stats else None)
    delta_a = _delta(stats.adapters, prev_stats[2] if prev_stats else None)
    lines.append(f"- Profiles: **{stats.profiles:,}** ({delta_p})")
    lines.append(f"- Verdicts: **{stats.verdicts:,}** ({delta_v})")
    lines.append(f"- Adapters: **{stats.adapters:,}** ({delta_a})")
    lines.append(f"- Pending review: **{stats.pending}**")
    lines.append(f"- Sandbox-validated verdicts: **{stats.sandbox_validated_verdicts}**")
    if stats.rejected:
        lines.append(f"- Rejected (preserved): **{stats.rejected}**")
    lines.append("")

    # Per-tier breakdown
    lines.append("## Tier breakdown")
    lines.append("")
    lines.append("| Tier | Profiles | Verdicts |")
    lines.append("|---|---:|---:|")
    for tier in (
        "sandbox-validated",
        "profile-verified",
        "docs-only",
        "unverified-profile",
    ):
        p_count = stats.profiles_by_tier.get(tier, 0)
        v_count = stats.verdicts_by_tier.get(tier, 0)
        if p_count or v_count:
            lines.append(f"| `{tier}` | {p_count:,} | {v_count:,} |")
    lines.append("")

    # Today's activity
    lines.append("## Activity today (UTC)")
    lines.append(f"- New verdicts created: **{new_verdicts_today:,}**")
    lines.append(f"- Sandbox runs (pass / fail): **{sandbox_pass} / {sandbox_fail}**")
    if budget:
        lines.append(
            f"- Autopilot budget: **{budget.get('runs_today', 0)}** runs · "
            f"**${budget.get('dollars_today', 0.0):.2f}** spent"
        )
    lines.append("")

    # Severity distribution across new verdicts
    if today_severities:
        lines.append("## Severity distribution · new verdicts today")
        lines.append("")
        lines.append("| Severity | Sub-verdicts |")
        lines.append("|---|---:|")
        for sev in ("none", "low", "medium", "high", "critical"):
            count = today_severities.get(sev, 0)
            if count:
                lines.append(f"| `{sev}` | {count} |")
        lines.append("")

    # Pipeline health
    lines.append("## Pipeline health")
    lines.append(
        f"- Docs-only queue depth: **{_queue_depth(repo_root, 'docs_only_queue.jsonl'):,}**"
    )
    lines.append(
        f"- Scaffold-tick attempted: **{_queue_depth(repo_root, 'scaffold_tick.jsonl'):,}** total"
    )
    pending_now = stats.pending
    if pending_now:
        lines.append(f"- Operator queue: **{pending_now}** verdict(s) awaiting review")
    judge_errors = repo_root / "state" / "judge_errors.jsonl"
    if judge_errors.exists():
        count = sum(1 for _ in judge_errors.open("r", encoding="utf-8"))
        if count:
            lines.append(f"- Judge errors logged (lifetime): **{count:,}**")
    lines.append("")

    lines.append("---")
    lines.append(f"*generated {datetime.now(UTC).isoformat(timespec='seconds')}*")
    lines.append("")
    return "\n".join(lines)


def write_report(*, repo_root: Path, today: date | None = None) -> Path:
    today = today or datetime.now(UTC).date()
    report_dir = repo_root / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{today.isoformat()}.md"
    path.write_text(render_report(repo_root=repo_root, today=today), encoding="utf-8")
    return path
