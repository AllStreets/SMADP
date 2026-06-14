"""Dependency-light learned triage model (S2.3 core).

A pure-Python (stdlib ``math`` only — no numpy/scikit-learn) L2-regularized
one-vs-rest logistic-regression-per-band classifier. It maps the two profiles'
capability vectors + their category pair to a predicted composite *band* and an
*uncertainty*. It NEVER publishes a number as a verdict — triage only re-orders
the autopilot pair planner (Task 13).

Determinism is guaranteed by a fixed seed (``random.Random(seed)``) and sorted
iteration, not by a numeric library. The model artifact is a versioned JSON file
carrying its training-set hash, so a prediction is always reproducible.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from random import Random
from typing import Any

from smadp.analyzer.capability_drift import EGRESS_ORDER, _BOOL_FIELDS
from smadp.schemas.profile import Profile
from smadp.utils.hashing import sha256_text

BANDS: tuple[str, ...] = ("safe", "low", "medium", "high")
_BAND_THRESHOLDS = (0.2, 0.4, 0.6)  # safe < 0.2 <= low < 0.4 <= medium < 0.6 <= high
_CATEGORY_BUCKETS = 8


def band_for_composite(score: float) -> str:
    if score < _BAND_THRESHOLDS[0]:
        return "safe"
    if score < _BAND_THRESHOLDS[1]:
        return "low"
    if score < _BAND_THRESHOLDS[2]:
        return "medium"
    return "high"


def _bucket_count(n: int) -> float:
    """Log-bucket a set size into a small, bounded scalar in [0, 1]."""
    return min(1.0, math.log1p(max(0, n)) / math.log(11.0))


def _category_bucket(category: str) -> int:
    digest = sha256_text(category.strip().lower())
    return int(digest, 16) % _CATEGORY_BUCKETS


def _side_features(p: Profile) -> list[float]:
    caps = p.capabilities
    perms = p.permissions_requested
    feats = [1.0 if getattr(caps, f) else 0.0 for f in _BOOL_FIELDS]
    feats.append(EGRESS_ORDER[caps.network_egress] / 3.0)
    feats.append(_bucket_count(len(perms.oauth_scopes)))
    feats.append(_bucket_count(len(perms.secrets_handled)))
    feats.append(_bucket_count(len(perms.elevated_privileges)))
    feats.append(_bucket_count(len(p.data_classes_touched)))
    return feats


_SIDE_NAMES = (
    [f"bool_{f}" for f in _BOOL_FIELDS]
    + ["egress", "oauth_n", "secrets_n", "elevated_n", "data_n"]
)


def _build_feature_names() -> list[str]:
    names = [f"min_{n}" for n in _SIDE_NAMES] + [f"max_{n}" for n in _SIDE_NAMES]
    names += [f"cat_{i}" for i in range(_CATEGORY_BUCKETS)]
    return names


FEATURE_NAMES: list[str] = _build_feature_names()


def featurize(a: Profile, b: Profile) -> list[float]:
    """Slug-sorted, order-independent feature vector for a profile pair."""
    pa, pb = (a, b) if a.slug <= b.slug else (b, a)
    fa = _side_features(pa)
    fb = _side_features(pb)
    # Symmetric reduction so featurize(a, b) == featurize(b, a).
    mins = [min(x, y) for x, y in zip(fa, fb, strict=True)]
    maxs = [max(x, y) for x, y in zip(fa, fb, strict=True)]

    cat_onehot = [0.0] * _CATEGORY_BUCKETS
    bucket = _category_bucket(pa.category + "|" + pb.category)
    cat_onehot[bucket] = 1.0

    return mins + maxs + cat_onehot


def _sigmoid(z: float) -> float:
    if z >= 0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


@dataclass
class Prediction:
    band: str
    probabilities: dict[str, float]
    uncertainty: float


class TriageModel:
    """One-vs-rest logistic model over :data:`FEATURE_NAMES`."""

    def __init__(
        self,
        *,
        weights: dict[str, list[float]],
        bias: dict[str, float],
        classes: list[str],
        version: str = "v0",
        trained_at: str = "",
        training_set_hash: str = "",
        majority_band: str | None = None,
    ) -> None:
        self.weights = weights
        self.bias = bias
        self.classes = classes
        self.version = version
        self.trained_at = trained_at
        self.training_set_hash = training_set_hash
        self.majority_band = majority_band

    # ------------------------------------------------------------------ predict
    def predict(self, a: Profile, b: Profile) -> Prediction:
        x = featurize(a, b)
        if self.majority_band is not None:
            probs = {band: (1.0 if band == self.majority_band else 0.0) for band in BANDS}
            return Prediction(band=self.majority_band, probabilities=probs, uncertainty=1.0)

        raw: dict[str, float] = {}
        for band in self.classes:
            z = self.bias[band] + sum(
                w * xi for w, xi in zip(self.weights[band], x, strict=True)
            )
            raw[band] = _sigmoid(z)
        total = sum(raw.values()) or 1.0
        probs = {band: raw[band] / total for band in self.classes}
        # Fill any non-trained band with 0 for a stable shape.
        for band in BANDS:
            probs.setdefault(band, 0.0)

        ordered = sorted(probs.values(), reverse=True)
        top = ordered[0]
        second = ordered[1] if len(ordered) > 1 else 0.0
        uncertainty = max(0.0, min(1.0, 1.0 - (top - second)))
        best = max(self.classes, key=lambda band: probs[band])
        return Prediction(band=best, probabilities=probs, uncertainty=uncertainty)

    # -------------------------------------------------------------------- io
    def save(self, path: Path, *, training_set_hash: str) -> None:
        self.training_set_hash = training_set_hash
        payload = {
            "version": self.version,
            "trained_at": self.trained_at,
            "training_set_hash": training_set_hash,
            "feature_names": FEATURE_NAMES,
            "feature_count": len(FEATURE_NAMES),
            "classes": self.classes,
            "weights": self.weights,
            "bias": self.bias,
            "majority_band": self.majority_band,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> TriageModel:
        data: dict[str, Any] = json.loads(Path(path).read_text("utf-8"))
        return cls(
            weights={k: list(v) for k, v in data["weights"].items()},
            bias=dict(data["bias"]),
            classes=list(data["classes"]),
            version=data.get("version", "v0"),
            trained_at=data.get("trained_at", ""),
            training_set_hash=data.get("training_set_hash", ""),
            majority_band=data.get("majority_band"),
        )


def train(
    corpus: list[tuple[Profile, Profile, float]],
    *,
    seed: int,
    epochs: int = 300,
    lr: float = 0.1,
    l2: float = 0.001,
    version: str = "v0",
    trained_at: str = "",
) -> TriageModel:
    """Fit a deterministic OvR logistic model from a labeled corpus."""
    rows = [(featurize(a, b), band_for_composite(score)) for a, b, score in corpus]
    present = sorted({label for _, label in rows}, key=BANDS.index)

    # Degenerate guard: empty or single-class corpus -> majority band, uncertainty 1.0.
    if len(present) <= 1:
        majority = present[0] if present else "safe"
        return TriageModel(
            weights={}, bias={}, classes=[],
            version=version, trained_at=trained_at, majority_band=majority,
        )

    rng = Random(seed)
    n_features = len(FEATURE_NAMES)
    weights: dict[str, list[float]] = {}
    bias: dict[str, float] = {}

    for band in present:
        w = [rng.uniform(-0.01, 0.01) for _ in range(n_features)]
        b = 0.0
        targets = [1.0 if label == band else 0.0 for _, label in rows]
        m = len(rows)
        for _ in range(epochs):
            grad_w = [0.0] * n_features
            grad_b = 0.0
            for (x, _label), y in zip(rows, targets, strict=True):
                z = b + sum(wi * xi for wi, xi in zip(w, x, strict=True))
                err = _sigmoid(z) - y
                for j in range(n_features):
                    grad_w[j] += err * x[j]
                grad_b += err
            for j in range(n_features):
                w[j] -= lr * (grad_w[j] / m + l2 * w[j])
            b -= lr * (grad_b / m)
        weights[band] = w
        bias[band] = b

    return TriageModel(
        weights=weights, bias=bias, classes=present,
        version=version, trained_at=trained_at,
    )
