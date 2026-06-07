"""Load and validate sandbox scenario YAML files.

Scenario YAML schema (v1)::

    name: string                       # filename-stem; must match the file
    description: string
    timeout_s: int                     # 1..1800
    agents:
      <role>:
        adapter: string | null         # adapter slug or null (filled at submit)
        role: string                   # human description for the prompt
        initial_prompt: string         # what the agent is asked to do
    shared_workspace:
      type: tmpfs                      # only 'tmpfs' supported in v1
      files: list[string]              # paths to be created (empty) at start
    allow_egress: list[string]         # FQDNs; usually empty
    synthetic_secrets:                 # list of single-key mappings
      - SMADP_TEST_FOO: "synthetic-..."
    assertions:                        # rubric — each entry has 'type' + params
      - type: no_network_egress_outside_allowlist
      - type: no_secret_in_transcript
        secret_pattern: "SMADP_TEST_*"
      - type: file_handoff_succeeded
        path: /work/scratchpad.md
      - type: both_agents_exited_zero
      - type: no_policy_violations

Validation rules:

* Two to four agents per scenario.
* Every synthetic-secret value must pass ``policy.is_safe_secret``.
* Every egress endpoint must pass ``policy.validate_egress_endpoint``.
* All assertion types must be in :data:`SUPPORTED_ASSERTIONS`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import yaml

from smadp.sandbox.policy import (
    PolicyError,
    is_safe_secret,
    validate_egress_endpoint,
)

KNOWN_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        "execute_shell",
        "read_filesystem",
        "write_filesystem",
        "network_egress",
        "spawn_subprocesses",
        "use_mcp",
        "modify_git_state",
        "install_packages",
        "run_browsers",
    }
)

SUPPORTED_ASSERTIONS: Final[frozenset[str]] = frozenset(
    {
        "no_network_egress_outside_allowlist",
        "no_secret_in_transcript",
        "file_handoff_succeeded",
        "both_agents_exited_zero",
        "no_policy_violations",
        "transcript_contains",
        "transcript_does_not_contain",
    }
)


class ScenarioLoadError(Exception):
    """Raised when a scenario YAML fails to parse or validate."""


@dataclass(frozen=True)
class AgentRole:
    """One agent in a 2-to-4-agent scenario."""

    role_key: str  # e.g. "calendar"
    adapter: str | None  # adapter slug (kept for back-compat; binding uses required_capabilities)
    role: str  # human-readable role description
    initial_prompt: str  # task prompt handed to the agent
    required_capabilities: tuple[str, ...]  # non-empty; capabilities the adapter must satisfy


@dataclass(frozen=True)
class Assertion:
    """A typed rubric assertion evaluated against the transcript."""

    type: str
    params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Scenario:
    """A fully-validated scenario definition."""

    name: str
    description: str
    timeout_s: int
    agents: tuple[AgentRole, ...]
    shared_workspace_files: tuple[str, ...]
    allow_egress: tuple[str, ...]
    synthetic_secrets: Mapping[str, str]
    assertions: tuple[Assertion, ...]
    source_path: Path | None = None

    def agent_by_role(self, role_key: str) -> AgentRole:
        for agent in self.agents:
            if agent.role_key == role_key:
                return agent
        raise KeyError(f"No agent role {role_key!r} in scenario {self.name!r}")


# ---------------------------------------------------------------------------
# Loader entry points
# ---------------------------------------------------------------------------


_BUILTIN_DIR = Path(__file__).resolve().parent


def list_builtin_scenarios() -> list[str]:
    """Return scenario names (filename stems) shipped with the package."""
    return sorted(p.stem for p in _BUILTIN_DIR.glob("*.yaml"))


def load_scenario(name: str) -> Scenario:
    """Load a built-in scenario by name (filename stem)."""
    path = _BUILTIN_DIR / f"{name}.yaml"
    if not path.exists():
        raise ScenarioLoadError(
            f"No built-in scenario named {name!r}. Available: {list_builtin_scenarios()}"
        )
    return load_scenario_from_path(path)


def load_scenario_from_path(path: Path) -> Scenario:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ScenarioLoadError(f"YAML parse error in {path}: {e}") from e
    if not isinstance(raw, Mapping):
        raise ScenarioLoadError(f"Scenario {path} root must be a mapping")
    return _validate(dict(raw), source_path=path)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _require(d: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise ScenarioLoadError(f"Missing required key {key!r} in {where}")
    return d[key]


def _validate(raw: dict[str, Any], source_path: Path) -> Scenario:
    name = str(_require(raw, "name", "scenario root"))
    if source_path.stem != name:
        raise ScenarioLoadError(
            f"Scenario name {name!r} must match filename stem {source_path.stem!r}"
        )

    description = str(_require(raw, "description", "scenario root"))
    timeout_s = int(_require(raw, "timeout_s", "scenario root"))
    if not 1 <= timeout_s <= 1800:
        raise ScenarioLoadError(f"timeout_s must be in [1, 1800], got {timeout_s}")

    agents_raw = _require(raw, "agents", "scenario root")
    if not isinstance(agents_raw, Mapping) or not (2 <= len(agents_raw) <= 4):
        raise ScenarioLoadError("scenario.agents must be a mapping of 2 to 4 entries")
    agents = tuple(_validate_agent(k, v) for k, v in agents_raw.items())

    workspace_raw = _require(raw, "shared_workspace", "scenario root")
    if not isinstance(workspace_raw, Mapping):
        raise ScenarioLoadError("shared_workspace must be a mapping")
    if workspace_raw.get("type") != "tmpfs":
        raise ScenarioLoadError("shared_workspace.type must be 'tmpfs' (only type supported in v1)")
    files_raw = workspace_raw.get("files", [])
    if not isinstance(files_raw, list) or not all(isinstance(f, str) for f in files_raw):
        raise ScenarioLoadError("shared_workspace.files must be a list of strings")
    files = tuple(files_raw)

    egress_raw = raw.get("allow_egress", []) or []
    if not isinstance(egress_raw, list):
        raise ScenarioLoadError("allow_egress must be a list")
    for endpoint in egress_raw:
        if not isinstance(endpoint, str) or not validate_egress_endpoint(endpoint):
            raise ScenarioLoadError(f"Invalid egress endpoint: {endpoint!r}")
    egress = tuple(egress_raw)

    secrets = _validate_secrets(raw.get("synthetic_secrets", []) or [])
    assertions = _validate_assertions(raw.get("assertions", []) or [])

    return Scenario(
        name=name,
        description=description,
        timeout_s=timeout_s,
        agents=agents,
        shared_workspace_files=files,
        allow_egress=egress,
        synthetic_secrets=secrets,
        assertions=assertions,
        source_path=source_path,
    )


def _validate_agent(role_key: str, raw: Any) -> AgentRole:
    if not isinstance(raw, Mapping):
        raise ScenarioLoadError(f"agents.{role_key} must be a mapping")
    adapter = raw.get("adapter")
    if adapter is not None and not isinstance(adapter, str):
        raise ScenarioLoadError(f"agents.{role_key}.adapter must be string or null")
    role = raw.get("role")
    initial_prompt = raw.get("initial_prompt")
    if not isinstance(role, str) or not role.strip():
        raise ScenarioLoadError(f"agents.{role_key}.role must be a non-empty string")
    if not isinstance(initial_prompt, str) or not initial_prompt.strip():
        raise ScenarioLoadError(f"agents.{role_key}.initial_prompt must be a non-empty string")

    caps_raw = raw.get("required_capabilities", [])
    if not isinstance(caps_raw, list) or not all(isinstance(c, str) for c in caps_raw):
        raise ScenarioLoadError(
            f"agents.{role_key}.required_capabilities must be a list of strings"
        )
    if not caps_raw:
        raise ScenarioLoadError(f"agents.{role_key}.required_capabilities must be a non-empty list")
    unknown = [c for c in caps_raw if c not in KNOWN_CAPABILITIES]
    if unknown:
        raise ScenarioLoadError(
            f"agents.{role_key}.required_capabilities contains unknown capability "
            f"names {unknown!r}; allowed: {sorted(KNOWN_CAPABILITIES)}"
        )
    seen: set[str] = set()
    dupes: list[str] = []
    for c in caps_raw:
        if c in seen:
            dupes.append(c)
        seen.add(c)
    if dupes:
        raise ScenarioLoadError(
            f"agents.{role_key}.required_capabilities contains duplicate values: {dupes!r}"
        )

    return AgentRole(
        role_key=role_key,
        adapter=adapter,
        role=role.strip(),
        initial_prompt=initial_prompt.strip(),
        required_capabilities=tuple(caps_raw),
    )


def _validate_secrets(raw: Any) -> dict[str, str]:
    if not isinstance(raw, list):
        raise ScenarioLoadError("synthetic_secrets must be a list of single-key mappings")
    out: dict[str, str] = {}
    for entry in raw:
        if not isinstance(entry, Mapping) or len(entry) != 1:
            raise ScenarioLoadError("Each synthetic_secrets entry must be a single-key mapping")
        ((key, value),) = entry.items()
        if not isinstance(key, str) or not isinstance(value, str):
            raise ScenarioLoadError("synthetic_secrets keys/values must be strings")
        if not is_safe_secret(value):
            raise ScenarioLoadError(
                f"Synthetic secret {key!r} value rejected by policy. "
                "Use SMADP_TEST_* or synthetic-test-only-* prefixes."
            )
        out[key] = value
    return out


def _validate_assertions(raw: Any) -> tuple[Assertion, ...]:
    if not isinstance(raw, list):
        raise ScenarioLoadError("assertions must be a list")
    out: list[Assertion] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            raise ScenarioLoadError("each assertion must be a mapping with a 'type' key")
        a_type = entry.get("type")
        if not isinstance(a_type, str) or a_type not in SUPPORTED_ASSERTIONS:
            raise ScenarioLoadError(
                f"Unsupported assertion type {a_type!r}. Supported: {sorted(SUPPORTED_ASSERTIONS)}"
            )
        params = {k: v for k, v in entry.items() if k != "type"}
        out.append(Assertion(type=a_type, params=params))
    return tuple(out)


def assert_secrets_safe(values: Iterable[str]) -> None:
    """Raise if any of ``values`` is unsafe (defense in depth)."""
    bad = [v for v in values if not is_safe_secret(v)]
    if bad:
        raise PolicyError(f"Unsafe secret values rejected: {bad}")


__all__ = [
    "KNOWN_CAPABILITIES",
    "SUPPORTED_ASSERTIONS",
    "AgentRole",
    "Assertion",
    "Scenario",
    "ScenarioLoadError",
    "assert_secrets_safe",
    "list_builtin_scenarios",
    "load_scenario",
    "load_scenario_from_path",
]
