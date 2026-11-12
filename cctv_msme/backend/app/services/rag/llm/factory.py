"""LLM factory: picks provider from settings with safe fallbacks."""
from __future__ import annotations

import logging
from functools import lru_cache

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache
def get_llm():
    settings = get_settings()
    provider = settings.llm_provider.lower()
    api_key = settings.llm_api_key.strip()

    if provider in ("groq", "openai", "ollama", "lmstudio", "local") and api_key or provider == "ollama":
        from app.services.rag.llm.openai_compat import OpenAICompatClient

        try:
            client = OpenAICompatClient(
                api_key=api_key,
                base_url=settings.llm_base_url,
                model=settings.llm_model,
                temperature=settings.llm_temperature,
            )
            logger.info("LLM provider: %s (%s)", client.provider, settings.llm_model)
            return client
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to init OpenAI-compatible client (%s); falling back to mock.", exc)

    if provider == "anthropic" and api_key:
        try:
            from app.services.rag.llm.anthropic_client import AnthropicClient

            client = AnthropicClient(api_key=api_key, model=settings.llm_model, temperature=settings.llm_temperature)
            logger.info("LLM provider: anthropic (%s)", settings.llm_model)
            return client
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to init Anthropic client (%s); falling back to mock.", exc)

    if provider == "mock" or not api_key:
        from app.services.rag.llm.mock import MockLLM

        if not api_key and provider != "mock":
            logger.warning("LLM_PROVIDER=%s but LLM_API_KEY is empty; using offline MockLLM.", provider)
        else:
            logger.info("LLM provider: mock (offline mode)")
        return MockLLM()

    raise RuntimeError(f"Unknown LLM provider: {provider}")
