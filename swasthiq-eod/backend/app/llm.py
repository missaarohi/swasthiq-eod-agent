"""Thin LLM client. Only the narrative layer uses it; reconcile.py never imports this."""
import httpx

from . import config


class LLMError(Exception):
    """Network problem, non-200 status, or an unreadable provider response."""


class AnthropicClient:
    URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key, model=None, timeout=None):
        self.api_key = api_key
        self.model = model or config.LLM_MODEL
        self.timeout = timeout or config.LLM_TIMEOUT_SECONDS

    def complete(self, system, user):
        try:
            r = httpx.post(
                self.URL,
                headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": self.model, "max_tokens": 500, "temperature": 0.3,
                      "system": system, "messages": [{"role": "user", "content": user}]},
                timeout=self.timeout,
            )
        except httpx.HTTPError as e:
            raise LLMError(f"LLM request failed: {type(e).__name__}") from e
        if r.status_code != 200:
            raise LLMError(f"LLM returned HTTP {r.status_code}")
        try:
            blocks = r.json()["content"]
            return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            raise LLMError("LLM response was not in the expected format") from e


def default_llm():
    return AnthropicClient(config.ANTHROPIC_API_KEY) if config.ANTHROPIC_API_KEY else None
