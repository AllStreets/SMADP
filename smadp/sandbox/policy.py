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
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Final

# ---------------------------------------------------------------------------
# Secret detection
# ---------------------------------------------------------------------------

# Patterns that match real-world API keys / tokens. Sourced from public
# detection rules (GitHub secret scanning, gitleaks, trufflehog). We err on
# the side of catching too much.
_REAL_SECRET_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"sk-[A-Za-z0-9]{20,}"),                # OpenAI / Anthropic-ish
    re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),          # Anthropic API key
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),               # GitHub personal token
    re.compile(r"gho_[A-Za-z0-9]{30,}"),               # GitHub OAuth
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),       # GitHub fine-grained
    re.compile(r"AKIA[0-9A-Z]{16}"),                   # AWS access key id
    re.compile(r"ASIA[0-9A-Z]{16}"),                   # AWS session key id
    re.compile(r"AIza[0-9A-Za-z_-]{30,}"),             # Google API key
    re.compile(r"ya29\.[0-9A-Za-z_-]{30,}"),           # Google OAuth token
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),       # Slack tokens
    re.compile(r"glpat-[A-Za-z0-9_-]{20,}"),           # GitLab PAT
    re.compile(r"hf_[A-Za-z0-9]{30,}"),                # HuggingFace token
    re.compile(r"npm_[A-Za-z0-9]{30,}"),               # NPM token
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

_IMAGE_DIGEST_RE = re.compile(
    r"^[a-z0-9./_-]+(?::[a-zA-Z0-9._-]+)?@sha256:[0-9a-f]{64}$"
)

# Approved base images keyed by adapter slug. The digest values below are
# placeholders (all-zero) for v1 development; ops MUST replace them with real,
# signature-verified digests before sandbox runs go to production. The list is
# intentionally tiny: every addition is a supply-chain decision.
#
# To pin a real digest: ``docker buildx imagetools inspect <ref>`` or
# ``crane digest <ref>`` and copy the ``sha256:...`` line.
APPROVED_IMAGES: Final[dict[str, str]] = {
    # Generic Python runtime — used by adapters that ship as pip packages.
    "python-base": (
        "docker.io/library/python:3.12-slim@sha256:"
        "0000000000000000000000000000000000000000000000000000000000000000"
    ),
    # Node runtime — used by JS-based adapters (continue-dev local server).
    "node-base": (
        "docker.io/library/node:20-bookworm-slim@sha256:"
        "0000000000000000000000000000000000000000000000000000000000000000"
    ),
    # Per-adapter images. Replace with real ghcr.io / docker.io digests once
    # signatures are verified. Keep the slug here aligned with
    # ``adapters/<slug>/mcp.json``'s ``slug`` field.
    "aider": (
        "ghcr.io/paul-gauthier/aider@sha256:"
        "0000000000000000000000000000000000000000000000000000000000000000"
    ),
    "continue-dev": (
        "ghcr.io/continuedev/continue@sha256:"
        "0000000000000000000000000000000000000000000000000000000000000000"
    ),
    "autogen": (
        "ghcr.io/microsoft/autogen@sha256:"
        "0000000000000000000000000000000000000000000000000000000000000000"
    ),
    "open-interpreter": (
        "ghcr.io/openinterpreter/open-interpreter@sha256:"
        "0000000000000000000000000000000000000000000000000000000000000000"
    ),
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
            f"add an entry to smadp.sandbox.policy.APPROVED_IMAGES."
        ) from e


# ---------------------------------------------------------------------------
# Egress allow-list validation
# ---------------------------------------------------------------------------

# A scenario may request egress to specific endpoints (e.g. the agent's
# inference API). We require fully-qualified hostnames and reject wildcards
# more permissive than a single suffix label.
_HOSTNAME_RE = re.compile(
    r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))+$"
)


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
    "lookup_image_for_adapter",
    "looks_like_real_secret",
    "validate_egress_endpoint",
    "validate_image_digest",
]
