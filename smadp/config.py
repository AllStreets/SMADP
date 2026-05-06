"""Configuration: paths, env, schema version constants."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import platformdirs

SCHEMA_VERSION = "1.0"
RUBRIC_VERSION = "1.0"

DEFAULT_MODEL_ID = "gpt-5.4-mini"
DEFAULT_MODEL_NAME = "gpt-5.4-mini"

REPO_ROOT_ENV = "SMADP_REPO_ROOT"
CATALOG_ENV = "SMADP_CATALOG"
CACHE_DIR_ENV = "SMADP_CACHE_DIR"
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
PUBLIC_BASE_URL_ENV = "SMADP_PUBLIC_BASE_URL"

PROFILE_FIELDS_REQUIRING_EVIDENCE = (
    "capabilities",
    "io_surfaces",
    "permissions_requested",
    "data_classes_touched",
    "sandboxing",
    "concurrency_model",
)


def _detect_repo_root() -> Path:
    explicit = os.environ.get(REPO_ROOT_ENV)
    if explicit:
        return Path(explicit).expanduser().resolve()
    here = Path(__file__).resolve().parent.parent
    return here


def _validate_public_base_url(url: str) -> str:
    """Validate that url is https:// or http://localhost*."""
    url_lower = url.lower()
    if url_lower.startswith("https://"):
        return url
    if url_lower.startswith("http://localhost"):
        return url
    raise ValueError("public_base_url must start with https:// or http://localhost")


@dataclass(frozen=True)
class Config:
    repo_root: Path = field(default_factory=_detect_repo_root)
    catalog_dir: Path = field(init=False)
    cache_dir: Path = field(init=False)
    openai_api_key: str | None = field(default_factory=lambda: os.environ.get(OPENAI_API_KEY_ENV))
    model_id: str = DEFAULT_MODEL_ID
    model_name: str = DEFAULT_MODEL_NAME
    public_base_url: str = field(
        default_factory=lambda: _validate_public_base_url(
            os.environ.get(PUBLIC_BASE_URL_ENV, "http://localhost:8000")
        )
    )

    def __post_init__(self) -> None:
        catalog_override = os.environ.get(CATALOG_ENV)
        catalog = (
            Path(catalog_override).expanduser().resolve()
            if catalog_override
            else self.repo_root / "catalog"
        )
        cache_override = os.environ.get(CACHE_DIR_ENV)
        cache = (
            Path(cache_override).expanduser().resolve()
            if cache_override
            else Path(platformdirs.user_cache_dir("smadp"))
        )
        object.__setattr__(self, "catalog_dir", catalog)
        object.__setattr__(self, "cache_dir", cache)

    @property
    def profiles_dir(self) -> Path:
        return self.catalog_dir / "profiles"

    @property
    def unverified_profiles_dir(self) -> Path:
        return self.profiles_dir / "_unverified"

    @property
    def chains_dir(self) -> Path:
        return self.catalog_dir / "chains"

    @property
    def verdicts_dir(self) -> Path:
        return self.catalog_dir / "verdicts"

    @property
    def evidence_dir(self) -> Path:
        return self.catalog_dir / "_evidence"

    @property
    def meta_dir(self) -> Path:
        return self.catalog_dir / "_meta"

    @property
    def chronicle_dir(self) -> Path:
        return self.catalog_dir / "_chronicle"

    @property
    def schema_dir(self) -> Path:
        return self.meta_dir / "schema" / SCHEMA_VERSION

    @property
    def rubric_path(self) -> Path:
        return self.meta_dir / "rubric" / f"{RUBRIC_VERSION}.json"

    def ensure_dirs(self) -> None:
        for directory in (
            self.profiles_dir,
            self.unverified_profiles_dir,
            self.chains_dir,
            self.verdicts_dir,
            self.evidence_dir,
            self.chronicle_dir,
            self.cache_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def load_config() -> Config:
    return Config()
