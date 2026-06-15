"""Git-backed catalog CRUD with atomic writes.

This module reads/writes the on-disk catalog (profiles, verdicts, evidence).
Writes are atomic: data is written to a `.tmp` sibling and then renamed onto
the target path, which is an atomic operation on POSIX filesystems. A separate
git layer (out of scope here) is expected to track the resulting file changes.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from smadp.config import Config, load_config
from smadp.schemas import Chain, Evidence, Profile, Verdict
from smadp.schemas.profile import VerificationStatus
from smadp.utils.slug import pair_filename, participants_filename, sort_pair


class CatalogError(RuntimeError):
    """Base class for catalog errors."""


class NotFoundError(CatalogError):
    """Raised when a profile / verdict / evidence file is missing."""


class CatalogRepo:
    """Read/write access to the SMADP catalog on disk.

    All write methods are atomic per-file. The repo does NOT directly invoke
    git; callers (e.g. the CLI commit step) are responsible for staging the
    affected files. The in-process write contract is "the file is either fully
    valid JSON for the new value or fully valid JSON for the previous value".
    """

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or load_config()
        # Don't auto-create directories on read paths; ensure_dirs is called
        # explicitly by `smadp init` and by all save_* methods.

    # ------------------------------------------------------------------ paths
    def profile_path(self, slug: str, *, verified: bool = True) -> Path:
        if verified:
            return self.config.profiles_dir / f"{slug}.json"
        return self.config.unverified_profiles_dir / f"{slug}.json"

    def verdict_path(self, *participants: str) -> Path:
        """Path to a verdict for a set of 2-4 participating agents.

        Length-2 callers can still write ``verdict_path(slug_a, slug_b)``;
        the resulting filename matches the legacy ``pair_filename`` output.
        """
        if len(participants) == 2:
            # Preserve identical bytes/path semantics for the 2-agent case.
            return self.config.verdicts_dir / pair_filename(*participants)
        return self.config.verdicts_dir / participants_filename(participants)

    def pending_path(self, *participants: str) -> Path:
        """Path to a pending (unreviewed) verdict for a set of 2-4 participants.

        Uses the same filename convention as ``verdict_path`` but lands under
        ``catalog/pending/`` instead of ``catalog/verdicts/``. The pending dir
        holds verdicts that were seeded by an automated sandbox run for a
        first-time agent combination; a human reviewer is expected to move
        them into ``verdicts/`` to publish.
        """
        if len(participants) == 2:
            return self.config.pending_dir / pair_filename(*participants)
        return self.config.pending_dir / participants_filename(participants)

    def evidence_path(self, ref: str) -> Path:
        if ref.startswith("sha256:"):
            sha = ref.removeprefix("sha256:")
        else:
            sha = ref
        return self.config.evidence_dir / f"sha256-{sha}.json"

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
        """Write JSON to `path` atomically (write to temp + rename)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        # NamedTemporaryFile in same directory ensures rename() is atomic.
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False, sort_keys=True, default=str)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise NotFoundError(f"file not found: {path}")
        with path.open("r", encoding="utf-8") as fh:
            data: Any = json.load(fh)
        if not isinstance(data, dict):
            raise CatalogError(f"expected object in {path}, got {type(data).__name__}")
        return data

    # --------------------------------------------------------------- profiles
    def load_profile(self, slug: str) -> Profile:
        verified_path = self.profile_path(slug, verified=True)
        if verified_path.exists():
            return Profile.model_validate(self._read_json(verified_path))
        unverified_path = self.profile_path(slug, verified=False)
        if unverified_path.exists():
            return Profile.model_validate(self._read_json(unverified_path))
        raise NotFoundError(f"profile not found: {slug}")

    def profile_exists(self, slug: str) -> bool:
        return (
            self.profile_path(slug, verified=True).exists()
            or self.profile_path(slug, verified=False).exists()
        )

    def save_profile(self, profile: Profile, *, verified: bool = True) -> Path:
        path = self.profile_path(profile.slug, verified=verified)
        # If we're saving as verified, opportunistically remove any stale
        # unverified copy so the catalog has a single source of truth.
        if verified:
            stale = self.profile_path(profile.slug, verified=False)
            if stale.exists():
                stale.unlink()
        payload = profile.model_dump(mode="json", exclude_none=False)
        self._atomic_write_json(path, payload)
        return path

    def list_profiles(
        self,
        *,
        status: VerificationStatus | None = None,
        category: str | None = None,
        source_type: str | None = None,
    ) -> list[Profile]:
        results: list[Profile] = []
        roots: list[Path] = []
        if self.config.profiles_dir.exists():
            roots.append(self.config.profiles_dir)
        if self.config.unverified_profiles_dir.exists():
            roots.append(self.config.unverified_profiles_dir)
        seen: set[str] = set()
        for root in roots:
            for path in sorted(root.glob("*.json")):
                # Skip the unverified subdir when iterating the verified root.
                if path.parent == self.config.profiles_dir and path.parent.name == "profiles":
                    pass
                try:
                    profile = Profile.model_validate(self._read_json(path))
                except (CatalogError, ValueError):
                    continue
                if profile.slug in seen:
                    continue
                seen.add(profile.slug)
                if status is not None and profile.verification.status != status:
                    continue
                if category is not None and profile.category != category:
                    continue
                if source_type is not None and profile.source_type != source_type:
                    continue
                results.append(profile)
        results.sort(key=lambda p: p.slug)
        return results

    def iter_profile_slugs(self) -> Iterator[str]:
        """Yield all known profile slugs (verified + unverified, deduped)."""
        seen: set[str] = set()
        for root in (self.config.profiles_dir, self.config.unverified_profiles_dir):
            if not root.exists():
                continue
            for path in sorted(root.glob("*.json")):
                slug = path.stem
                if slug in seen:
                    continue
                seen.add(slug)
                yield slug

    def iter_profile_entries(self) -> Iterator[tuple[str, Profile | None, dict[str, Any]]]:
        """Yield every profile on disk as ``(slug, full_or_None, raw_dict)``.

        The catalog now has three tiers (hand-curated, LLM-enriched, ONEXUS
        stubs) and only the first two reliably satisfy the strict ``Profile``
        schema. Callers that need to iterate ALL profiles (e.g. the search
        indexer) use this method: a full ``Profile`` object is returned when
        validation succeeds; ``None`` plus the raw dict otherwise.
        """
        from pydantic import ValidationError

        seen: set[str] = set()
        for root in (self.config.profiles_dir, self.config.unverified_profiles_dir):
            if not root.exists():
                continue
            for path in sorted(root.glob("*.json")):
                slug = path.stem
                if slug in seen:
                    continue
                seen.add(slug)
                try:
                    raw = self._read_json(path)
                except CatalogError:
                    continue
                if not isinstance(raw, dict):
                    continue
                try:
                    full: Profile | None = Profile.model_validate(raw)
                except (ValidationError, ValueError):
                    full = None
                yield slug, full, raw

    # ---------------------------------------------------------------- verdicts
    def load_verdict(self, *participants: str, include_pending: bool = False) -> Verdict:
        """Load the verdict for 2-4 participating agents.

        Backwards compatible: ``load_verdict(slug_a, slug_b)`` continues to
        work because participants is variadic-positional.

        When ``include_pending`` is True, falls back to ``catalog/pending/``
        if no published verdict exists. The published path is always preferred
        when both exist.
        """
        path = self.verdict_path(*participants)
        if path.exists():
            return Verdict.model_validate(self._read_json(path))
        if include_pending:
            pending = self.pending_path(*participants)
            if pending.exists():
                return Verdict.model_validate(self._read_json(pending))
        raise NotFoundError(f"verdict not found: {list(participants)}")

    def verdict_exists(self, *participants: str) -> bool:
        return self.verdict_path(*participants).exists()

    def pending_verdict_exists(self, *participants: str) -> bool:
        return self.pending_path(*participants).exists()

    def _build_verdict_payload(self, verdict: Verdict) -> tuple[list[str], dict[str, Any]]:
        """Shared payload builder for save_verdict / save_pending_verdict."""
        participants = list(verdict.participants)
        if list(participants) != sorted(participants):
            raise CatalogError(f"verdict participants must be alphabetized; got {participants}")
        payload = verdict.model_dump(mode="json", exclude_none=False)
        # Pydantic emits `pair` as a list — make sure that survives for N=2.
        if len(participants) == 2:
            payload["pair"] = [participants[0], participants[1]]
        payload["participants"] = list(participants)
        return participants, payload

    def save_verdict(self, verdict: Verdict) -> Path:
        # Canonical N-ary path: derive from ``participants``.
        participants, payload = self._build_verdict_payload(verdict)
        path = self.verdict_path(*participants)
        self._atomic_write_json(path, payload)
        return path

    def save_pending_verdict(self, verdict: Verdict) -> Path:
        """Atomically write a verdict to ``catalog/pending/<key>.json``.

        Used to stash first-time, agent-seeded verdicts for human review
        before they are promoted into the published ``verdicts/`` directory.
        The on-disk shape matches ``save_verdict`` so a reviewer can simply
        ``mv`` the file across directories to publish it.
        """
        participants, payload = self._build_verdict_payload(verdict)
        path = self.pending_path(*participants)
        self._atomic_write_json(path, payload)
        return path

    def list_verdicts(
        self,
        *,
        evidence_level: str | None = None,
        slug: str | None = None,
    ) -> list[Verdict]:
        results: list[Verdict] = []
        if not self.config.verdicts_dir.exists():
            return results
        for path in sorted(self.config.verdicts_dir.glob("*__*.json")):
            try:
                verdict = Verdict.model_validate(self._read_json(path))
            except (CatalogError, ValueError):
                continue
            if evidence_level is not None and verdict.evidence_level != evidence_level:
                continue
            if slug is not None and slug not in verdict.participants:
                continue
            results.append(verdict)
        results.sort(key=lambda v: tuple(v.participants))
        return results

    # ---------------------------------------------------------------- evidence
    def load_evidence(self, ref: str) -> Evidence:
        path = self.evidence_path(ref)
        if not path.exists():
            raise NotFoundError(f"evidence not found: {ref}")
        return Evidence.model_validate(self._read_json(path))

    def evidence_exists(self, ref: str) -> bool:
        return self.evidence_path(ref).exists()

    def save_evidence(self, evidence: Evidence) -> Path:
        path = self.evidence_path(evidence.evidence_ref)
        payload = evidence.model_dump(mode="json", exclude_none=False)
        self._atomic_write_json(path, payload)
        return path

    def iter_evidence_refs(self) -> Iterator[str]:
        if not self.config.evidence_dir.exists():
            return
        for path in sorted(self.config.evidence_dir.glob("sha256-*.json")):
            sha = path.stem.removeprefix("sha256-")
            yield f"sha256:{sha}"

    # ------------------------------------------------------------------ chains
    def chain_path(self, chain_id: str) -> Path:
        return self.config.chains_dir / f"{chain_id}.json"

    def save_chain(self, chain: Chain) -> Path:
        path = self.chain_path(chain.chain_id)
        self.config.chains_dir.mkdir(parents=True, exist_ok=True)
        payload = chain.model_dump(mode="json", by_alias=True, exclude_none=True)
        self._atomic_write_json(path, payload)
        return path

    def load_chain(self, chain_id: str) -> Chain:
        path = self.chain_path(chain_id)
        if not path.exists():
            raise NotFoundError(f"chain not found: {chain_id}")
        return Chain.model_validate(self._read_json(path))

    def list_chains(self) -> list[Chain]:
        if not self.config.chains_dir.exists():
            return []
        out: list[Chain] = []
        for path in sorted(self.config.chains_dir.glob("*.json")):
            try:
                out.append(Chain.model_validate(self._read_json(path)))
            except (CatalogError, ValueError):
                continue
        return out

    # ------------------------------------------------------- pending chains
    def pending_chains_dir(self) -> Path:
        """Holding pen for composed chain candidates awaiting operator review.

        Composed chains are ``Chain`` models (not pairwise ``Verdict`` files),
        so they live in ``catalog/pending/chains/`` rather than the flat
        pairwise pending queue. An operator promotes a candidate via
        ``approve_chain`` (file move) into ``catalog/chains/``.
        """
        return self.config.pending_dir / "chains"

    def pending_chain_path(self, chain_id: str) -> Path:
        return self.pending_chains_dir() / f"{chain_id}.json"

    def save_pending_chain(self, chain: Chain) -> Path:
        path = self.pending_chain_path(chain.chain_id)
        self.pending_chains_dir().mkdir(parents=True, exist_ok=True)
        payload = chain.model_dump(mode="json", by_alias=True, exclude_none=True)
        self._atomic_write_json(path, payload)
        return path

    def load_pending_chain(self, chain_id: str) -> Chain:
        path = self.pending_chain_path(chain_id)
        if not path.exists():
            raise NotFoundError(f"pending chain not found: {chain_id}")
        return Chain.model_validate(self._read_json(path))

    def list_pending_chains(self) -> list[Chain]:
        pending_chains = self.pending_chains_dir()
        if not pending_chains.exists():
            return []
        out: list[Chain] = []
        for path in sorted(pending_chains.glob("*.json")):
            try:
                out.append(Chain.model_validate(self._read_json(path)))
            except (CatalogError, ValueError):
                continue
        return out

    # ------------------------------------------------------------------- pairs
    def iter_pairs(self) -> Iterator[tuple[str, str]]:
        """Yield every alphabetized pair of slugs in the catalog."""
        slugs = sorted(self.iter_profile_slugs())
        for i, a in enumerate(slugs):
            for b in slugs[i + 1 :]:
                yield sort_pair(a, b)


@contextmanager
def open_repo(config: Config | None = None) -> Iterator[CatalogRepo]:
    """Convenience context manager (no-op cleanup; reserved for future locking)."""
    yield CatalogRepo(config)
