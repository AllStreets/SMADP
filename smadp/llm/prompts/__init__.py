"""Versioned prompt templates for SMADP's LLM-driven extraction and judgment.

Every prompt module exposes:

- ``VERSION``: a semver string. Bump on any text change so verdicts that
  reference an older prompt version can be regenerated deterministically.
- ``SYSTEM``: the model-facing system prompt (eligible for prompt caching).
- ``build_user_message(...)``: returns the user-turn content string.
- ``TOOL_NAME`` / ``TOOL_DESCRIPTION`` / ``TOOL_INPUT_SCHEMA``: the structured
  output tool the model must call.
"""

from smadp.llm.prompts import pairwise_judge, profile_extraction

__all__ = ["pairwise_judge", "profile_extraction"]
