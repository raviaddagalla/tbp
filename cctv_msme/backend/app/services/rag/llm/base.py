"""Pluggable LLM backend.

LLMClient interface so the model provider can be swapped without touching
business logic. Providers: openai-compatible (OpenAI, Groq, Ollama, LM
Studio via LLM_BASE_URL), Anthropic, and an offline MockLLM.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class LLMClient(ABC):
    @property
    @abstractmethod
    def provider(self) -> str: ...

    @abstractmethod
    def chat(self, system: str, user: str, temperature: float | None = None) -> str:
        """Single-turn completion. May raise on transport errors."""

    @abstractmethod
    def chat_json(self, system: str, user: str, temperature: float | None = None) -> dict:
        """Completion parsed as JSON object (best-effort)."""
