"""Async Anthropic client wrapper with prompt caching, retries, and tool-use.

Two public entry points are exposed:

- :meth:`LLMClient.extract_profile` — single tool-use call against the
  profile-extraction prompt; returns the raw tool-input dict.
- :meth:`LLMClient.judge_pair` — single tool-use call against the pairwise
  judge prompt; returns the raw tool-input dict.

Both methods use ``temperature=0`` for reproducibility and apply
``cache_control`` markers to the system prompts (and, where it pays off, the
evidence bundle) to keep latency and cost down on repeated calls.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

import anthropic
import structlog
from anthropic import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncAnthropic,
    RateLimitError,
)
from anthropic.types import Message, ToolUseBlock
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from smadp.config import ANTHROPIC_API_KEY_ENV, Config, load_config
from smadp.llm.prompts import pairwise_judge, profile_extraction

logger = structlog.get_logger(__name__)

_DEFAULT_MAX_TOKENS = 4096
_RETRY_ATTEMPTS = 4
_RETRY_WAIT_MIN_SECONDS = 1.0
_RETRY_WAIT_MAX_SECONDS = 30.0


class LLMError(RuntimeError):
    """Raised when the LLM call cannot be turned into a structured tool result."""


def _is_retryable_status(exc: BaseException) -> bool:
    if isinstance(exc, (APITimeoutError, APIConnectionError, RateLimitError)):
        return True
    if isinstance(exc, APIStatusError):
        return 500 <= exc.status_code < 600
    return False


@dataclass(frozen=True)
class StructuredCallResult:
    """Outcome of a structured (tool-use) Anthropic call."""

    tool_input: dict[str, Any]
    """The arguments the model passed to the structured-output tool."""

    raw_response: Message
    """The raw SDK response for callers that want token usage / cache stats."""

    @property
    def usage(self) -> dict[str, int]:
        """Best-effort token usage extraction (input/output/cache)."""
        usage = self.raw_response.usage
        return {
            "input_tokens": getattr(usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(usage, "output_tokens", 0) or 0,
            "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
            "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
        }


class LLMClient:
    """Thin async wrapper over :class:`anthropic.AsyncAnthropic`.

    The client does *not* manage prompt versions or schemas; it merely sends
    the prompt + tool definition supplied by callers and unpacks the single
    expected ``tool_use`` block from the response.
    """

    def __init__(
        self,
        config: Config | None = None,
        *,
        client: AsyncAnthropic | None = None,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> None:
        self._config = config or load_config()
        if client is not None:
            self._client = client
        else:
            api_key = self._config.anthropic_api_key
            if not api_key:
                raise LLMError(
                    f"No Anthropic API key configured. Set ${ANTHROPIC_API_KEY_ENV} "
                    "or pass an explicit client."
                )
            self._client = AsyncAnthropic(api_key=api_key)
        self._max_tokens = max_tokens

    @property
    def model_id(self) -> str:
        """The model identifier used for all calls (from Config)."""
        return self._config.model_id

    @property
    def model_name(self) -> str:
        """Display name for the model, surfaced in Verdict.model.name."""
        return self._config.model_name

    async def extract_profile(
        self,
        payload: profile_extraction.ProfileExtractionInput,
    ) -> StructuredCallResult:
        """Run the profile-extraction prompt and return the structured tool input."""
        system_blocks: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": profile_extraction.SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        user_text = profile_extraction.build_user_message(payload)
        tool: dict[str, Any] = {
            "name": profile_extraction.TOOL_NAME,
            "description": profile_extraction.TOOL_DESCRIPTION,
            "input_schema": profile_extraction.TOOL_INPUT_SCHEMA,
        }
        return await self._call_tool(
            system=system_blocks,
            user_text=user_text,
            tool=tool,
            tool_choice_name=profile_extraction.TOOL_NAME,
            log_event="llm.extract_profile",
            log_context={
                "slug": payload.slug,
                "evidence_count": len(payload.evidence),
                "prompt_version": profile_extraction.VERSION,
            },
        )

    async def judge_pair(
        self,
        payload: pairwise_judge.JudgeInput,
    ) -> StructuredCallResult:
        """Run the pairwise judge prompt and return the structured tool input."""
        system_blocks: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": pairwise_judge.SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        user_text = pairwise_judge.build_user_message(payload)
        tool = {
            "name": pairwise_judge.TOOL_NAME,
            "description": pairwise_judge.TOOL_DESCRIPTION,
            "input_schema": pairwise_judge.TOOL_INPUT_SCHEMA,
        }
        return await self._call_tool(
            system=system_blocks,
            user_text=user_text,
            tool=tool,
            tool_choice_name=pairwise_judge.TOOL_NAME,
            log_event="llm.judge_pair",
            log_context={"prompt_version": pairwise_judge.VERSION},
        )

    async def _call_tool(
        self,
        *,
        system: list[dict[str, Any]],
        user_text: str,
        tool: dict[str, Any],
        tool_choice_name: str,
        log_event: str,
        log_context: dict[str, Any],
    ) -> StructuredCallResult:
        """Issue one tool-use call and unpack the single expected tool_use block."""
        # Cache the rubric/evidence portion of the user message too: the
        # cache_control marker on the LAST text block of a turn caches the
        # cumulative prefix up to that point.
        user_blocks: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": user_text,
                "cache_control": {"type": "ephemeral"},
            }
        ]

        @retry(
            retry=retry_if_exception_type(
                (APITimeoutError, APIConnectionError, RateLimitError, APIStatusError)
            ),
            stop=stop_after_attempt(_RETRY_ATTEMPTS),
            wait=wait_exponential(
                multiplier=1,
                min=_RETRY_WAIT_MIN_SECONDS,
                max=_RETRY_WAIT_MAX_SECONDS,
            ),
            reraise=True,
        )
        async def _send() -> Message:
            try:
                return await self._client.messages.create(
                    model=self.model_id,
                    max_tokens=self._max_tokens,
                    temperature=0.0,
                    system=cast(Any, system),
                    tools=cast(Any, [tool]),
                    tool_choice=cast(
                        Any, {"type": "tool", "name": tool_choice_name}
                    ),
                    messages=[{"role": "user", "content": cast(Any, user_blocks)}],
                )
            except APIStatusError as exc:
                # Only retry server-side errors; surface 4xx immediately.
                if not _is_retryable_status(exc):
                    raise
                raise

        try:
            response = await _send()
        except anthropic.AnthropicError as exc:
            logger.error(log_event + ".failed", error=str(exc), **log_context)
            raise LLMError(f"Anthropic call failed: {exc}") from exc

        tool_input = _extract_tool_input(response, tool_choice_name)
        logger.info(
            log_event + ".ok",
            stop_reason=response.stop_reason,
            input_tokens=getattr(response.usage, "input_tokens", 0),
            output_tokens=getattr(response.usage, "output_tokens", 0),
            cache_read_input_tokens=getattr(response.usage, "cache_read_input_tokens", 0),
            **log_context,
        )
        return StructuredCallResult(tool_input=tool_input, raw_response=response)


def _extract_tool_input(response: Message, expected_tool_name: str) -> dict[str, Any]:
    """Find the single tool_use block matching ``expected_tool_name`` and return its input."""
    matches: list[ToolUseBlock] = [
        block
        for block in response.content
        if isinstance(block, ToolUseBlock) and block.name == expected_tool_name
    ]
    if not matches:
        raise LLMError(
            f"Model did not call tool {expected_tool_name!r}; stop_reason={response.stop_reason}"
        )
    if len(matches) > 1:
        raise LLMError(
            f"Model called tool {expected_tool_name!r} {len(matches)} times; expected exactly one."
        )
    raw = matches[0].input
    if isinstance(raw, dict):
        return cast(dict[str, Any], raw)
    if isinstance(raw, str):
        try:
            return cast(dict[str, Any], json.loads(raw))
        except json.JSONDecodeError as exc:
            raise LLMError(f"Tool input was a string but not valid JSON: {exc}") from exc
    raise LLMError(f"Tool input had unexpected type: {type(raw).__name__}")
