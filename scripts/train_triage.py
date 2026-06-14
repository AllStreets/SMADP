"""Train the dependency-light triage model into a versioned JSON artifact.

Reads published pairwise verdicts whose both participants have profiles,
featurizes each (profile_a, profile_b) pair, fits the stdlib-only logistic
triage model (:mod:`smadp.analyzer.triage`), and writes a versioned artifact to
``catalog/_meta/triage/<version>.json`` carrying the training-set hash so the
prediction is reproducible.

The model is consumed only by the autopilot pair planner to *re-order* the judge
queue; it never publishes a verdict.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from smadp.analyzer.triage import TriageModel, train
from smadp.catalog.repo import CatalogRepo, NotFoundError
from smadp.config import Config
from smadp.schemas import Profile
from smadp.utils.hashing import sha256_canonical_json
from smadp.utils.time import utcnow_iso


def build_corpus(repo: CatalogRepo) -> list[tuple[Profile, Profile, float]]:
    """Yield ``(profile_a, profile_b, composite_score)`` for 2-participant verdicts."""
    corpus: list[tuple[Profile, Profile, float]] = []
    for verdict in repo.list_verdicts():
        if len(verdict.participants) != 2:
            continue
        a, b = verdict.participants
        try:
            pa = repo.load_profile(a)
            pb = repo.load_profile(b)
        except NotFoundError:
            continue
        corpus.append((pa, pb, verdict.composite_score))
    return corpus


def _training_set_hash(corpus: list[tuple[Profile, Profile, float]]) -> str:
    rows = sorted((tuple(sorted((a.slug, b.slug))), round(score, 6)) for a, b, score in corpus)
    return "sha256:" + sha256_canonical_json(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train the SMADP triage model.")
    parser.add_argument("--catalog", default=None, help="Catalog dir (defaults to env).")
    parser.add_argument("--out", default=None, help="Artifact output path.")
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--version", default="v1")
    args = parser.parse_args(argv)

    if args.catalog:
        os.environ["SMADP_CATALOG"] = str(Path(args.catalog).expanduser().resolve())
    config = Config()
    repo = CatalogRepo(config)

    corpus = build_corpus(repo)
    train_hash = _training_set_hash(corpus)
    model: TriageModel = train(
        corpus, seed=args.seed, version=args.version, trained_at=utcnow_iso()
    )

    out = (
        Path(args.out).expanduser()
        if args.out
        else config.catalog_dir / "_meta" / "triage" / f"{args.version}.json"
    )
    model.save(out, training_set_hash=train_hash)
    print(f"wrote triage artifact: {out} ({len(corpus)} pairs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
