from __future__ import annotations

import os
from typing import Any

PROVIDER_PRIORITY: list[tuple[str, str, str]] = [
    ("openai", "OPENAI_API_KEY", "gpt-4o-mini"),
    ("anthropic", "ANTHROPIC_API_KEY", "anthropic/claude-haiku-4-5"),
    ("gemini", "GEMINI_API_KEY", "gemini/gemini-1.5-flash"),
]

ANTHROPIC_FALLBACK_MODEL: str = "anthropic/claude-3-5-haiku-latest"


def detect_provider() -> tuple[str, str] | None:
    """Return (provider_name, model_string) for the first configured key, or None."""
    for name, env_var, model in PROVIDER_PRIORITY:
        if os.getenv(env_var):
            return name, model
    return None


def build_llm() -> Any | None:
    """Construct a ChatLiteLLM instance for the detected provider, or None."""
    detected = detect_provider()
    if not detected:
        return None
    _, model = detected

    from langchain_community.chat_models import ChatLiteLLM

    return ChatLiteLLM(model=model, temperature=0)
