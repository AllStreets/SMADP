"""Read `~/.smadp/keys.env` and decide which keys each adapter container gets.

The worker is the only caller. Keys NEVER enter the queue DB, the transcript,
or any chronicle event. The allowlist is hardcoded so a typo in keys.env
cannot accidentally exfiltrate a token to an unrelated env var.
"""

from __future__ import annotations

import logging
import stat
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Final

log = logging.getLogger(__name__)

KEY_ALLOWLIST: Final[frozenset[str]] = frozenset({"OPENAI_API_KEY"})


def default_keys_path() -> Path:
    return Path.home() / ".smadp" / "keys.env"


def load_keys_file(path: Path) -> dict[str, str]:
    """Parse a `.env`-style file. Returns {} if the file does not exist."""
    if not path.exists():
        return {}
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:  # any group/world bits set
        log.warning(
            "sandbox.keys.permissive_mode path=%s mode=%04o (recommend 0600)",
            path,
            mode,
        )
    out: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and ((value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")):
            value = value[1:-1]
        if not key:
            continue
        out[key] = value
    return out


def filter_to_allowlist(loaded: Mapping[str, str]) -> dict[str, str]:
    """Drop any key not in :data:`KEY_ALLOWLIST`."""
    return {k: v for k, v in loaded.items() if k in KEY_ALLOWLIST}


def compute_env_for_adapter(
    loaded: Mapping[str, str],
    *,
    env_required: Iterable[str],
    env_optional: Iterable[str],
) -> tuple[dict[str, str], list[str]]:
    """Return (env_to_inject, missing_required_keys).

    ``loaded`` should already be filtered to the allowlist (call
    :func:`filter_to_allowlist` first), but this function tolerates extras —
    it only ever returns keys explicitly listed in env_required or env_optional.
    """
    requested = set(env_required) | set(env_optional)
    safe = filter_to_allowlist(loaded)
    available = {k: v for k, v in safe.items() if k in requested}
    missing = sorted(set(env_required) - safe.keys())
    return available, missing


__all__ = [
    "KEY_ALLOWLIST",
    "compute_env_for_adapter",
    "default_keys_path",
    "filter_to_allowlist",
    "load_keys_file",
]
