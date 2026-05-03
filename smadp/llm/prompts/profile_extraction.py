"""Prompt for extracting a Safety Profile from fetched source documents.

Strict anti-hallucination contract: every populated field must cite at least
one evidence sha that was supplied in the bundle, and a verbatim quote from
the source document. Empty is preferred over guessed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

VERSION = "1.0.0"

SYSTEM = """You are SMADP-Profiler, an evidence-only safety analyst.

Your job is to read the supplied source documents about an AI agent and emit a
single, well-formed Safety Profile by calling the `emit_profile` tool exactly
once.

ABSOLUTE RULES (violations cause the profile to be rejected):

1. EVIDENCE-ONLY. You MAY ONLY populate a field if at least one supplied
   evidence document directly supports it. If the documents are silent on a
   field, leave it at its safe default (false / empty list / empty string).
   "Empty is better than guessed."

2. CITE EVERY SIGNAL. For every capability you set to true, every IO surface
   you enable, every permission, every secret, every data class, every API
   endpoint, every sandboxing/concurrency string you fill in, the supporting
   evidence sha MUST appear in the profile's `evidence_refs` array.

3. VERBATIM QUOTES ONLY. When you reference an evidence document, the quote
   in that document must appear verbatim in the original source. Do not
   paraphrase. Do not fabricate quotes. If you cannot find a verbatim quote
   that supports a field, do not set the field.

4. CONSERVATIVE DEFAULTS. If documentation is ambiguous about a capability
   (e.g. "may execute commands"), leave the capability false unless the
   document unambiguously confirms it. Under-claiming is safe; over-claiming
   is a bug.

5. NO INVENTED FIELDS. The Safety Profile schema is closed. Do not add fields
   the schema does not define. Do not invent OAuth scopes, secrets, or APIs
   that the documents do not name.

6. SLUG AND IDENTITY. Use the slug, name, source_type, and category provided
   by the user message exactly as given. Do not rename the agent.

7. TIMESTAMPS. Use the `now_iso` value supplied in the user message for
   `first_seen_at` and `last_refreshed_at`.

8. EVIDENCE_REFS DEDUP. Each sha in `evidence_refs` should appear at most
   once and must be one of the shas listed in the EVIDENCE bundle.

9. NO EXTERNAL KNOWLEDGE. Even if you "know" facts about this agent from
   training data, do not include them. Only the supplied bundle counts.

10. EXACTLY ONE TOOL CALL. Call `emit_profile` exactly once, then stop. No
    free-text response.

The Safety Profile schema is documented in the tool's input schema. Honor
every constraint (enums, patterns, additionalProperties=false).
"""


@dataclass(frozen=True)
class ProfileExtractionInput:
    """Inputs the user message needs to convey to the model."""

    slug: str
    name: str
    source_type: str
    category: str
    homepage: str | None
    repo_url: str | None
    docs_urls: list[str]
    now_iso: str
    evidence: list[dict[str, str]]
    """Each item: {sha, source_url, media_type, quote, context}."""


def build_user_message(payload: ProfileExtractionInput) -> str:
    """Render the user-turn content for one extraction call."""
    header = (
        "Extract a Safety Profile for the following agent. Honor every rule in "
        "the system prompt. Call `emit_profile` exactly once.\n\n"
        f"slug: {payload.slug}\n"
        f"name: {payload.name}\n"
        f"source_type: {payload.source_type}\n"
        f"category: {payload.category}\n"
        f"homepage: {payload.homepage or ''}\n"
        f"repo_url: {payload.repo_url or ''}\n"
        f"docs_urls: {json.dumps(payload.docs_urls)}\n"
        f"now_iso: {payload.now_iso}\n"
    )
    bundle_lines = ["", "EVIDENCE BUNDLE (each item is a chunk of a real source document):", ""]
    for item in payload.evidence:
        bundle_lines.append(f"--- evidence sha256:{item['sha']} ---")
        bundle_lines.append(f"source_url: {item['source_url']}")
        bundle_lines.append(f"media_type: {item['media_type']}")
        if item.get("context"):
            bundle_lines.append(f"context: {item['context']}")
        bundle_lines.append("quote:")
        bundle_lines.append(item["quote"])
        bundle_lines.append("")
    return header + "\n".join(bundle_lines)


TOOL_NAME = "emit_profile"
TOOL_DESCRIPTION = (
    "Emit the extracted Safety Profile as a single JSON object that conforms "
    "exactly to the supplied input schema. Call this tool once and only once."
)

TOOL_INPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "required": [
        "slug",
        "name",
        "vendor",
        "source_type",
        "category",
        "verification",
        "capabilities",
        "io_surfaces",
        "permissions_requested",
        "data_classes_touched",
        "sandboxing",
        "concurrency_model",
        "evidence_refs",
        "first_seen_at",
        "last_refreshed_at",
    ],
    "additionalProperties": False,
    "properties": {
        "slug": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{1,63}$"},
        "name": {"type": "string", "minLength": 1, "maxLength": 100},
        "tagline": {"type": "string", "maxLength": 200},
        "vendor": {
            "type": "object",
            "required": ["type", "handle"],
            "additionalProperties": False,
            "properties": {
                "type": {"enum": ["company", "org", "individual"]},
                "handle": {"type": "string", "minLength": 1},
                "url": {"type": "string"},
            },
        },
        "source_type": {"enum": ["open-source", "closed-source", "source-available"]},
        "category": {"type": "string", "minLength": 1},
        "homepage": {"type": "string"},
        "docs_urls": {"type": "array", "items": {"type": "string"}},
        "repo_url": {"type": "string"},
        "verification": {
            "type": "object",
            "required": ["status", "verified_at", "method"],
            "additionalProperties": False,
            "properties": {
                "status": {"enum": ["unverified", "draft", "verified", "stale", "invalid"]},
                "verified_by": {"type": "string"},
                "verified_at": {"type": "string"},
                "method": {
                    "enum": [
                        "manual-review-of-llm-extraction",
                        "manual-authoring",
                        "auto-only",
                    ]
                },
            },
        },
        "capabilities": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "execute_shell": {"type": "boolean"},
                "read_filesystem": {"type": "boolean"},
                "write_filesystem": {"type": "boolean"},
                "network_egress": {"enum": ["none", "allowlisted", "vendor-only", "broad"]},
                "spawn_subprocesses": {"type": "boolean"},
                "use_mcp": {"type": "boolean"},
                "modify_git_state": {"type": "boolean"},
                "install_packages": {"type": "boolean"},
                "run_browsers": {"type": "boolean"},
            },
        },
        "io_surfaces": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "stdin_stdout": {"type": "boolean"},
                "files": {"type": "array", "items": {"type": "string"}},
                "clipboard": {"type": "boolean"},
                "screen_capture": {"type": "boolean"},
                "audio": {"type": "boolean"},
                "calls_apis": {"type": "array", "items": {"type": "string"}},
            },
        },
        "permissions_requested": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "oauth_scopes": {"type": "array", "items": {"type": "string"}},
                "secrets_handled": {"type": "array", "items": {"type": "string"}},
                "elevated_privileges": {"type": "array", "items": {"type": "string"}},
            },
        },
        "data_classes_touched": {"type": "array", "items": {"type": "string"}},
        "sandboxing": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "self_isolation": {"type": "string"},
                "subagent_model": {"type": "string"},
                "tool_use_pattern": {"type": "string"},
            },
        },
        "concurrency_model": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "session_scope": {"type": "string"},
                "shared_state_with_other_instances": {"type": "string"},
                "supports_multiple_instances": {"type": "boolean"},
            },
        },
        "evidence_refs": {
            "type": "array",
            "items": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
        },
        "first_seen_at": {"type": "string"},
        "last_refreshed_at": {"type": "string"},
    },
}
