"""Deterministic causal-risk computation over a hand-authored DAG.

Pure Python, no LLM, no I/O beyond loading the JSON DAG. The DAG structure is
fixed (``catalog/_meta/risk-causality.json``); per-verdict severities drive
which edges are *active*, how much each amplifies, and which mitigation has the
most downstream leverage.

The rules below are mirrored EXACTLY in ``site/src/lib/causality.ts`` — the two
implementations are kept in lockstep by identical golden tests in
``tests/unit/test_causality.py`` and ``site/tests/lib/causality.test.ts``. Any
change here must change both, or the parity tests fail.

Rules:

* SCORE: none=0.0, low=0.2, medium=0.5, high=0.8, critical=1.0 (== analyzer
  SEVERITY_SCORES).
* An edge ``src -> dst`` is ACTIVE iff ``score(src) >= 0.5`` and
  ``score(dst) > 0``.
* amplification = ``round4(score(src) * score(dst))`` when active, else 0.0.
* leverage(n) = ``round4(score(n) + sum(score(d)) for d in active-edge
  descendants of n)`` — descendants reachable following only ACTIVE edges.
* best_mitigation = the node with the greatest leverage > 0, ties broken by
  the canonical A < B < C < D < E order; ``None`` when every leverage is 0.
"""

from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Canonical risk order (also the tie-break order for best_mitigation).
RISK_IDS: tuple[str, ...] = (
    "A_prompt_injection",
    "B_data_leakage",
    "C_capability_conflict",
    "D_cascading_error",
    "E_compliance",
)

# Identical to smadp.analyzer.scoring.SEVERITY_SCORES (kept literal here so the
# TS port can match without importing the scoring module).
_SCORE: dict[str, float] = {
    "none": 0.0,
    "low": 0.2,
    "medium": 0.5,
    "high": 0.8,
    "critical": 1.0,
}

_ACTIVE_SRC_THRESHOLD = 0.5


class CausalityError(ValueError):
    """Raised for a malformed or cyclic causal DAG."""


def _round4(value: float) -> float:
    return round(value, 4)


def _score(severity: str) -> float:
    if severity not in _SCORE:
        raise CausalityError(f"unknown severity {severity!r}")
    return _SCORE[severity]


@dataclass(frozen=True)
class CausalEdge:
    src: str
    dst: str
    mechanism: str


@dataclass(frozen=True)
class CausalityDag:
    nodes: tuple[str, ...]
    edges: tuple[CausalEdge, ...]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CausalityDag:
        nodes_raw = raw.get("nodes")
        if not isinstance(nodes_raw, list) or {str(n) for n in nodes_raw} != set(RISK_IDS):
            raise CausalityError(f"DAG nodes must be exactly the risk ids {sorted(RISK_IDS)}")
        nodes = tuple(str(n) for n in nodes_raw)
        edges_raw = raw.get("edges")
        if not isinstance(edges_raw, list):
            raise CausalityError("DAG 'edges' must be a list")
        seen: set[tuple[str, str]] = set()
        edges: list[CausalEdge] = []
        node_set = set(nodes)
        for e in edges_raw:
            if not isinstance(e, dict):
                raise CausalityError("each edge must be an object")
            src = str(e.get("from", ""))
            dst = str(e.get("to", ""))
            mechanism = str(e.get("mechanism", ""))
            if src not in node_set or dst not in node_set:
                raise CausalityError(f"edge {src!r}->{dst!r} references unknown node")
            if src == dst:
                raise CausalityError(f"self-loop on node {src!r} is not allowed")
            if (src, dst) in seen:
                raise CausalityError(f"duplicate edge {src!r}->{dst!r}")
            seen.add((src, dst))
            edges.append(CausalEdge(src=src, dst=dst, mechanism=mechanism))
        dag = cls(nodes=nodes, edges=tuple(edges))
        dag._assert_acyclic()
        return dag

    def _assert_acyclic(self) -> None:
        """Kahn topological sort; raise if a cycle remains."""
        indeg: dict[str, int] = dict.fromkeys(self.nodes, 0)
        adj: dict[str, list[str]] = defaultdict(list)
        for e in self.edges:
            indeg[e.dst] += 1
            adj[e.src].append(e.dst)
        q = deque(n for n in self.nodes if indeg[n] == 0)
        visited = 0
        while q:
            n = q.popleft()
            visited += 1
            for m in adj[n]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    q.append(m)
        if visited != len(self.nodes):
            raise CausalityError("causal DAG contains a cycle")


@dataclass(frozen=True)
class EdgeAssessment:
    src: str
    dst: str
    mechanism: str
    amplification: float
    active: bool


@dataclass(frozen=True)
class CausalityReport:
    severities: dict[str, str]
    edges: tuple[EdgeAssessment, ...]
    leverage: dict[str, float]
    best_mitigation: str | None = field(default=None)

    def to_payload(self) -> dict[str, Any]:
        return {
            "severities": dict(self.severities),
            "edges": [
                {
                    "from": e.src,
                    "to": e.dst,
                    "mechanism": e.mechanism,
                    "amplification": e.amplification,
                    "active": e.active,
                }
                for e in self.edges
            ],
            "leverage": dict(self.leverage),
            "best_mitigation": self.best_mitigation,
        }


def load_causality_dag(path: Path) -> CausalityDag:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise CausalityError("risk-causality.json root must be an object")
    return CausalityDag.from_dict(raw)


def compute_causality(severities: dict[str, str], dag: CausalityDag) -> CausalityReport:
    """Assess edges, compute per-node leverage, pick the best mitigation."""
    score = {rid: _score(severities[rid]) for rid in RISK_IDS}

    edges: list[EdgeAssessment] = []
    active_adj: dict[str, list[str]] = defaultdict(list)
    for e in dag.edges:
        active = score[e.src] >= _ACTIVE_SRC_THRESHOLD and score[e.dst] > 0.0
        amplification = _round4(score[e.src] * score[e.dst]) if active else 0.0
        edges.append(
            EdgeAssessment(
                src=e.src,
                dst=e.dst,
                mechanism=e.mechanism,
                amplification=amplification,
                active=active,
            )
        )
        if active:
            active_adj[e.src].append(e.dst)

    leverage: dict[str, float] = {}
    for rid in RISK_IDS:
        descendants = _active_descendants(rid, active_adj)
        total = score[rid] + sum(score[d] for d in descendants)
        leverage[rid] = _round4(total)

    best_mitigation: str | None = None
    best_value = 0.0
    for rid in RISK_IDS:  # canonical order => deterministic tie-break
        if leverage[rid] > best_value:
            best_value = leverage[rid]
            best_mitigation = rid

    return CausalityReport(
        severities={rid: severities[rid] for rid in RISK_IDS},
        edges=tuple(edges),
        leverage=leverage,
        best_mitigation=best_mitigation,
    )


def _active_descendants(start: str, active_adj: dict[str, list[str]]) -> set[str]:
    """All nodes reachable from ``start`` via active edges (excludes start)."""
    seen: set[str] = set()
    stack = list(active_adj.get(start, ()))
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(active_adj.get(node, ()))
    return seen


__all__ = [
    "RISK_IDS",
    "CausalEdge",
    "CausalityDag",
    "CausalityError",
    "CausalityReport",
    "EdgeAssessment",
    "compute_causality",
    "load_causality_dag",
]
