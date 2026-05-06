"""Async OpenAI client wrapper with retries and tool-calling.

Two public entry points are exposed:

- :meth:`LLMClient.extract_profile` — single tool-call against the
  profile-extraction prompt; returns the raw tool-arguments dict.
- :meth:`LLMClient.judge_pair` — single tool-call against the pairwise
  judge prompt; returns the raw tool-arguments dict.

Both methods use ``temperature=0`` for reproducibility. OpenAI applies
prompt caching automatically to prefixes of >=1024 tokens, so no
explicit cache markers are required.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

import openai
import structlog
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    RateLimitError,
)
from openai.types.chat import ChatCompletion
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from smadp.config import OPENAI_API_KEY_ENV, Config, load_config
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
    """Outcome of a structured (tool-call) OpenAI call."""

    tool_input: dict[str, Any]
    """The arguments the model passed to the structured-output tool."""

    raw_response: ChatCompletion
    """The raw SDK response for callers that want token usage / cache stats."""

    @property
    def usage(self) -> dict[str, int]:
        """Best-effort token usage extraction (input/output/cache)."""
        usage = self.raw_response.usage
        if usage is None:
            return {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            }
        prompt_details = getattr(usage, "prompt_tokens_details", None)
        cached = getattr(prompt_details, "cached_tokens", 0) if prompt_details else 0
        return {
            "input_tokens": getattr(usage, "prompt_tokens", 0) or 0,
            "output_tokens": getattr(usage, "completion_tokens", 0) or 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": cached or 0,
        }


class LLMClient:
    """Thin async wrapper over :class:`openai.AsyncOpenAI`.

    The client does *not* manage prompt versions or schemas; it merely sends
    the prompt + tool definition supplied by callers and unpacks the single
    expected tool call from the response.
    """

    def __init__(
        self,
        config: Config | None = None,
        *,
        client: AsyncOpenAI | None = None,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> None:
        self._config = config or load_config()
        if client is not None:
            self._client = client
        else:
            api_key = self._config.openai_api_key
            if not api_key:
                raise LLMError(
                    f"No OpenAI API key configured. Set ${OPENAI_API_KEY_ENV} "
                    "or pass an explicit client."
                )
            self._client = AsyncOpenAI(api_key=api_key)
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
        user_text = profile_extraction.build_user_message(payload)
        tool: dict[str, Any] = {
            "type": "function",
            "function": {
                "name": profile_extraction.TOOL_NAME,
                "description": profile_extraction.TOOL_DESCRIPTION,
                "parameters": profile_extraction.TOOL_INPUT_SCHEMA,
            },
        }
        return await self._call_tool(
            system_text=profile_extraction.SYSTEM,
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
        user_text = pairwise_judge.build_user_message(payload)
        tool: dict[str, Any] = {
            "type": "function",
            "function": {
                "name": pairwise_judge.TOOL_NAME,
                "description": pairwise_judge.TOOL_DESCRIPTION,
                "parameters": pairwise_judge.TOOL_INPUT_SCHEMA,
            },
        }
        return await self._call_tool(
            system_text=pairwise_judge.SYSTEM,
            user_text=user_text,
            tool=tool,
            tool_choice_name=pairwise_judge.TOOL_NAME,
            log_event="llm.judge_pair",
            log_context={"prompt_version": pairwise_judge.VERSION},
        )

    async def _call_tool(
        self,
        *,
        system_text: str,
        user_text: str,
        tool: dict[str, Any],
        tool_choice_name: str,
        log_event: str,
        log_context: dict[str, Any],
    ) -> StructuredCallResult:
        """Issue one tool-call and unpack the single expected tool_call."""
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ]
        tool_choice = {"type": "function", "function": {"name": tool_choice_name}}

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
        async def _send() -> ChatCompletion:
            return await self._client.chat.completions.create(
                model=self.model_id,
                max_tokens=self._max_tokens,
                temperature=0.0,
                messages=cast(Any, messages),
                tools=cast(Any, [tool]),
                tool_choice=cast(Any, tool_choice),
            )

        try:
            response = await _send()
        except openai.OpenAIError as exc:
            logger.error(log_event + ".failed", error=str(exc), **log_context)
            raise LLMError(f"OpenAI call failed: {exc}") from exc

        tool_input = _extract_tool_input(response, tool_choice_name)
        usage = response.usage
        prompt_details = getattr(usage, "prompt_tokens_details", None) if usage else None
        cached = getattr(prompt_details, "cached_tokens", 0) if prompt_details else 0
        choice = response.choices[0] if response.choices else None
        logger.info(
            log_event + ".ok",
            finish_reason=getattr(choice, "finish_reason", None),
            input_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
            cache_read_input_tokens=cached or 0,
            **log_context,
        )
        return StructuredCallResult(tool_input=tool_input, raw_response=response)


def _extract_tool_input(response: ChatCompletion, expected_tool_name: str) -> dict[str, Any]:
    """Find the single tool_call matching ``expected_tool_name`` and return its arguments."""
    if not response.choices:
        raise LLMError(f"Model returned no choices; cannot extract tool {expected_tool_name!r}")
    message = response.choices[0].message
    finish_reason = response.choices[0].finish_reason
    tool_calls = message.tool_calls or []
    matches = [tc for tc in tool_calls if tc.function and tc.function.name == expected_tool_name]
    if not matches:
        raise LLMError(
            f"Model did not call tool {expected_tool_name!r}; finish_reason={finish_reason}"
        )
    if len(matches) > 1:
        raise LLMError(
            f"Model called tool {expected_tool_name!r} {len(matches)} times; expected exactly one."
        )
    raw = matches[0].function.arguments
    if not raw:
        raise LLMError(f"Tool {expected_tool_name!r} returned empty arguments")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Tool arguments were not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LLMError(f"Tool arguments parsed to {type(parsed).__name__}, expected dict")
    return cast(dict[str, Any], parsed)
