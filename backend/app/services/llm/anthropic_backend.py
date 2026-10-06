"""Claude via the official Anthropic SDK."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import anthropic

from app.core.config import Settings
from app.core.errors import ConfigurationError, LLMError
from app.services.llm.base import PromptedBackend, SchemaT

logger = logging.getLogger(__name__)

# Server-side refusal fallback: if the primary model declines, the API re-runs the request on
# Anthropic's recommended fallback model inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


@contextmanager
def _translate_errors() -> Iterator[None]:
    try:
        yield
    except anthropic.AuthenticationError as exc:
        raise LLMError("The Anthropic API key was rejected. Check ANTHROPIC_API_KEY.", code="llm_auth") from exc
    except anthropic.PermissionDeniedError as exc:
        raise LLMError("The Anthropic API key lacks access to this model.", code="llm_auth") from exc
    except anthropic.NotFoundError as exc:
        raise LLMError("The configured Claude model was not found. Check ANTHROPIC_MODEL.") from exc
    except anthropic.RateLimitError as exc:
        raise LLMError(
            "The LLM provider is rate limiting requests. Please retry shortly.", code="llm_rate_limited"
        ) from exc
    except anthropic.BadRequestError as exc:
        raise LLMError(f"The LLM provider rejected the request: {exc.message}") from exc
    except anthropic.APIStatusError as exc:
        raise LLMError(f"The LLM provider returned an error ({exc.status_code}). Please retry.") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMError(
            "Could not reach the LLM provider. Check your network connection.", code="llm_unavailable"
        ) from exc


class AnthropicBackend(PromptedBackend):
    name = "anthropic"

    def __init__(self, settings: Settings):
        if not settings.anthropic_api_key:
            raise ConfigurationError("LLM_PROVIDER=anthropic requires ANTHROPIC_API_KEY.")
        self.client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key, timeout=settings.llm_timeout_seconds, max_retries=2
        )
        self.model = settings.anthropic_model
        self.effort = settings.anthropic_effort
        self.fallbacks = settings.anthropic_fallbacks

    def _request_options(self) -> dict[str, Any]:
        options: dict[str, Any] = {"model": self.model}
        if self.effort:
            options["output_config"] = {"effort": self.effort}
        if self.fallbacks:
            options["betas"] = [FALLBACK_BETA]
            options["fallbacks"] = "default"
        return options

    def _stream_text(self, system: str, messages: list[dict[str, str]], max_tokens: int) -> Iterator[str]:
        with (
            _translate_errors(),
            self.client.beta.messages.stream(
                max_tokens=max_tokens, system=system, messages=messages, **self._request_options()
            ) as stream,
        ):
            yield from stream.text_stream
            final = stream.get_final_message()
        if final.stop_reason == "refusal":
            raise LLMError("The model declined to answer this request.", code="llm_refusal")
        if final.stop_reason == "max_tokens":
            yield "\n\n*(Answer truncated — reached the maximum response length.)*"

    def _structured(self, system: str, user: str, schema: type[SchemaT], max_tokens: int) -> SchemaT:
        with _translate_errors():
            response = self.client.beta.messages.parse(
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=schema,
                **self._request_options(),
            )
        if response.stop_reason == "refusal":
            raise LLMError("The model declined to generate this content.", code="llm_refusal")
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            raise LLMError("The model response was incomplete. Try requesting fewer items.")
        return response.parsed_output
