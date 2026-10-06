"""Any OpenAI-compatible chat endpoint: OpenAI, DeepSeek, Qwen (DashScope), Moonshot, Ollama, vLLM, LM Studio…"""

import json
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager

import openai
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import ConfigurationError, LLMError
from app.services.llm.base import PromptedBackend, SchemaT

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def extract_json_object(text: str) -> dict:
    """Parse a JSON object from model output that may be wrapped in prose or Markdown fences."""
    cleaned = _FENCE_RE.sub("", text.strip())
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise
        value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise json.JSONDecodeError("Expected a JSON object", cleaned, 0)
    return value


@contextmanager
def _translate_errors() -> Iterator[None]:
    try:
        yield
    except openai.AuthenticationError as exc:
        raise LLMError("The LLM API key was rejected. Check OPENAI_API_KEY.", code="llm_auth") from exc
    except openai.NotFoundError as exc:
        raise LLMError("The configured model was not found. Check OPENAI_MODEL / OPENAI_BASE_URL.") from exc
    except openai.RateLimitError as exc:
        raise LLMError(
            "The LLM provider is rate limiting requests. Please retry shortly.", code="llm_rate_limited"
        ) from exc
    except openai.APIStatusError as exc:
        raise LLMError(f"The LLM provider returned an error ({exc.status_code}). Please retry.") from exc
    except openai.APIConnectionError as exc:
        raise LLMError("Could not reach the LLM provider. Check OPENAI_BASE_URL.", code="llm_unavailable") from exc


class OpenAICompatibleBackend(PromptedBackend):
    name = "openai"
    structured_max_tokens = 8000

    def __init__(self, settings: Settings):
        if not settings.openai_model:
            raise ConfigurationError("LLM_PROVIDER=openai requires OPENAI_MODEL (e.g. deepseek-chat, qwen-plus).")
        self.client = openai.OpenAI(
            # Local servers such as Ollama ignore the key but the SDK requires a value.
            api_key=settings.openai_api_key or "not-needed",
            base_url=settings.openai_base_url,
            timeout=settings.llm_timeout_seconds,
            max_retries=2,
        )
        self.model = settings.openai_model

    def _stream_text(self, system: str, messages: list[dict[str, str]], max_tokens: int) -> Iterator[str]:
        with _translate_errors():
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, *messages],
                stream=True,
                temperature=0.2,
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

    def _complete(self, messages: list[dict[str, str]], json_mode: bool, max_tokens: int) -> str:
        kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
        response = self.client.chat.completions.create(
            model=self.model, messages=messages, temperature=0.4, max_tokens=max_tokens, **kwargs
        )
        return response.choices[0].message.content or ""

    def _structured(self, system: str, user: str, schema: type[SchemaT], max_tokens: int) -> SchemaT:
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        messages = [
            {
                "role": "system",
                "content": f"{system}\n\nRespond with a single JSON object that conforms to this JSON Schema, "
                f"with no extra text:\n{schema_json}",
            },
            {"role": "user", "content": user},
        ]
        last_error: Exception | None = None
        json_mode = True
        for _attempt in range(3):
            with _translate_errors():
                try:
                    raw = self._complete(messages, json_mode, max_tokens)
                except openai.BadRequestError:
                    if not json_mode:
                        raise
                    json_mode = False  # some compatible servers don't implement response_format
                    raw = self._complete(messages, json_mode, max_tokens)
            try:
                return schema.model_validate(extract_json_object(raw))
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                logger.warning("Structured output failed validation, retrying: %s", exc)
                messages += [
                    {"role": "assistant", "content": raw},
                    {
                        "role": "user",
                        "content": f"That response was not valid ({exc}). Return only the corrected JSON.",
                    },
                ]
        raise LLMError(f"The model did not return valid structured output: {last_error}")
