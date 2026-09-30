"""LLM provider abstraction.

Only providers that actually generate text live here. The offline path is a
separate, deterministic writer in script.py; it does not pretend to be an LLM.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..errors import ProviderError
from ..logging_setup import get_logger

log = get_logger("studio.api")


@dataclass
class LLMResult:
    data: dict
    input_tokens: int
    output_tokens: int
    model: str


class LLMProvider(ABC):
    name = "base"

    @abstractmethod
    def generate_json(self, *, system: str, prompt: str, schema: dict, max_tokens: int = 16000) -> LLMResult:
        ...


class AnthropicLLM(LLMProvider):
    """Claude via the official Anthropic SDK, with JSON-schema structured output.

    * thinking stays at the model default (adaptive); depth is set with `effort`
    * refusals are re-run server-side on Anthropic's recommended fallback model
      (`fallbacks="default"`), and a final refusal is surfaced as an error
    """
    name = "anthropic"

    def __init__(self, *, model: str, effort: str = "high", api_key: str | None = None, client=None):
        if client is None:
            if not api_key:
                raise ProviderError("ANTHROPIC_API_KEY is not set",
                                    hint="add it to .env, or set content.llm_provider: offline")
            try:
                import anthropic
            except ImportError as exc:
                raise ProviderError("The anthropic package is not installed", hint="pip install anthropic") from exc
            client = anthropic.Anthropic(api_key=api_key, max_retries=2, timeout=300.0)
        self.client = client
        self.model = model
        self.effort = effort

    def generate_json(self, *, system: str, prompt: str, schema: dict, max_tokens: int = 16000) -> LLMResult:
        try:
            import anthropic
            api_errors = (anthropic.APIStatusError, anthropic.APIConnectionError)
        except ImportError:  # a fake client in tests
            anthropic, api_errors = None, ()
        try:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
        except api_errors as exc:  # type: ignore[misc]
            status = getattr(exc, "status_code", None)
            retryable = status is None or status == 429 or status >= 500
            raise ProviderError(f"Anthropic API error ({status or 'connection'}): {exc.__class__.__name__}",
                                retryable=retryable) from exc

        if response.stop_reason == "refusal":
            category = getattr(getattr(response, "stop_details", None), "category", None)
            raise ProviderError(f"The model declined this request (category: {category})",
                                hint="review the topic; the script was not generated")
        if response.stop_reason == "max_tokens":
            raise ProviderError("The model hit max_tokens before finishing the JSON", retryable=True)
        text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderError("The model returned invalid JSON", retryable=True) from exc
        usage = response.usage
        log.info("anthropic %s: %s in / %s out tokens", self.model, usage.input_tokens, usage.output_tokens)
        return LLMResult(data=data, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                         model=getattr(response, "model", self.model))


def build_llm(ctx) -> LLMProvider | None:
    name = ctx.cfg.get("content.llm_provider")
    if name == "offline":
        return None
    if name == "anthropic":
        return AnthropicLLM(model=ctx.cfg.get("content.anthropic_model"), api_key=ctx.cfg.secret("ANTHROPIC_API_KEY"))
    raise ProviderError(f"Unknown LLM provider {name!r}")
