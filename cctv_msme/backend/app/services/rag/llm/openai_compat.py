"""OpenAI-compatible LLM client (OpenAI / Groq / Ollama / LM Studio)."""
from __future__ import annotations

import json
import logging
import re

from app.services.rag.llm.base import LLMClient

logger = logging.getLogger(__name__)


class OpenAICompatClient(LLMClient):
    def __init__(self, api_key: str, base_url: str, model: str, temperature: float = 0.2):
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key or "not-set", base_url=base_url or None)
        self._model = model
        self._temperature = temperature
        self._label = base_url.split("//")[-1].split("/")[0] if base_url else "openai"

    @property
    def provider(self) -> str:
        return f"openai-compatible ({self._label})"

    def chat(self, system: str, user: str, temperature: float | None = None) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=self._temperature if temperature is None else temperature,
        )
        return (resp.choices[0].message.content or "").strip()

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
            logger.warning("LLM returned non-JSON for JSON request: %.200s", raw)
            return {}
