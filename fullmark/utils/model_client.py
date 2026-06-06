"""
fullmark/utils/model_client.py
-------------------------------
LLM provider fallback chain for the Compiler Agent.

Priority (from .env):
  PRIMARY    → Gemini direct (GEMINI_API_KEY)
  FALLBACK_1 → Any OpenAI-compatible provider (OPENAI_API_KEY + OPENAI_BASE_URL)
  FALLBACK_2 → Ollama local (OLLAMA_BASE_URL — no key needed)
  FALLBACK_3 → None (returns None, caller falls back to mechanical formatting)

Usage:
    from fullmark.utils.model_client import ModelClient
    client = ModelClient()
    result = client.complete("Your prompt here")
    if result is None:
        # use fallback mechanical formatter
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class ModelClient:
    """
    Unified LLM client that tries providers in priority order.

    Reads configuration from environment variables (loaded from ``.env``).
    Never raises — returns ``None`` if no provider is available.
    """

    def __init__(self) -> None:
        self._primary   = os.getenv("COMPILER_PRIMARY", "gemini").lower()
        self._fallback1 = os.getenv("COMPILER_FALLBACK_1", "openai_compatible").lower()
        self._fallback2 = os.getenv("COMPILER_FALLBACK_2", "ollama").lower()

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def complete(self, prompt: str, system: str | None = None) -> Optional[str]:
        """
        Send *prompt* to the best available LLM and return the response text.

        Args:
            prompt: User message / content to process.
            system: Optional system prompt.

        Returns:
            Response string, or ``None`` if no provider is available.
        """
        chain = [self._primary, self._fallback1, self._fallback2]
        for provider in chain:
            try:
                result = self._call(provider, prompt, system)
                if result is not None:
                    return result
            except Exception as exc:
                logger.warning("Provider %r failed: %s", provider, exc)

        warn = os.getenv("COMPILER_WARN_ON_LIMIT", "true").lower() == "true"
        if warn:
            logger.warning(
                "No LLM provider available. "
                "Set GEMINI_API_KEY, OPENAI_API_KEY, or ensure Ollama is running. "
                "Output will be uncompiled."
            )
        return None

    # ──────────────────────────────────────────────────────────────────────────
    # Internal dispatchers
    # ──────────────────────────────────────────────────────────────────────────

    def _call(self, provider: str, prompt: str, system: str | None) -> Optional[str]:
        if provider == "gemini":
            return self._call_gemini(prompt, system)
        if provider == "openai_compatible":
            return self._call_openai_compatible(prompt, system)
        if provider == "ollama":
            return self._call_ollama(prompt, system)
        logger.debug("Unknown provider %r — skipping", provider)
        return None

    def _call_gemini(self, prompt: str, system: str | None) -> Optional[str]:
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key or api_key == "your_key_here":
            return None
        try:
            import google.generativeai as genai  # type: ignore
            genai.configure(api_key=api_key)
            model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
            model = genai.GenerativeModel(model_name)
            full_prompt = f"{system}\n\n{prompt}" if system else prompt
            response = model.generate_content(full_prompt)
            return response.text
        except ImportError:
            logger.debug("google-generativeai not installed — skipping Gemini")
            return None

    def _call_openai_compatible(self, prompt: str, system: str | None) -> Optional[str]:
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key or api_key == "your_key_here":
            return None
        try:
            from openai import OpenAI  # type: ignore
            base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
            model    = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            client   = OpenAI(api_key=api_key, base_url=base_url)
            messages: list[dict] = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=4096,
            )
            return response.choices[0].message.content
        except ImportError:
            logger.debug("openai package not installed — skipping OpenAI-compatible")
            return None

    def _call_ollama(self, prompt: str, system: str | None) -> Optional[str]:
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        model    = os.getenv("OLLAMA_MODEL", "mistral")
        try:
            import ollama as _ollama  # type: ignore
            messages: list[dict] = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            response = _ollama.Client(host=base_url).chat(
                model=model,
                messages=messages,
            )
            return response["message"]["content"]
        except ImportError:
            logger.debug("ollama package not installed — skipping Ollama")
            return None
        except Exception as exc:
            logger.debug("Ollama call failed: %s", exc)
            return None
