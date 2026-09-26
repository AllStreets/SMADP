"""Pre-flight policy enforcement for the Sandbox Validator.

This module is the *gatekeeper* between user input / scenario YAML and the
container runtime. Everything here is intentionally conservative: a false
positive (rejecting a legitimate input) is acceptable; a false negative
(letting a real secret or an unpinned image through) is not.

Two responsibilities:

1. **Secret hygiene** — reject any string that pattern-matches a real-world
   API key. Sandbox scenarios are only allowed *synthetic* secrets whose value
   is prefixed with ``SMADP_TEST_`` or ``synthetic-test-only-``. This is a
   defense-in-depth measure: even if a user accidentally types a real key into
   a scenario YAML, the queue refuses to enqueue the run.

2. **Image allowlist** — every container image must be pinned by digest
   (``image@sha256:<64-hex>``) and present in :data:`APPROVED_IMAGES`. This
   blocks supply-chain attacks via ``:latest`` tag drift and unknown images.

   A caller running its own experiment may extend that set for its own process
   only, by pointing ``SMADP_SANDBOX_EXTRA_APPROVED_IMAGES`` at a JSON file it
   owns. This exists so that a downstream project studying agents it built
   itself does not have to edit this package's committed allowlist, which is
   the shared baseline every host validates against and is not one experiment's
   to widen. The extension is additive only: an entry in the caller's file can
   never remove or rewrite one here, so the baseline is a floor rather than a
   default. Loading it emits a warning naming the file and the count, because a
   widened trust boundary that nobody notices is the failure this whole module
   exists to prevent.
"""

from __future__ import annotations

import json
import os
import re
import warnings
from collections.abc import Iterable
from pathlib import Path
from typing import Final

# ---------------------------------------------------------------------------
# Secret detection
# ---------------------------------------------------------------------------

# Patterns that match real-world API keys / tokens. Sourced from public
# detection rules (GitHub secret scanning, gitleaks, trufflehog). We err on
# the side of catching too much.
_REAL_SECRET_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"sk-[A-Za-z0-9]{20,}"),  # OpenAI / Anthropic-ish
    re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),  # Anthropic API key
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),  # GitHub personal token
    re.compile(r"gho_[A-Za-z0-9]{30,}"),  # GitHub OAuth
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),  # GitHub fine-grained
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key id
    re.compile(r"ASIA[0-9A-Z]{16}"),  # AWS session key id
    re.compile(r"AIza[0-9A-Za-z_-]{30,}"),  # Google API key
    re.compile(r"ya29\.[0-9A-Za-z_-]{30,}"),  # Google OAuth token
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),  # Slack tokens
    re.compile(r"glpat-[A-Za-z0-9_-]{20,}"),  # GitLab PAT
    re.compile(r"hf_[A-Za-z0-9]{30,}"),  # HuggingFace token
    re.compile(r"npm_[A-Za-z0-9]{30,}"),  # NPM token
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),  # PEM private keys
)

_SAFE_SYNTHETIC_PREFIXES: Final[tuple[str, ...]] = (
    "SMADP_TEST_",
    "synthetic-test-only-",
    "synthetic-",
)


def looks_like_real_secret(value: str) -> bool:
    """Heuristic: True if ``value`` matches any known real-secret pattern."""
    if not isinstance(value, str):
        return False
    return any(pat.search(value) for pat in _REAL_SECRET_PATTERNS)


def is_safe_secret(value: str) -> bool:
    """True iff ``value`` is acceptable as a sandbox-scoped synthetic secret.

    A safe secret either starts with a recognized synthetic prefix
    (``SMADP_TEST_`` / ``synthetic-test-only-``) **and** does not contain any
    real-secret pattern. Empty strings are not safe (forces explicit values).
    """
    if not isinstance(value, str) or not value:
        return False
    if looks_like_real_secret(value):
        return False
    return any(value.startswith(prefix) for prefix in _SAFE_SYNTHETIC_PREFIXES)


def assert_safe_secrets(env: dict[str, str]) -> None:
    """Raise :class:`UnsafeSecretError` if any value in ``env`` looks real."""
    bad: list[str] = []
    for key, value in env.items():
        if looks_like_real_secret(value):
            bad.append(key)
    if bad:
        raise UnsafeSecretError(
            f"Refusing to enqueue: env keys appear to contain real secrets: {bad}"
        )


# ---------------------------------------------------------------------------
# Image allowlist
# ---------------------------------------------------------------------------

# Two accepted forms:
#   1. Registry-pull form:  <name>[:tag]@sha256:<64hex>   — pinned upstream
#   2. Local-build form:    sha256:<64hex>                — docker image ID
# Both let docker resolve a specific immutable image; the latter is for images
# built locally that we can't tag with a registry digest.
_IMAGE_DIGEST_RE = re.compile(
    r"^(?:[a-z0-9./_-]+(?::[a-zA-Z0-9._-]+)?@sha256:[0-9a-f]{64}|sha256:[0-9a-f]{64})$"
)

_APPROVED_IMAGES_PATH: Final[Path] = Path(__file__).with_name("approved_images.json")

#: Env var naming a JSON file of additional slug -> pinned digest entries.
#: Read once at import, like the baseline, so the trust boundary of a process
#: cannot change underneath a run that has already started.
EXTRA_APPROVED_IMAGES_ENV: Final[str] = "SMADP_SANDBOX_EXTRA_APPROVED_IMAGES"


def _load_extra_approved_images(baseline: dict[str, str]) -> dict[str, str]:
    """Load the caller-supplied allowlist extension, if one is configured.

    Additive only. A key already present in the baseline is refused rather than
    overwritten: silently rebinding a slug that ships with this package would
    let an extension file redirect a known agent to an image of its choosing,
    which is precisely the substitution the allowlist exists to stop.
    """
    configured = os.environ.get(EXTRA_APPROVED_IMAGES_ENV)
    if not configured:
        return {}

    path = Path(configured).expanduser()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PolicyError(f"{EXTRA_APPROVED_IMAGES_ENV} points at {path}, which "
                          f"could not be read: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PolicyError(f"{EXTRA_APPROVED_IMAGES_ENV} points at {path}, which "
                          f"is not valid JSON: {exc}") from exc

    if not isinstance(raw, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in raw.items()
    ):
        raise PolicyError(f"{path} must be a JSON object of string to string")

    collisions = sorted(set(raw) & set(baseline))
    if collisions:
        raise PolicyError(
            f"{path} redefines slugs that ship with this package: "
            f"{', '.join(collisions)}. The extension is additive; it may not "
            f"rebind a baseline entry.")

    for slug, digest in raw.items():
        if not _IMAGE_DIGEST_RE.match(digest):
            raise PolicyError(
                f"{path} entry {slug!r} is not a pinned digest: {digest!r}")

    if raw:
        warnings.warn(
            f"sandbox image allowlist extended with {len(raw)} entries from "
            f"{path}. The baseline in this package is unchanged. Runs in this "
            f"process may execute images that other hosts will refuse.",
            stacklevel=2,
        )
    return raw


def _load_approved_images() -> dict[str, str]:
    """Load `<package>/approved_images.json` into a slug → pinned-digest mapping.

    The file is package data; it is mutated by `smadp sandbox pin-images` and
    committed to git so every host validates against the same set.
    """
    raw = json.loads(_APPROVED_IMAGES_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in raw.items()
    ):
        raise PolicyError(f"{_APPROVED_IMAGES_PATH} must be a JSON object of string→string")
    if not raw:
        raise PolicyError(f"{_APPROVED_IMAGES_PATH} must not be empty")
    return raw


_BASELINE_APPROVED_IMAGES: Final[dict[str, str]] = _load_approved_images()

#: The effective allowlist for this process: the committed baseline, plus any
#: caller extension. Callers that need to know which is which should read
#: :data:`_BASELINE_APPROVED_IMAGES`.
APPROVED_IMAGES: Final[dict[str, str]] = {
    **_BASELINE_APPROVED_IMAGES,
    **_load_extra_approved_images(_BASELINE_APPROVED_IMAGES),
}


def validate_image_digest(digest: str) -> bool:
    """True iff ``digest`` is well-formed AND in :data:`APPROVED_IMAGES`."""
    if not isinstance(digest, str) or not _IMAGE_DIGEST_RE.match(digest):
        return False
    return digest in APPROVED_IMAGES.values()


def assert_image_approved(digest: str) -> None:
    if not validate_image_digest(digest):
        raise DisallowedImageError(
            f"Image digest not on approved allowlist or malformed: {digest!r}. "
            "Pinned ``image@sha256:...`` references in APPROVED_IMAGES are required."
        )


def lookup_image_for_adapter(adapter_slug: str) -> str:
    """Return the approved pinned digest for a given adapter slug."""
    try:
        return APPROVED_IMAGES[adapter_slug]
    except KeyError as e:
        raise DisallowedImageError(
            f"No approved image for adapter slug {adapter_slug!r}; "
            f"add an entry to smadp/sandbox/approved_images.json."
        ) from e


# ---------------------------------------------------------------------------
# Egress allow-list validation
# ---------------------------------------------------------------------------

# A scenario may request egress to specific endpoints (e.g. the agent's
# inference API). We require fully-qualified hostnames and reject wildcards
# more permissive than a single suffix label.
_HOSTNAME_RE = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))+$")


def validate_egress_endpoint(endpoint: str) -> bool:
    """True iff ``endpoint`` is a single fully-qualified hostname."""
    if not isinstance(endpoint, str) or not endpoint:
        return False
    if endpoint in {"*", ""}:
        return False
    return bool(_HOSTNAME_RE.match(endpoint))


def assert_egress_allowlist_ok(endpoints: Iterable[str]) -> None:
    bad = [e for e in endpoints if not validate_egress_endpoint(e)]
    if bad:
        raise DisallowedEgressError(
            f"Egress allow-list contains invalid endpoints: {bad}. "
            "Each entry must be a fully-qualified hostname (no wildcards)."
        )


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PolicyError(Exception):
    """Base class for all sandbox-policy violations."""


class UnsafeSecretError(PolicyError):
    """A value in scenario / env appeared to be a real-world secret."""


class DisallowedImageError(PolicyError):
    """An image reference was unpinned or not on the approved allowlist."""


class DisallowedEgressError(PolicyError):
    """An egress endpoint failed validation."""


__all__ = [
    "APPROVED_IMAGES",
    "DisallowedEgressError",
    "DisallowedImageError",
    "PolicyError",
    "UnsafeSecretError",
    "assert_egress_allowlist_ok",
    "assert_image_approved",
    "assert_safe_secrets",
    "is_safe_secret",
    "looks_like_real_secret",
    "lookup_image_for_adapter",
    "validate_egress_endpoint",
    "validate_image_digest",
]
