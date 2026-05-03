"""Lock the LLM prompt versions.

The two prompts that drive every Profile and Verdict are part of SMADP's
public reproducibility surface. A prompt revision MUST bump the VERSION
constant — the chronicle and downstream consumers rely on the version
string to detect drift. This test makes a silent revision impossible.
"""

from __future__ import annotations

from smadp.llm.prompts import pairwise_judge, profile_extraction


def test_profile_extraction_prompt_version() -> None:
    assert profile_extraction.VERSION == "1.0.0"


def test_pairwise_judge_prompt_version() -> None:
    assert pairwise_judge.VERSION == "1.0.0"


def test_profile_extraction_tool_name_stable() -> None:
    assert profile_extraction.TOOL_NAME == "emit_profile"


def test_pairwise_judge_tool_name_stable() -> None:
    assert pairwise_judge.TOOL_NAME == "emit_verdict"
