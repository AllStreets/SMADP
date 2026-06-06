"""OnexusProfiler: turn a RawOnexusAgent into an SMADP profile dict.

Capability inference is a deliberately conservative tag-based heuristic.
Anything we can't infer defaults to "unknown" (False / "none"). Operators can
override by editing the profile JSON and adding ``"manual": true`` so future
bootstrap runs skip the file (see ``bootstrap.py`` for the policy).
"""

from __future__ import annotations

import hashlib
from typing import Any

from smadp.autopilot.sources.onexus import RawOnexusAgent

_SHELL_TAGS = {"shell", "cli", "terminal", "bash", "zsh"}
_FS_READ_TAGS = {"filesystem", "files", "file-system", "fs", "code-search"}
_FS_WRITE_TAGS = {"filesystem", "files", "file-system", "fs", "code-edit", "code-editor"}
_NETWORK_BROAD = {"web-browsing", "browser", "web", "internet", "scraping"}
_NETWORK_NARROW = {"api", "rest", "http"}
_MCP_TAGS = {"mcp", "model-context-protocol"}


def _sha(s: str) -> str:
    return "sha256:" + hashlib.sha256(s.encode("utf-8")).hexdigest()


class OnexusProfiler:
    name = "onexus"
    accepts_source = "onexus"

    def normalize(self, raw: RawOnexusAgent) -> dict[str, Any]:
        tags_lc = {t.lower() for t in raw.tags}
        docs_urls: list[str] = []
        if raw.source_homepage:
            docs_urls.append(raw.source_homepage)
        if raw.source_github:
            docs_urls.append(f"https://github.com/{raw.source_github}")
        evidence_refs = [_sha(f"onexus:{raw.slug}:{u}") for u in docs_urls]

        capabilities = {
            "execute_shell": bool(tags_lc & _SHELL_TAGS),
            "install_packages": False,
            "modify_git_state": False,
            "network_egress": (
                "broad"
                if tags_lc & _NETWORK_BROAD
                else "narrow"
                if tags_lc & _NETWORK_NARROW
                else "none"
            ),
            "read_filesystem": bool(tags_lc & _FS_READ_TAGS),
            "run_browsers": bool({"browser", "web-browsing"} & tags_lc),
            "spawn_subprocesses": bool(tags_lc & _SHELL_TAGS),
            "use_mcp": bool(tags_lc & _MCP_TAGS),
            "write_filesystem": bool(tags_lc & _FS_WRITE_TAGS),
        }
        return {
            "slug": raw.slug,
            "name": raw.name,
            "category": raw.category,
            "evidence_level": "docs-only",
            "docs_urls": docs_urls,
            "evidence_refs": evidence_refs,
            "capabilities": capabilities,
            "data_classes_touched": [],
            "concurrency_model": {
                "session_scope": "unknown",
                "shared_state_with_other_instances": "unknown",
                "supports_multiple_instances": False,
            },
            "composite_score": raw.composite_score,
            "license": raw.license,
            "onexus": {
                "source_github": raw.source_github,
                "author_handle": raw.author_handle,
                "tags": raw.tags,
                "runnable": raw.runnable,
            },
        }
