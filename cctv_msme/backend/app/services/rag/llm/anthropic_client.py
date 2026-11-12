"""Anthropic LLM client."""
from __future__ import annotations

import json
import logging
import re

from app.services.rag.llm.base import LLMClient

logger = logging.getLogger(__name__)


class AnthropicClient(LLMClient):
    def __init__(self, api_key: str, model: str, temperature: float = 0.2):
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key)
        self._model = model
        self._temperature = temperature

    @property
    def provider(self) -> str:
        return "anthropic"

    def chat(self, system: str, user: str, temperature: float | None = None) -> str:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=1500,
            system=system,
            temperature=self._temperature if temperature is None else temperature,
            messages=[{"role": "user", "content": user}],
        )
        parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
        return "".join(parts).strip()

    def chat_json(self, system: str, user: str, temperature: float | None = None) -> dict:
        raw = self.chat(
            system + "\nRespond with ONLY a valid JSON object, no markdown, no commentary.",
            user,
            temperature=0.0 if temperature is None else temperature,
        )
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            logger.warning("Anthropic returned non-JSON: %.200s", raw)
            return {}
