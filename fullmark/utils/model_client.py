"""
fullmark/utils/model_client.py
-------------------------------
LLM provider fallback chain for the Compiler Agent.

Configured via COMPILER_CHAIN in .env (comma-separated provider names).
Each provider is tried in order; the first successful response is returned.
If all fail, returns None and the caller uses mechanical formatting.

Provider names supported in COMPILER_CHAIN:
  Free tier  : openrouter_free, groq, cerebras, nvidia, gemini, mistral_free,
               cohere, together, inception, morph, replicate
  Low cost   : deepseek, fireworks, mistral, openai
  Premium    : anthropic, gemini_pro
  Local      : ollama

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

_PLACEHOLDER = "your_key_here"

# Maps provider name → (env_prefix, default_base_url, default_model)
# All of these use the OpenAI-compatible SDK.
_OPENAI_COMPAT_PROVIDERS: dict[str, tuple[str, str, str]] = {
    "openrouter":      ("OPENROUTER_",  "https://openrouter.ai/api/v1",                     "google/gemini-2.0-flash-exp:free"),
    "openrouter_free": ("OPENROUTER_",  "https://openrouter.ai/api/v1",                     "google/gemini-2.0-flash-exp:free"),
    "groq":            ("GROQ_",        "https://api.groq.com/openai/v1",                   "llama-3.3-70b-versatile"),
    "cerebras":        ("CEREBRAS_",    "https://api.cerebras.ai/v1",                       "llama3.1-70b"),
    "nvidia":          ("NVIDIA_",      "https://integrate.api.nvidia.com/v1",              "meta/llama-3.3-70b-instruct"),
    "mistral":         ("MISTRAL_",     "https://api.mistral.ai/v1",                        "open-mixtral-8x7b"),
    "mistral_free":    ("MISTRAL_",     "https://api.mistral.ai/v1",                        "open-mixtral-8x7b"),
    "deepseek":        ("DEEPSEEK_",    "https://api.deepseek.com/v1",                      "deepseek-chat"),
    "together":        ("TOGETHER_",    "https://api.together.xyz/v1",                      "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free"),
    "fireworks":       ("FIREWORKS_",   "https://api.fireworks.ai/inference/v1",            "accounts/fireworks/models/llama-v3p3-70b-instruct"),
    "openai":          ("OPENAI_",      "https://api.openai.com/v1",                        "gpt-4o-mini"),
    "cohere":          ("COHERE_",      "https://api.cohere.com/compatibility/v1",          "command-r"),
    "inception":       ("INCEPTION_",   "https://api.inceptionlabs.ai/v1",                  "mercury-coder-small"),
    "morph":           ("MORPH_",       "https://api.morphllm.com/v1",                      "morph-v2"),
    "replicate":       ("REPLICATE_",   "https://openai-compat.replicate.com/v1",           "meta/meta-llama-3-70b-instruct"),
}


class ModelClient:
    """
    Unified LLM client that walks the COMPILER_CHAIN until one succeeds.

    Reads all configuration from environment variables (loaded from ``.env``).
    Never raises — returns ``None`` if no provider is available.

    Rate-limit handling
    -------------------
    When a provider returns a 429 / rate-limit / quota error, the client
    waits ``PROVIDER_RETRY_DELAY`` seconds (default 5) and retries the same
    provider up to ``PROVIDER_MAX_RETRIES`` times (default 2) before moving
    to the next provider in the chain.
    """

    def __init__(self) -> None:
        self._warn_duplicate_env_keys()
        chain_env = os.getenv("COMPILER_CHAIN", "")
        if chain_env:
            self._chain = [p.strip().lower() for p in chain_env.split(",") if p.strip()]
        else:
            # Legacy single-key fallback for backward compatibility
            self._chain = [
                os.getenv("COMPILER_PRIMARY", "gemini").lower(),
                os.getenv("COMPILER_FALLBACK_1", "openrouter_free").lower(),
                os.getenv("COMPILER_FALLBACK_2", "ollama").lower(),
            ]
        self._retry_delay = float(os.getenv("PROVIDER_RETRY_DELAY", "5"))
        self._max_retries = int(os.getenv("PROVIDER_MAX_RETRIES", "2"))

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _warn_duplicate_env_keys() -> None:
        """
        Warn if .env contains multiple active (non-commented) COMPILER_CHAIN or
        VISION_CHAIN assignments.  python-dotenv silently uses the FIRST value,
        so duplicates cause the wrong chain to run with no error message.
        """
        env_path = os.path.join(os.getcwd(), ".env")
        if not os.path.exists(env_path):
            return
        try:
            with open(env_path, encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return
        for key in ("COMPILER_CHAIN", "VISION_CHAIN"):
            active = [l.strip() for l in lines
                      if l.strip().startswith(f"{key}=") and not l.strip().startswith("#")]
            if len(active) > 1:
                logger.warning(
                    ".env contains %d active '%s=' lines — python-dotenv uses only the FIRST. "
                    "Remove the duplicates to avoid using the wrong provider chain. "
                    "Active lines found: %s",
                    len(active), key, active,
                )

    def complete(self, prompt: str, system: str | None = None) -> Optional[str]:
        """
        Send *prompt* to the best available LLM and return the response text.

        Args:
            prompt: User message / content to process.
            system: Optional system prompt.

        Returns:
            Response string, or ``None`` if no provider is available.
        """
        for provider in self._chain:
            logger.debug("Trying provider: %s", provider)
            result = self._try_with_retry(provider, prompt, system)
            if result is not None:
                return result

        if os.getenv("COMPILER_WARN_ON_LIMIT", "true").lower() == "true":
            logger.warning(
                "No LLM provider succeeded. Output will use mechanical formatting. "
                "Check your COMPILER_CHAIN and API keys in .env."
            )
        return None

    def _try_with_retry(
        self, provider: str, prompt: str, system: str | None
    ) -> Optional[str]:
        """
        Attempt *provider* up to (1 + PROVIDER_MAX_RETRIES) times.

        On a rate-limit / 429 error, waits PROVIDER_RETRY_DELAY seconds and
        retries the same provider. Any other exception moves to the next
        provider immediately.
        """
        import time

        attempts = 0
        max_attempts = 1 + self._max_retries

        while attempts < max_attempts:
            try:
                result = self._dispatch(provider, prompt, system)
                if result is not None:
                    logger.debug("Provider %s succeeded (attempt %d)", provider, attempts + 1)
                    return result
                return None  # Provider returned None (no key / not configured)
            except Exception as exc:
                exc_str = str(exc).lower()
                is_ratelimit = any(
                    kw in exc_str for kw in ("429", "rate limit", "rate_limit", "quota", "too many requests")
                )
                attempts += 1
                if is_ratelimit and attempts < max_attempts:
                    wait = self._retry_delay * attempts  # exponential: 5s, 10s
                    logger.warning(
                        "Provider %r rate-limited (attempt %d/%d) — waiting %.0fs",
                        provider, attempts, max_attempts, wait,
                    )
                    time.sleep(wait)
                else:
                    logger.warning("Provider %r failed: %s", provider, exc)
                    return None

        return None

    def describe_image(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> Optional[str]:
        """
        Send an image to a vision-capable LLM and return a text description.

        Tries each provider in VISION_CHAIN (env var, comma-separated).
        Falls back to COMPILER_CHAIN providers that support vision.
        Returns ``None`` if no vision provider is available.

        Args:
            image_bytes: Raw image bytes.
            mime_type: MIME type of the image (e.g. ``"image/jpeg"``).

        Returns:
            Description string, or ``None`` if no provider can handle vision.
        """
        import base64
        b64 = base64.b64encode(image_bytes).decode()
        data_uri = f"data:{mime_type};base64,{b64}"

        vision_chain_env = os.getenv("VISION_CHAIN", "")
        if vision_chain_env:
            vision_chain = [p.strip().lower() for p in vision_chain_env.split(",") if p.strip()]
        else:
            # Default vision providers in priority order
            vision_chain = ["gemini", "gemini_free", "openai", "anthropic", "openrouter_free"]

        system = (
            "You are a visual content analyst. Describe the image in detail, "
            "extracting all text, numbers, labels, relationships, and visual meaning. "
            "Format as Markdown: use ## headings for major sections, bullet points for lists, "
            "and GFM tables for any tabular data you observe. Be thorough — no data should be omitted."
        )

        for provider in vision_chain:
            logger.debug("Trying vision provider: %s", provider)
            result = self._try_vision_with_retry(provider, data_uri, mime_type, system)
            if result is not None:
                return result

        logger.warning("No vision LLM provider succeeded — will use base64 embedding fallback")
        return None

    def _try_vision_with_retry(
        self, provider: str, data_uri: str, mime_type: str, system: str | None
    ) -> Optional[str]:
        """Attempt vision call with rate-limit retry logic."""
        import time

        attempts = 0
        max_attempts = 1 + self._max_retries

        while attempts < max_attempts:
            try:
                result = self._dispatch_vision(provider, data_uri, mime_type, system)
                if result is not None:
                    logger.debug("Vision provider %s succeeded (attempt %d)", provider, attempts + 1)
                    return result
                return None
            except Exception as exc:
                exc_str = str(exc).lower()
                is_ratelimit = any(
                    kw in exc_str for kw in ("429", "rate limit", "rate_limit", "quota", "too many requests")
                )
                attempts += 1
                if is_ratelimit and attempts < max_attempts:
                    wait = self._retry_delay * attempts
                    logger.warning(
                        "Vision provider %r rate-limited (attempt %d/%d) — waiting %.0fs",
                        provider, attempts, max_attempts, wait,
                    )
                    time.sleep(wait)
                else:
                    logger.warning("Vision provider %r failed: %s", provider, exc)
                    return None

        return None

    # ──────────────────────────────────────────────────────────────────────────
    # Dispatcher
    # ──────────────────────────────────────────────────────────────────────────

    def _dispatch(self, provider: str, prompt: str, system: str | None) -> Optional[str]:
        if provider in ("gemini", "gemini_free"):
            return self._call_gemini(prompt, system, paid=False)
        if provider == "gemini_pro":
            return self._call_gemini(prompt, system, paid=True)
        if provider == "anthropic":
            return self._call_anthropic(prompt, system)
        if provider == "ollama":
            return self._call_ollama(prompt, system)
        if provider in _OPENAI_COMPAT_PROVIDERS:
            return self._call_openai_compat(provider, prompt, system)
        logger.debug("Unknown provider %r — skipping", provider)
        return None

    def _dispatch_vision(
        self,
        provider: str,
        data_uri: str,
        mime_type: str,
        system: str | None,
    ) -> Optional[str]:
        if provider in ("gemini", "gemini_free", "gemini_pro"):
            return self._call_gemini_vision(data_uri, mime_type, system)
        if provider == "anthropic":
            return self._call_anthropic_vision(data_uri, mime_type, system)
        if provider in _OPENAI_COMPAT_PROVIDERS:
            return self._call_openai_compat_vision(provider, data_uri, mime_type, system)
        if provider == "ollama":
            return self._call_ollama_vision(data_uri, mime_type, system)
        logger.debug("Provider %r does not support vision — skipping", provider)
        return None

    # ──────────────────────────────────────────────────────────────────────────
    # Gemini (google-genai SDK — new; falls back to google-generativeai — old)
    # ──────────────────────────────────────────────────────────────────────────

    def _call_gemini(self, prompt: str, system: str | None, paid: bool = False) -> Optional[str]:
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key or api_key == _PLACEHOLDER:
            return None

        if paid:
            model_names = [os.getenv("GEMINI_PRO_MODEL", "gemini-1.5-pro")]
        else:
            primary = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
            fallbacks_str = os.getenv("GEMINI_FALLBACK_MODELS", primary)
            model_names = [m.strip() for m in fallbacks_str.split(",") if m.strip()]
            if primary not in model_names:
                model_names.insert(0, primary)

        full_prompt = f"{system}\n\n{prompt}" if system else prompt

        # Try new google-genai SDK first
        try:
            import google.genai as genai_new  # type: ignore
            client = genai_new.Client(api_key=api_key)
            for model_name in model_names:
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=full_prompt,
                    )
                    return response.text
                except Exception as exc:
                    logger.debug("google-genai model %r failed: %s", model_name, exc)
            return None
        except ImportError:
            pass

        # Fallback to legacy google-generativeai SDK
        try:
            import warnings
            import google.generativeai as genai_old  # type: ignore
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                genai_old.configure(api_key=api_key)
            for model_name in model_names:
                try:
                    model = genai_old.GenerativeModel(model_name)
                    response = model.generate_content(full_prompt)
                    return response.text
                except Exception as exc:
                    logger.debug("google-generativeai model %r failed: %s", model_name, exc)
            return None
        except ImportError:
            logger.debug("Neither google-genai nor google-generativeai installed — skipping Gemini")
            return None

    # ──────────────────────────────────────────────────────────────────────────
    # Anthropic (anthropic SDK)
    # ──────────────────────────────────────────────────────────────────────────

    def _call_anthropic(self, prompt: str, system: str | None) -> Optional[str]:
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key or api_key == _PLACEHOLDER:
            return None
        try:
            import anthropic  # type: ignore
        except ImportError:
            logger.debug("anthropic package not installed — pip install anthropic")
            return None

        model = os.getenv("ANTHROPIC_MODEL", "claude-haiku-3-5-20241022")
        client = anthropic.Anthropic(api_key=api_key)
        kwargs: dict = {
            "model": model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        try:
            response = client.messages.create(**kwargs)
            return response.content[0].text
        except Exception as exc:
            logger.debug("Anthropic call failed: %s", exc)
            return None

    # ──────────────────────────────────────────────────────────────────────────
    # OpenAI-compatible (covers 15+ providers)
    # ──────────────────────────────────────────────────────────────────────────

    def _call_openai_compat(self, provider: str, prompt: str, system: str | None) -> Optional[str]:
        prefix, default_url, default_model = _OPENAI_COMPAT_PROVIDERS[provider]

        api_key  = os.getenv(f"{prefix}API_KEY", "")
        base_url = os.getenv(f"{prefix}BASE_URL", default_url)

        # For mistral_free, use the free model env var
        if provider == "mistral_free":
            model = os.getenv("MISTRAL_FREE_MODEL", default_model)
        else:
            model = os.getenv(f"{prefix}MODEL", default_model)

        if not api_key or api_key == _PLACEHOLDER:
            logger.debug("No API key for provider %r — skipping", provider)
            return None

        try:
            from openai import OpenAI  # type: ignore
        except ImportError:
            logger.debug("openai package not installed")
            return None

        client = OpenAI(api_key=api_key, base_url=base_url)
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        # For openrouter_free: rotate through free models if primary fails
        if provider == "openrouter_free":
            return self._call_openrouter_free(client, messages, model)

        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=4096,
            )
            return response.choices[0].message.content
        except Exception as exc:
            logger.debug("Provider %r model %r failed: %s", provider, model, exc)
            return None

    def _call_openrouter_free(self, client, messages: list[dict], primary_model: str) -> Optional[str]:
        """Rotate through OPENROUTER_FREE_MODELS until one succeeds."""
        free_models_str = os.getenv("OPENROUTER_FREE_MODELS", primary_model)
        models = [m.strip() for m in free_models_str.split(",") if m.strip()]
        if primary_model not in models:
            models.insert(0, primary_model)

        for model in models:
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=4096,
                )
                return response.choices[0].message.content
            except Exception as exc:
                logger.debug("OpenRouter free model %r failed: %s", model, exc)
        return None

    # ──────────────────────────────────────────────────────────────────────────
    # Ollama (local)
    # ──────────────────────────────────────────────────────────────────────────

    def _call_ollama(self, prompt: str, system: str | None) -> Optional[str]:
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        primary  = os.getenv("OLLAMA_MODEL", "mistral")
        fallbacks_str = os.getenv("OLLAMA_FALLBACK_MODELS", primary)
        models = [m.strip() for m in fallbacks_str.split(",") if m.strip()]
        if primary not in models:
            models.insert(0, primary)

        try:
            import ollama as _ollama  # type: ignore
        except ImportError:
            logger.debug("ollama package not installed — pip install ollama")
            return None

        ollama_client = _ollama.Client(host=base_url)
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        for model in models:
            try:
                response = ollama_client.chat(model=model, messages=messages)
                return response["message"]["content"]
            except Exception as exc:
                logger.debug("Ollama model %r failed: %s", model, exc)
        return None

    # ──────────────────────────────────────────────────────────────────────────
    # Vision methods
    # ──────────────────────────────────────────────────────────────────────────

    def _call_gemini_vision(
        self, data_uri: str, mime_type: str, system: str | None
    ) -> Optional[str]:
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key or api_key == _PLACEHOLDER:
            return None

        primary = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        fallbacks_str = os.getenv("GEMINI_FALLBACK_MODELS", primary)
        model_names = [m.strip() for m in fallbacks_str.split(",") if m.strip()]
        if primary not in model_names:
            model_names.insert(0, primary)

        # Extract base64 from data URI
        import base64
        b64 = data_uri.split(",", 1)[1] if "," in data_uri else data_uri
        image_bytes = base64.b64decode(b64)

        # Try new google-genai SDK
        try:
            import google.genai as genai_new  # type: ignore
            import google.genai.types as types  # type: ignore
            client = genai_new.Client(api_key=api_key)
            for model_name in model_names:
                try:
                    parts_content: list = []
                    if system:
                        parts_content.append(system)
                    parts_content.append(
                        types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
                    )
                    response = client.models.generate_content(
                        model=model_name,
                        contents=parts_content,
                    )
                    return response.text
                except Exception as exc:
                    logger.debug("gemini vision model %r failed: %s", model_name, exc)
            return None
        except ImportError:
            pass

        # Fallback to legacy SDK
        try:
            import warnings
            import google.generativeai as genai_old  # type: ignore
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                genai_old.configure(api_key=api_key)
            for model_name in model_names:
                try:
                    from PIL import Image as _PILImage  # type: ignore
                    import io as _io
                    img = _PILImage.open(_io.BytesIO(image_bytes))
                    model = genai_old.GenerativeModel(model_name)
                    prompt_parts = [system or "", img]
                    response = model.generate_content(prompt_parts)
                    return response.text
                except Exception as exc:
                    logger.debug("legacy gemini vision %r failed: %s", model_name, exc)
            return None
        except ImportError:
            return None

    def _call_anthropic_vision(
        self, data_uri: str, mime_type: str, system: str | None
    ) -> Optional[str]:
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key or api_key == _PLACEHOLDER:
            return None
        try:
            import anthropic  # type: ignore
        except ImportError:
            return None

        model = os.getenv("ANTHROPIC_MODEL", "claude-haiku-3-5-20241022")
        client = anthropic.Anthropic(api_key=api_key)

        # Anthropic expects base64 source, not data URI
        import base64
        b64 = data_uri.split(",", 1)[1] if "," in data_uri else data_uri

        content: list = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime_type,
                    "data": b64,
                },
            },
            {"type": "text", "text": system or "Describe this image in detail as Markdown."},
        ]
        kwargs: dict = {
            "model": model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": content}],
        }
        if system:
            kwargs["system"] = system
        try:
            response = client.messages.create(**kwargs)
            return response.content[0].text
        except Exception as exc:
            logger.debug("Anthropic vision failed: %s", exc)
            return None

    def _call_openai_compat_vision(
        self, provider: str, data_uri: str, mime_type: str, system: str | None
    ) -> Optional[str]:
        prefix, default_url, default_model = _OPENAI_COMPAT_PROVIDERS[provider]
        api_key  = os.getenv(f"{prefix}API_KEY", "")
        base_url = os.getenv(f"{prefix}BASE_URL", default_url)
        model    = os.getenv(f"{prefix}MODEL", default_model)

        if not api_key or api_key == _PLACEHOLDER:
            return None
        try:
            from openai import OpenAI  # type: ignore
        except ImportError:
            return None

        client = OpenAI(api_key=api_key, base_url=base_url)
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": data_uri}},
                {"type": "text", "text": system or "Describe this image in detail as Markdown."},
            ],
        })
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=4096,
            )
            return response.choices[0].message.content
        except Exception as exc:
            logger.debug("OpenAI-compat vision provider %r failed: %s", provider, exc)
            return None

    def _call_ollama_vision(
        self, data_uri: str, mime_type: str, system: str | None
    ) -> Optional[str]:
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        # Vision-capable Ollama models (llava family)
        model = os.getenv("OLLAMA_VISION_MODEL", os.getenv("OLLAMA_MODEL", "llava"))
        try:
            import ollama as _ollama  # type: ignore
        except ImportError:
            return None

        import base64
        b64 = data_uri.split(",", 1)[1] if "," in data_uri else data_uri
        image_bytes = base64.b64decode(b64)

        ollama_client = _ollama.Client(host=base_url)
        prompt = system or "Describe this image in detail as Markdown."
        try:
            response = ollama_client.chat(
                model=model,
                messages=[{
                    "role": "user",
                    "content": prompt,
                    "images": [image_bytes],
                }],
            )
            return response["message"]["content"]
        except Exception as exc:
            logger.debug("Ollama vision model %r failed: %s", model, exc)
            return None
