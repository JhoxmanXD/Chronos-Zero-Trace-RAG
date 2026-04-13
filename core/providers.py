"""Provider resolution and OpenAI-compatible client construction."""

from __future__ import annotations

import os
from urllib.parse import urlparse

from openai import OpenAI

DEFAULT_LM_URL = "http://localhost:1234/v1"
DEFAULT_MODEL_NAME = "gemma 4/gguf/gemma-4-e4b-uncensored-hauhaucs-aggressive-q6_k_p.gguf"

PROVIDER_LOCAL = "Local (LM Studio/Ollama)"
PROVIDER_OPENAI_COMPAT = "OpenAI Compatible"
PROVIDER_OPENROUTER = "OpenRouter"
PROVIDER_OPTIONS = [PROVIDER_LOCAL, PROVIDER_OPENAI_COMPAT, PROVIDER_OPENROUTER]

DEFAULT_OPENAI_COMPAT_URL = "https://api.openai.com/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

DEFAULT_PROVIDER_MODELS = {
    PROVIDER_LOCAL: DEFAULT_MODEL_NAME,
    PROVIDER_OPENAI_COMPAT: "gpt-4o-mini",
    PROVIDER_OPENROUTER: "openrouter/auto",
}


def normalize_provider_custom_models(raw_models: object) -> dict[str, str]:
    """Normalize custom model mapping into a sorted dictionary.

    Args:
        raw_models: Untrusted object expected to be display-name -> model-id mapping.

    Returns:
        dict[str, str]: Sanitized mapping sorted by display-name.
    """
    if not isinstance(raw_models, dict):
        return {}

    cleaned: dict[str, str] = {}
    for display_name, model_id in raw_models.items():
        name = str(display_name or "").strip()
        value = str(model_id or "").strip()
        if not name or not value:
            continue
        cleaned[name] = value

    return dict(sorted(cleaned.items(), key=lambda item: item[0].casefold()))


def build_default_provider_settings() -> dict[str, dict]:
    """Build default provider settings payload for UI state initialization.

    Returns:
        dict[str, dict]: Provider settings dictionary.
    """
    return {
        PROVIDER_LOCAL: {
            "api_key": "",
            "base_url": DEFAULT_LM_URL,
            "model_name": DEFAULT_PROVIDER_MODELS[PROVIDER_LOCAL],
            "custom_models_dict": {},
        },
        PROVIDER_OPENAI_COMPAT: {
            "api_key": "",
            "base_url": DEFAULT_OPENAI_COMPAT_URL,
            "model_name": DEFAULT_PROVIDER_MODELS[PROVIDER_OPENAI_COMPAT],
            "custom_models_dict": {},
        },
        PROVIDER_OPENROUTER: {
            "api_key": "",
            "base_url": OPENROUTER_BASE_URL,
            "model_name": DEFAULT_PROVIDER_MODELS[PROVIDER_OPENROUTER],
            "custom_models_dict": {},
        },
    }


def normalize_provider_settings(raw_settings: object) -> dict[str, dict]:
    """Merge persisted provider settings with current defaults.

    Args:
        raw_settings: Untrusted provider settings payload.

    Returns:
        dict[str, dict]: Fully normalized provider settings.
    """
    defaults = build_default_provider_settings()
    if not isinstance(raw_settings, dict):
        return defaults

    for provider_name in PROVIDER_OPTIONS:
        incoming = raw_settings.get(provider_name, {})
        if not isinstance(incoming, dict):
            continue

        merged = defaults[provider_name]
        merged["api_key"] = str(incoming.get("api_key", "") or "").strip()
        merged["base_url"] = str(incoming.get("base_url", merged["base_url"]) or "").strip() or merged["base_url"]
        merged["model_name"] = (
            str(incoming.get("model_name", merged["model_name"]) or "").strip() or merged["model_name"]
        )
        merged["custom_models_dict"] = normalize_provider_custom_models(incoming.get("custom_models_dict", {}))

        if provider_name == PROVIDER_OPENROUTER:
            merged["base_url"] = OPENROUTER_BASE_URL

    return defaults


def validate_lm_url(lm_url: str, *, strict_local: bool = True) -> None:
    """Validate provider base URL format and local-only policy.

    Args:
        lm_url: Base URL to validate.
        strict_local: Enforce localhost-only URL.

    Raises:
        ValueError: If URL has invalid format.
        RuntimeError: If strict local policy is violated.
    """
    parsed = urlparse((lm_url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("LM URL must start with http:// or https://.")
    if not parsed.hostname:
        raise ValueError("LM URL is invalid: hostname is empty.")
    if strict_local and parsed.hostname.lower() not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("STRICT_LOCAL_LLM is enabled: local provider must run on localhost.")


def resolve_provider_connection(
    active_provider: str,
    provider_settings: dict,
    lm_url: str | None = None,
) -> tuple[str, str]:
    """Resolve base URL and API key for the selected provider.

    Args:
        active_provider: Selected provider name.
        provider_settings: Provider settings dictionary.
        lm_url: Optional override base URL.

    Returns:
        tuple[str, str]: Resolved (base_url, api_key).
    """
    normalized_provider = str(active_provider or PROVIDER_LOCAL).strip()
    if normalized_provider not in PROVIDER_OPTIONS:
        normalized_provider = PROVIDER_LOCAL

    normalized_settings = normalize_provider_settings(provider_settings or {})
    provider_cfg = normalized_settings[normalized_provider]

    if normalized_provider == PROVIDER_LOCAL:
        base_url = str(lm_url or provider_cfg.get("base_url", DEFAULT_LM_URL)).strip() or DEFAULT_LM_URL
        default_local_key = "ollama" if "11434" in base_url else "lm-studio"
        api_key = str(provider_cfg.get("api_key", "")).strip() or os.getenv("LM_STUDIO_API_KEY", default_local_key)
        return base_url, api_key

    if normalized_provider == PROVIDER_OPENAI_COMPAT:
        base_url = str(provider_cfg.get("base_url", DEFAULT_OPENAI_COMPAT_URL)).strip() or DEFAULT_OPENAI_COMPAT_URL
        api_key = str(provider_cfg.get("api_key", "")).strip()
        return base_url, api_key

    base_url = OPENROUTER_BASE_URL
    api_key = str(provider_cfg.get("api_key", "")).strip()
    return base_url, api_key


def get_llm_client(
    lm_url: str | None,
    *,
    active_provider: str,
    provider_settings: dict,
) -> OpenAI:
    """Build an OpenAI-compatible client for the active provider.

    Args:
        lm_url: Optional provider URL override.
        active_provider: Selected provider name.
        provider_settings: Provider settings payload.

    Returns:
        OpenAI: Configured OpenAI-compatible client.
    """
    resolved_provider = str(active_provider or PROVIDER_LOCAL).strip()
    base_url, api_key = resolve_provider_connection(
        resolved_provider,
        provider_settings,
        lm_url=lm_url,
    )

    strict_local = os.getenv("STRICT_LOCAL_LLM", "true").lower() != "false"
    if resolved_provider != PROVIDER_LOCAL:
        strict_local = False
    validate_lm_url(base_url, strict_local=strict_local)

    if resolved_provider in {PROVIDER_OPENAI_COMPAT, PROVIDER_OPENROUTER} and not api_key:
        raise RuntimeError("Configure an API key for the active provider in LLM Configuration.")

    return OpenAI(base_url=base_url.rstrip("/"), api_key=api_key)
