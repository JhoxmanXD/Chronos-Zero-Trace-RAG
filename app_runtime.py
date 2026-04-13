#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import queue
import random
import re
import socket
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from html import escape, unescape
from pathlib import Path
from typing import Generator, List
from urllib.parse import parse_qs, quote, unquote, urlparse

import requests
import streamlit as st
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException
from urllib3.util.retry import Retry

from core.vault import SecretsVault, get_secret
from core.providers import (
    build_default_provider_settings as core_build_default_provider_settings,
    get_llm_client as core_get_llm_client,
    normalize_provider_custom_models as core_normalize_provider_custom_models,
    normalize_provider_settings as core_normalize_provider_settings,
    resolve_provider_connection as core_resolve_provider_connection,
)
from core.rag_agent import (
    DIRECT_SYSTEM_PROMPT as CORE_DIRECT_SYSTEM_PROMPT,
    PrivacyError,
    SearchResult,
    THINKING_SYSTEM_PROMPT as CORE_THINKING_SYSTEM_PROMPT,
    ZeroTraceRAG,
    run_research_with_runtime as core_run_research_with_runtime,
    search_brave_api,
)
from ui.chat import (
    render_assistant_content as ui_render_assistant_content,
    render_chat_history as ui_render_chat_history,
    render_logs_console as ui_render_logs_console,
    render_message_bubble as ui_render_message_bubble,
)
from ui.sidebar import sidebar_controls as ui_sidebar_controls
from ui.styles import inject_styles as ui_inject_styles
from utils.storage import (
    build_store_payload as storage_build_store_payload,
    delete_conversation_from_disk as storage_delete_conversation_from_disk,
    ensure_conversations_dir as storage_ensure_conversations_dir,
    load_conversations_from_disk as storage_load_conversations_from_disk,
    load_custom_models as storage_load_custom_models,
    make_default_conversation as storage_make_default_conversation,
    normalize_loaded_conversation as storage_normalize_loaded_conversation,
    save_conversation_to_disk as storage_save_conversation_to_disk,
    save_conversations_to_disk as storage_save_conversations_to_disk,
    save_custom_models as storage_save_custom_models,
    utc_now as storage_utc_now,
)
from utils.helpers import (
    diversify_results as helpers_diversify_results,
    estimate_messages_tokens as helpers_estimate_messages_tokens,
    estimate_text_tokens as helpers_estimate_text_tokens,
    sanitize_query_for_antibot as helpers_sanitize_query_for_antibot,
    split_and_sanitize_queries as helpers_split_and_sanitize_queries,
    truncate_text_to_tokens as helpers_truncate_text_to_tokens,
)

DEFAULT_LM_URL = "http://localhost:1234/v1"
DEFAULT_MODEL_NAME = "gemma 4/gguf/gemma-4-e4b-uncensored-hauhaucs-aggressive-q6_k_p.gguf"
DEFAULT_TOR_PORT = "9150"
DEFAULT_SEARX_INSTANCES = [
    "https://searx.tiekoetter.com",
    "https://search.inetol.net",
    "https://priv.au",
    "https://search.datenkrake.ch",
    "https://search.ononoki.org",
    "https://search.rhscz.eu",
    "https://search.sapti.me",
    "https://searx.be",
    "https://searx.party",
    "https://searx.ro",
    "https://searx.tsmdt.de",
]
DEFAULT_SEARX_ONION_INSTANCES = [
    "http://searx3aolosaf3urwnhpynlhuokqsgz47si4pzz5hvb7uuzyjncl2tid.onion",
    "http://searchb5a7tmwkzqp63ea6t4qcgrmlfrn3cd5uvlxnvnhpqticiknad.onion",
]

SAVE_SETTINGS_LOCK = threading.Lock()
UI_SETTINGS_PATH = Path(__file__).resolve().parent / "conversations_json" / "ui_settings.json"
RETRY_JITTER_RANGE_SECONDS = (0.08, 0.32)
GENERATION_EVENT_QUEUE_MAXSIZE = 8192
GENERATION_EVENT_PUT_TIMEOUT_SECONDS = 0.5
DEFAULT_SEARCH_INSTANCE_ATTEMPTS = 4
MAX_WEB_RESULTS_POOL_FACTOR = 3
RESEARCH_MAX_ITERATIONS = 3
EVALUATOR_MAX_CONTEXT_SOURCES = 10
MAX_CONTEXT_LIMIT_TOKENS = 1_000_000
THINKING_FORCE_PREFIX = (
    "Use exactly one <think>...</think> block at the beginning, do not repeat those tags inside reasoning, then answer in the same language the user used: "
)
THINKING_SYSTEM_PROMPT = CORE_THINKING_SYSTEM_PROMPT

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

DIRECT_SYSTEM_PROMPT = CORE_DIRECT_SYSTEM_PROMPT

GREETING_MESSAGES = {
    "hello",
    "hi",
    "hey",
    "greetings",
    "good morning",
    "good afternoon",
    "good evening",
    "how are you",
    "thanks",
    "thank you",
    "ok",
    "okay",
    "alright",
}

WEB_INTENT_HINTS = {
    "search",
    "investigate",
    "internet",
    "web",
    "current",
    "today",
    "news",
    "headline",
    "price",
    "pricing",
    "quote",
    "who",
    "when",
    "where",
    "2025",
    "2026",
}

TOR_WEB_ENGINE_OPTIONS = {
    "auto": "Auto (SearXNG -> DuckDuckGo)",
    "searxng": "Prioritize SearXNG",
    "duckduckgo": "Prioritize DuckDuckGo",
    "wikipedia_only": "Wikipedia Only (Manual)",
}

TOKEN_RE = re.compile(r"\w+|[^\w\s]", flags=re.UNICODE)

PRIVACY_PROFILES = {
    "max_tor": {
        "label": "Maximum Shielding (Tor + RAG)",
        "web_mode": "tor",
        "description": (
            "Maximum anonymity. All web access requires Tor with strict IsTor=true verification "
            "(fail-closed). If Tor is unavailable or no valid anonymous egress exists, search is blocked. "
            "Best for sensitive requests and high OPSEC workflows."
        ),
    },
    "local_only": {
        "label": "Strict Local (No Web)",
        "web_mode": "off",
        "description": (
            "Strong privacy through surface minimization: no external web traffic, "
            "only local LM Studio conversation."
        ),
    },
    "fast_direct": {
        "label": "Fast Direct Web (No Tor)",
        "web_mode": "direct",
        "description": (
            "Higher speed for non-sensitive requests. Uses SearXNG over HTTPS without Tor; "
            "reduces latency but sacrifices network anonymity."
        ),
    },
    "fast_brave": {
        "label": "Brave Search API",
        "web_mode": "brave",
        "description": (
            "Fast web search using Brave Search API with API-key authentication. "
            "No Tor required and usually more stable than direct scraping."
        ),
    },
}


st.set_page_config(
    page_title="Zero-Trace RAG Chat",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _normalize_provider_custom_models(raw_models: object) -> dict[str, str]:
    return core_normalize_provider_custom_models(raw_models)


def build_default_provider_settings() -> dict[str, dict]:
    return core_build_default_provider_settings()


def normalize_provider_settings(raw_settings: object) -> dict[str, dict]:
    return core_normalize_provider_settings(raw_settings)


def ensure_provider_state_consistency() -> None:
    st.session_state.provider_settings = normalize_provider_settings(st.session_state.get("provider_settings", {}))

    active_provider = str(st.session_state.get("active_provider", PROVIDER_LOCAL)).strip()
    if active_provider not in PROVIDER_OPTIONS:
        active_provider = PROVIDER_LOCAL
    st.session_state.active_provider = active_provider


def sync_active_provider_runtime_state() -> None:
    ensure_provider_state_consistency()
    active_provider = st.session_state.active_provider
    provider_cfg = st.session_state.provider_settings[active_provider]

    active_model_name = str(provider_cfg.get("model_name", "")).strip() or DEFAULT_PROVIDER_MODELS[active_provider]
    provider_cfg["model_name"] = active_model_name
    st.session_state.provider_settings[active_provider] = provider_cfg

    st.session_state.lm_url = str(provider_cfg.get("base_url", "")).strip()
    st.session_state.model_name = active_model_name
    st.session_state.custom_models_dict = dict(
        sorted(provider_cfg.get("custom_models_dict", {}).items(), key=lambda item: item[0].casefold())
    )


def safe_option_index(options: list[str], value: object, *, default: int = 0) -> int:
    if not options:
        return 0

    normalized_value = str(value or "").strip()
    if normalized_value in options:
        return options.index(normalized_value)

    return max(0, min(default, len(options) - 1))


def clear_dynamic_sidebar_widget_state() -> None:
    dynamic_prefixes = (
        "provider_model_selector_",
        "custom_model_delete_target_",
    )

    for state_key in list(st.session_state.keys()):
        if any(state_key.startswith(prefix) for prefix in dynamic_prefixes):
            del st.session_state[state_key]


def ensure_conversations_dir() -> Path:
    return storage_ensure_conversations_dir()


def utc_now() -> datetime:
    return storage_utc_now()


def make_default_conversation(
    conv_id: str | None = None,
    *,
    is_incognito: bool = True,
    title: str | None = None,
) -> dict:
    return storage_make_default_conversation(
        conv_id,
        is_incognito=is_incognito,
        title=title,
    )


def _write_chat_schema_marker() -> None:
    return


def _read_chat_schema_marker() -> int | None:
    return None


def reset_chat_storage_if_needed() -> None:
    # Persistence disabled for privacy.
    return


def _build_store_payload(conversations: dict[str, dict]) -> dict:
    return storage_build_store_payload(conversations)


def _save_conversations_to_disk(conversations: dict[str, dict]) -> None:
    storage_save_conversations_to_disk(conversations)


def save_conversation_to_disk(conversation: dict) -> None:
    conversations = st.session_state.get("conversations", {})
    storage_save_conversation_to_disk(conversation, conversations)


def delete_conversation_from_disk(conv_id: str) -> None:
    storage_delete_conversation_from_disk(conv_id)


def _normalize_loaded_conversation(payload: dict) -> dict | None:
    return storage_normalize_loaded_conversation(payload)


def load_conversations_from_disk() -> dict:
    return storage_load_conversations_from_disk()


def load_custom_models() -> dict:
    return storage_load_custom_models()


def save_custom_models(models_dict: dict) -> None:
    storage_save_custom_models(models_dict)


def save_current_conversation() -> None:
    conversation = get_current_conversation()
    save_conversation_to_disk(conversation)


def _normalize_model_library(raw_models: object) -> list[str]:
    if not isinstance(raw_models, list):
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_models:
        model_name = str(item or "").strip()
        if not model_name:
            continue
        model_key = model_name.casefold()
        if model_key in seen:
            continue
        seen.add(model_key)
        normalized.append(model_name)

    normalized.sort(key=str.casefold)
    return normalized


def _clamp_int(value: object, *, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(max_value, parsed))


def load_ui_settings_from_disk() -> dict:
    try:
        ensure_conversations_dir()
        if not UI_SETTINGS_PATH.exists():
            return {}
        payload = json.loads(UI_SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

    if not isinstance(payload, dict):
        return {}

    loaded: dict = {}

    active_provider = str(payload.get("active_provider", "")).strip()
    if active_provider in PROVIDER_OPTIONS:
        loaded["active_provider"] = active_provider

    provider_models = payload.get("provider_models", {})
    provider_connections = payload.get("provider_connections", {})
    persisted_provider_settings = build_default_provider_settings()
    if isinstance(provider_models, dict):
        for provider_name in PROVIDER_OPTIONS:
            provider_payload = provider_models.get(provider_name, {})
            if not isinstance(provider_payload, dict):
                continue

            persisted_provider_settings[provider_name]["model_name"] = (
                str(provider_payload.get("model_name", "")).strip() or DEFAULT_PROVIDER_MODELS[provider_name]
            )
            persisted_provider_settings[provider_name]["custom_models_dict"] = _normalize_provider_custom_models(
                provider_payload.get("custom_models_dict", {})
            )

    if isinstance(provider_connections, dict):
        for provider_name in PROVIDER_OPTIONS:
            provider_payload = provider_connections.get(provider_name, {})
            if not isinstance(provider_payload, dict):
                continue

            if provider_name == PROVIDER_OPENROUTER:
                persisted_provider_settings[provider_name]["base_url"] = OPENROUTER_BASE_URL
                continue

            provider_base_url = str(provider_payload.get("base_url", "")).strip()
            if provider_base_url:
                persisted_provider_settings[provider_name]["base_url"] = provider_base_url

    # Migration from legacy single-provider structure.
    legacy_model_name = str(payload.get("model_name", "")).strip()
    if legacy_model_name:
        persisted_provider_settings[PROVIDER_LOCAL]["model_name"] = legacy_model_name

    legacy_model_library = _normalize_model_library(payload.get("model_library", []))
    if legacy_model_library and not persisted_provider_settings[PROVIDER_LOCAL]["custom_models_dict"]:
        persisted_provider_settings[PROVIDER_LOCAL]["custom_models_dict"] = {
            name: name for name in legacy_model_library
        }

    legacy_lm_url = str(payload.get("lm_url", "")).strip()
    if legacy_lm_url:
        loaded["legacy_lm_url"] = legacy_lm_url

    loaded["provider_settings"] = persisted_provider_settings

    tor_port = str(payload.get("tor_port", "")).strip()
    if tor_port in {"9050", "9150"}:
        loaded["tor_port"] = tor_port

    privacy_profile = str(payload.get("privacy_profile", "")).strip()
    if privacy_profile in PRIVACY_PROFILES:
        loaded["privacy_profile"] = privacy_profile

    if "web_search_enabled" in payload:
        loaded["web_search_enabled"] = bool(payload.get("web_search_enabled"))
    if "auto_web_for_informational_queries" in payload:
        loaded["auto_web_for_informational_queries"] = bool(payload.get("auto_web_for_informational_queries"))

    tor_engine = str(payload.get("tor_web_engine_preference", "")).strip()
    if tor_engine in TOR_WEB_ENGINE_OPTIONS or tor_engine == "wikipedia":
        loaded["tor_web_engine_preference"] = tor_engine

    loaded["context_limit_tokens"] = _clamp_int(
        payload.get("context_limit_tokens"),
        default=int(os.getenv("LM_CONTEXT_LIMIT", "8192")),
        min_value=1024,
        max_value=MAX_CONTEXT_LIMIT_TOKENS,
    )

    if "llm_thinking_enabled" in payload:
        loaded["llm_thinking_enabled"] = bool(payload.get("llm_thinking_enabled"))

    searx_instances_raw = payload.get("searx_instances_raw")
    if isinstance(searx_instances_raw, str):
        loaded["searx_instances_raw"] = searx_instances_raw

    return loaded


def save_ui_settings_to_disk() -> None:
    ensure_provider_state_consistency()
    providers = normalize_provider_settings(st.session_state.get("provider_settings", {}))
    active_provider = st.session_state.active_provider

    provider_models_payload: dict[str, dict] = {}
    provider_connections_payload: dict[str, dict] = {}
    for provider_name, provider_cfg in providers.items():
        provider_models_payload[provider_name] = {
            "model_name": str(provider_cfg.get("model_name", "")).strip() or DEFAULT_PROVIDER_MODELS[provider_name],
            "custom_models_dict": _normalize_provider_custom_models(provider_cfg.get("custom_models_dict", {})),
        }
        provider_connections_payload[provider_name] = {
            "base_url": (
                OPENROUTER_BASE_URL
                if provider_name == PROVIDER_OPENROUTER
                else str(provider_cfg.get("base_url", "")).strip()
            )
        }

    payload = {
        "active_provider": active_provider,
        "provider_models": provider_models_payload,
        "provider_connections": provider_connections_payload,
        "tor_port": str(st.session_state.get("tor_port", DEFAULT_TOR_PORT) or DEFAULT_TOR_PORT).strip() or DEFAULT_TOR_PORT,
        "privacy_profile": str(st.session_state.get("privacy_profile", "max_tor") or "max_tor").strip() or "max_tor",
        "web_search_enabled": bool(st.session_state.get("web_search_enabled", True)),
        "auto_web_for_informational_queries": bool(st.session_state.get("auto_web_for_informational_queries", True)),
        "tor_web_engine_preference": str(
            st.session_state.get("tor_web_engine_preference", "duckduckgo") or "duckduckgo"
        ).strip()
        or "duckduckgo",
        "context_limit_tokens": _clamp_int(
            st.session_state.get("context_limit_tokens"),
            default=int(os.getenv("LM_CONTEXT_LIMIT", "8192")),
            min_value=1024,
            max_value=MAX_CONTEXT_LIMIT_TOKENS,
        ),
        "llm_thinking_enabled": bool(st.session_state.get("llm_thinking_enabled", False)),
        "searx_instances_raw": str(st.session_state.get("searx_instances_raw", "") or ""),
    }

    try:
        ensure_conversations_dir()
        with SAVE_SETTINGS_LOCK:
            UI_SETTINGS_PATH.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    except Exception:
        # Silent failure: app keeps running in memory even if persistence fails.
        return


def save_provider_credentials_to_vault(provider_settings: dict) -> None:
    """Persist provider API keys to the encrypted vault."""
    normalized_settings = normalize_provider_settings(provider_settings)
    vault_payload = SecretsVault().load_secrets()
    if not isinstance(vault_payload, dict):
        vault_payload = {}

    vault_payload["providers"] = {
        provider_name: {"api_key": str(provider_cfg.get("api_key", "")).strip()}
        for provider_name, provider_cfg in normalized_settings.items()
    }
    SecretsVault().save_secrets(vault_payload)


def save_brave_api_key_to_vault(brave_api_key: str) -> None:
    """Persist Brave Search API key to the encrypted vault."""
    vault_payload = SecretsVault().load_secrets()
    if not isinstance(vault_payload, dict):
        vault_payload = {}

    providers_payload = vault_payload.get("providers", {})
    vault_payload["providers"] = providers_payload if isinstance(providers_payload, dict) else {}
    vault_payload["brave_api_key"] = str(brave_api_key or "").strip()
    SecretsVault().save_secrets(vault_payload)


def inject_styles() -> None:
    """Inject the application stylesheet into Streamlit."""
    ui_inject_styles()

def init_session_state() -> None:
    if not st.session_state.get("storage_loaded", False):
        loaded_conversations = load_conversations_from_disk()
        if loaded_conversations:
            st.session_state.conversations = loaded_conversations
            st.session_state.current_conversation_id = next(iter(loaded_conversations.keys()))
        else:
            first_conv = make_default_conversation(is_incognito=False)
            st.session_state.conversations = {first_conv["id"]: first_conv}
            st.session_state.current_conversation_id = first_conv["id"]
        st.session_state.storage_loaded = True

    defaults = {
        "active_provider": PROVIDER_LOCAL,
        "provider_settings": build_default_provider_settings(),
        "lm_url": DEFAULT_LM_URL,
        "model_name": DEFAULT_MODEL_NAME,
        "custom_models_dict": {},
        "legacy_lm_url": "",
        "vault_loaded": False,
        "tor_port": DEFAULT_TOR_PORT,
        "privacy_profile": "max_tor",
        "brave_api_key": "",
        "web_search_enabled": True,
        "auto_web_for_informational_queries": True,
        "tor_web_engine_preference": "duckduckgo",
        "tor_engine_migrated": False,
        "context_limit_tokens": int(os.getenv("LM_CONTEXT_LIMIT", "8192")),
        "llm_thinking_enabled": False,
        # Preload clearnet + onion instances so users can edit them in the UI.
        "searx_instances_raw": "\n".join([*DEFAULT_SEARX_INSTANCES, *DEFAULT_SEARX_ONION_INSTANCES]),
        "lm_status": "unknown",
        "lm_status_detail": "Status pending.",
        "tor_daemon_status": "unknown",
        "tor_daemon_detail": "Status pending.",
        "tor_verified_status": "unknown",
        "tor_verified_detail": "Tor egress has not been verified yet.",
        "live_monitor_enabled": True,
        "live_monitor_interval": 5,
        "last_monitor_update": "Never",
        "last_live_monitor_probe_at": 0.0,
        "pending_tor_revalidate": True,
        "last_tor_port_seen": DEFAULT_TOR_PORT,
        "generation_active": False,
        "generation_stop_event": None,
        "generation_queue": None,
        "generation_thread": None,
        "generation_buffer": "",
        "generation_target_conv_id": "",
        "generation_sources": None,
        "generation_rag_done": False,
        "generation_messages": None,
        "generation_cancel_requested": False,
        "generation_last_render_len": 0,
        "generation_last_render_at": 0.0,
        "generation_think_started_at": 0.0,
        "generation_think_elapsed": 0.0,
        "generation_think_closed": False,
        "search_cache": {},
        "search_cache_hits": 0,
        "search_cache_misses": 0,
        "search_cache_ttl_seconds": int(os.getenv("SEARCH_CACHE_TTL_SECONDS", "900")),
        "search_cache_max_entries": int(os.getenv("SEARCH_CACHE_MAX_ENTRIES", "120")),
        "last_privacy_profile": "max_tor",
        "sidebar_widget_recovery_attempted": False,
        "startup_healthcheck_deadline": time.time() + 5.0,
        "ui_settings_loaded": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    conversations = st.session_state.get("conversations")
    if isinstance(conversations, dict):
        for conv in conversations.values():
            if not isinstance(conv, dict):
                continue
            conv["is_incognito"] = bool(conv.get("is_incognito", False))
            if not str(conv.get("title", "")).strip():
                conv["title"] = "Incognito chat" if conv["is_incognito"] else "Regular chat"

    if not st.session_state.ui_settings_loaded:
        persisted_settings = load_ui_settings_from_disk()
        for key, value in persisted_settings.items():
            st.session_state[key] = value
        st.session_state.ui_settings_loaded = True

    ensure_provider_state_consistency()

    local_provider_cfg = st.session_state.provider_settings[PROVIDER_LOCAL]
    legacy_lm_url = str(st.session_state.get("legacy_lm_url", "")).strip()
    if legacy_lm_url and local_provider_cfg.get("base_url", DEFAULT_LM_URL) == DEFAULT_LM_URL:
        local_provider_cfg["base_url"] = legacy_lm_url

    legacy_custom_models = load_custom_models()
    if legacy_custom_models and not local_provider_cfg.get("custom_models_dict"):
        local_provider_cfg["custom_models_dict"] = legacy_custom_models

    st.session_state.provider_settings[PROVIDER_LOCAL] = local_provider_cfg

    if not st.session_state.vault_loaded:
        vault_payload = SecretsVault().load_secrets()
        vault_providers = vault_payload.get("providers", {}) if isinstance(vault_payload, dict) else {}
        if isinstance(vault_payload, dict):
            st.session_state.brave_api_key = str(vault_payload.get("brave_api_key", "") or "").strip()
        if isinstance(vault_providers, dict):
            merged_provider_settings = normalize_provider_settings(st.session_state.get("provider_settings", {}))
            for provider_name in PROVIDER_OPTIONS:
                provider_secret = vault_providers.get(provider_name, {})
                if not isinstance(provider_secret, dict):
                    continue

                merged_provider_settings[provider_name]["api_key"] = str(provider_secret.get("api_key", "")).strip()

                if provider_name == PROVIDER_OPENROUTER:
                    merged_provider_settings[provider_name]["base_url"] = OPENROUTER_BASE_URL

            st.session_state.provider_settings = merged_provider_settings

        st.session_state.vault_loaded = True

    ensure_provider_state_consistency()
    sync_active_provider_runtime_state()

    if st.session_state.get("privacy_profile_ui") not in PRIVACY_PROFILES:
        st.session_state.privacy_profile_ui = st.session_state.privacy_profile

    if not st.session_state.tor_engine_migrated and st.session_state.tor_web_engine_preference == "auto":
        st.session_state.tor_web_engine_preference = "duckduckgo"
    st.session_state.tor_engine_migrated = True


def ensure_conversation_state() -> None:
    conversations = st.session_state.get("conversations", {})
    if not conversations:
        new_conv = make_default_conversation(is_incognito=False)
        st.session_state.conversations = {new_conv["id"]: new_conv}
        st.session_state.current_conversation_id = new_conv["id"]
        return

    current_id = st.session_state.get("current_conversation_id")
    if current_id not in conversations:
        st.session_state.current_conversation_id = next(iter(conversations.keys()))


def create_new_conversation(*, is_incognito: bool = True) -> None:
    conv_id = f"conv-{uuid.uuid4().hex[:8]}"
    new_conv = make_default_conversation(conv_id=conv_id, is_incognito=is_incognito)
    st.session_state.conversations[conv_id] = new_conv
    st.session_state.current_conversation_id = conv_id
    save_conversation_to_disk(new_conv)


def get_current_conversation() -> dict:
    ensure_conversation_state()
    conv_id = st.session_state.current_conversation_id
    return st.session_state.conversations[conv_id]


def get_conversation_by_id(conv_id: str) -> dict | None:
    return st.session_state.conversations.get(conv_id)


def append_log(conv_id: str, message: str) -> None:
    conv = get_conversation_by_id(conv_id)
    if conv is None:
        return

    logs = conv.setdefault("logs", [])
    ts = datetime.now().strftime("%H:%M:%S")
    logs.append(f"[{ts}] {str(message or '')}")
    if len(logs) > 400:
        conv["logs"] = logs[-400:]


def build_msg_start_log(user_text: str, max_chars: int = 40) -> str:
    clean_text = " ".join(str(user_text or "").split())
    if not clean_text:
        return "MSG_START: (no text)"

    snippet = clean_text[:max_chars]
    if len(clean_text) > max_chars:
        snippet = f"{snippet}..."
    return f"MSG_START: {snippet}"


def should_auto_name_conversation(title: str) -> bool:
    normalized = str(title or "").strip().casefold()
    return normalized in {"", "incognito chat", "regular chat", "untitled chat"}


def build_auto_conversation_title(user_text: str, max_chars: int = 28) -> str:
    clean_text = " ".join(str(user_text or "").split())
    if not clean_text:
        return "Untitled chat"

    words = clean_text.split()
    if len(words) > 1:
        clean_text = " ".join(words[:-1])

    snippet = clean_text[:max_chars]
    if len(clean_text) > max_chars:
        snippet = f"{snippet}..."
    return snippet


def clear_logs(conv_id: str) -> None:
    conv = get_conversation_by_id(conv_id)
    if conv is None:
        return
    conv["logs"] = []
    save_conversation_to_disk(conv)


def reset_generation_state() -> None:
    st.session_state.generation_active = False
    st.session_state.generation_stop_event = None
    st.session_state.generation_queue = None
    st.session_state.generation_thread = None
    st.session_state.generation_buffer = ""
    st.session_state.generation_target_conv_id = ""
    st.session_state.generation_sources = None
    st.session_state.generation_rag_done = False
    st.session_state.generation_messages = None
    st.session_state.generation_cancel_requested = False
    st.session_state.generation_last_render_len = 0
    st.session_state.generation_last_render_at = 0.0
    st.session_state.generation_think_started_at = 0.0
    st.session_state.generation_think_elapsed = 0.0
    st.session_state.generation_think_closed = False


def delete_current_conversation() -> None:
    conversations = st.session_state.conversations
    current_id = st.session_state.current_conversation_id

    delete_conversation_from_disk(current_id)
    conversations.pop(current_id, None)

    if not conversations:
        fallback = make_default_conversation(is_incognito=False)
        conversations[fallback["id"]] = fallback
        st.session_state.current_conversation_id = fallback["id"]
        save_conversation_to_disk(fallback)
    else:
        st.session_state.current_conversation_id = next(iter(conversations.keys()))


def run_coro(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


def parse_searx_instances(raw_text: str) -> List[str]:
    candidates = []
    for line in (raw_text or "").splitlines():
        item = line.strip()
        if not item:
            continue
        candidates.append(item)
    return candidates


def summarize_query_for_log(text: str) -> str:
    sanitized, redactions = ZeroTraceRAG._sanitize_web_query(text or "")
    token_count = len(TOKEN_RE.findall(sanitized))
    return f"{token_count} token(s), {len(sanitized)} chars, redactions={redactions}"


def with_thinking_prefix(user_text: str) -> str:
    text = str(user_text or "").strip()
    if not text:
        return ""
    if text.startswith(THINKING_FORCE_PREFIX):
        return text
    return f"{THINKING_FORCE_PREFIX}{text}"


def inject_thinking_prompt_into_messages(messages: list[dict], thinking_enabled: bool | None = None) -> list[dict]:
    enabled = bool(st.session_state.get("llm_thinking_enabled", False)) if thinking_enabled is None else bool(thinking_enabled)
    if not enabled:
        return messages

    adapted: list[dict] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        adapted.append(
            {
                "role": str(item.get("role", "")).strip(),
                "content": str(item.get("content", "")),
            }
        )

    if not adapted:
        return messages

    system_updated = False
    for idx, item in enumerate(adapted):
        if item["role"] != "system":
            continue
        if THINKING_SYSTEM_PROMPT not in item["content"]:
            item["content"] = f"{item['content']}\n\n{THINKING_SYSTEM_PROMPT}".strip()
        adapted[idx] = item
        system_updated = True
        break

    if not system_updated:
        adapted.insert(0, {"role": "system", "content": THINKING_SYSTEM_PROMPT})

    for idx in range(len(adapted) - 1, -1, -1):
        if adapted[idx]["role"] == "user":
            adapted[idx]["content"] = with_thinking_prefix(adapted[idx]["content"])
            break

    return adapted


def sanitize_query_for_antibot(query: str) -> str:
    return helpers_sanitize_query_for_antibot(query)


def split_and_sanitize_queries(raw_text: str, fallback_text: str, max_queries: int = 2) -> list[str]:
    return helpers_split_and_sanitize_queries(raw_text, fallback_text, max_queries=max_queries)


def get_max_instance_attempts() -> int:
    raw = os.getenv("SEARX_MAX_INSTANCE_ATTEMPTS", str(DEFAULT_SEARCH_INSTANCE_ATTEMPTS))
    try:
        value = int(raw)
    except ValueError:
        value = DEFAULT_SEARCH_INSTANCE_ATTEMPTS
    return max(1, min(value, 12))


def diversify_results(results: list[SearchResult], top_k: int) -> list[SearchResult]:
    return helpers_diversify_results(results, top_k)


def _normalize_instance_list(searx_instances: list[str]) -> list[str]:
    normalized = []
    for item in searx_instances:
        clean = str(item or "").strip().rstrip("/")
        if clean:
            normalized.append(clean)
    return sorted(set(normalized))


def build_search_cache_key(
    *,
    query: str,
    web_mode: str,
    preferred_engine: str,
    top_k: int,
    searx_instances: list[str],
) -> str:
    sanitized_query, _ = ZeroTraceRAG._sanitize_web_query(query)
    payload = {
        "q": " ".join(sanitized_query.lower().split()),
        "mode": str(web_mode),
        "engine": str(preferred_engine),
        "top_k": int(top_k),
        "instances": _normalize_instance_list(searx_instances),
    }
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)


def _cache_ttl_seconds() -> int:
    try:
        ttl = int(st.session_state.get("search_cache_ttl_seconds", 900))
    except Exception:
        ttl = 900
    return max(30, min(ttl, 86400))


def _cache_max_entries() -> int:
    try:
        max_entries = int(st.session_state.get("search_cache_max_entries", 120))
    except Exception:
        max_entries = 120
    return max(8, min(max_entries, 1000))


def record_search_cache_event(*, hit: bool) -> None:
    if hit:
        st.session_state.search_cache_hits = int(st.session_state.get("search_cache_hits", 0)) + 1
    else:
        st.session_state.search_cache_misses = int(st.session_state.get("search_cache_misses", 0)) + 1


def get_cached_search_results(cache_key: str) -> list[SearchResult] | None:
    cache = st.session_state.get("search_cache")
    if not isinstance(cache, dict):
        return None

    entry = cache.get(cache_key)
    if not isinstance(entry, dict):
        return None

    created_at = float(entry.get("created_at", 0.0) or 0.0)
    if created_at <= 0 or (time.time() - created_at) > _cache_ttl_seconds():
        cache.pop(cache_key, None)
        return None

    raw_results = entry.get("results", [])
    if not isinstance(raw_results, list):
        return None

    parsed: list[SearchResult] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        url = str(item.get("url", "")).strip()
        snippet = str(item.get("snippet", ""))
        if not title or not url:
            continue
        parsed.append(SearchResult(title=title, url=url, snippet=snippet))

    return parsed or None


def put_cached_search_results(cache_key: str, results: list[SearchResult]) -> None:
    if not results:
        return

    cache = st.session_state.get("search_cache")
    if not isinstance(cache, dict):
        cache = {}
        st.session_state.search_cache = cache

    cache[cache_key] = {
        "created_at": time.time(),
        "results": [asdict(item) for item in results],
    }

    max_entries = _cache_max_entries()
    if len(cache) <= max_entries:
        return

    ordered = sorted(cache.items(), key=lambda kv: float((kv[1] or {}).get("created_at", 0.0)))
    for key, _ in ordered[:-max_entries]:
        cache.pop(key, None)


def clear_search_cache() -> None:
    st.session_state.search_cache = {}
    st.session_state.search_cache_hits = 0
    st.session_state.search_cache_misses = 0


def get_context_limit_tokens() -> int:
    raw = int(st.session_state.context_limit_tokens)
    return max(1024, min(MAX_CONTEXT_LIMIT_TOKENS, raw))


def estimate_text_tokens(text: str) -> int:
    return helpers_estimate_text_tokens(text)


def estimate_messages_tokens(messages: list[dict]) -> int:
    return helpers_estimate_messages_tokens(messages)


def truncate_text_to_tokens(text: str, max_tokens: int) -> str:
    return helpers_truncate_text_to_tokens(text, max_tokens)


def build_history_window_messages(history: list[dict], token_budget: int) -> list[dict]:
    selected: list[dict] = []
    used = 0

    for item in reversed(history):
        role = item.get("role", "")
        content = str(item.get("content", ""))
        if role not in {"user", "assistant"} or not content:
            continue

        message = {"role": role, "content": content}
        msg_tokens = estimate_messages_tokens([message])

        if selected and used + msg_tokens > token_budget:
            break

        if not selected and msg_tokens > token_budget:
            available = max(64, token_budget - 8)
            message["content"] = truncate_text_to_tokens(content, available)
            msg_tokens = estimate_messages_tokens([message])

        selected.append(message)
        used += msg_tokens

    selected.reverse()
    return selected


def format_history_for_rag(history: list[dict], token_budget: int) -> str:
    entries: list[str] = []
    used = 0

    for item in reversed(history):
        role = item.get("role", "")
        content = str(item.get("content", ""))
        if role not in {"user", "assistant"} or not content:
            continue

        label = "User" if role == "user" else "Assistant"
        clean = " ".join(content.split())
        segment = f"{label}: {clean}"
        segment_tokens = estimate_text_tokens(segment)

        if entries and used + segment_tokens > token_budget:
            break

        if not entries and segment_tokens > token_budget:
            segment = f"{label}: {truncate_text_to_tokens(clean, max(64, token_budget - 8))}"
            segment_tokens = estimate_text_tokens(segment)

        entries.append(segment)
        used += segment_tokens

    entries.reverse()
    return "\n".join(entries) if entries else "No prior history."


def compute_conversation_tokens_in_use(messages: list[dict], context_limit_tokens: int) -> tuple[int, int]:
    direct_messages = build_direct_messages(messages, context_limit_tokens)
    in_use = estimate_messages_tokens(direct_messages)
    full_total = estimate_messages_tokens(
        [
            {"role": item.get("role", ""), "content": str(item.get("content", ""))}
            for item in messages
            if item.get("role") in {"user", "assistant"}
        ]
    )
    return in_use, full_total


def strip_html(text: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", text or "")
    return " ".join(unescape(no_tags).split())


def should_use_web_search(user_text: str, smart_mode: bool) -> bool:
    if not smart_mode:
        return True

    text = " ".join((user_text or "").lower().split())
    if not text:
        return False

    if text in GREETING_MESSAGES:
        return False

    words = text.split()
    if len(words) <= 2 and "?" not in text and not any(h in text for h in WEB_INTENT_HINTS):
        return False

    if any(h in text for h in WEB_INTENT_HINTS):
        return True

    if "?" in text and len(words) >= 4:
        return True

    return len(words) >= 5


def parse_duckduckgo_redirect(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname and "duckduckgo.com" in parsed.hostname and parsed.path.startswith("/l/"):
        uddg = parse_qs(parsed.query).get("uddg", [""])[0]
        return unquote(uddg) if uddg else ""
    return url


def is_onion_instance_url(raw_url: str) -> bool:
    host = (urlparse(str(raw_url or "").strip()).hostname or "").lower()
    return host.endswith(".onion")


def tor_proxy_from_port(port_text: str) -> str:
    port = str(port_text or "9050").strip()
    if not port.isdigit():
        raise PrivacyError("Tor port must be numeric.")
    return f"socks5h://127.0.0.1:{port}"


def create_rag(
    lm_url: str,
    model_name: str,
    tor_proxy: str,
    searx_instances: List[str],
    *,
    active_provider: str | None = None,
    provider_settings: dict | None = None,
) -> ZeroTraceRAG:
    resolved_provider = str(active_provider or st.session_state.get("active_provider", PROVIDER_LOCAL)).strip()

    rag_lm_url = str(lm_url or "").strip() or DEFAULT_LM_URL
    if resolved_provider != PROVIDER_LOCAL:
        rag_lm_url = DEFAULT_LM_URL

    _, active_api_key = resolve_active_provider_connection(
        lm_url=rag_lm_url,
        active_provider=resolved_provider,
        provider_settings=provider_settings,
    )
    if not active_api_key:
        active_api_key = os.getenv("LM_STUDIO_API_KEY", "lm-studio")

    return ZeroTraceRAG(
        lm_base_url=rag_lm_url,
        model_name=model_name,
        tor_proxy=tor_proxy,
        searx_instances=searx_instances,
        lm_api_key=active_api_key,
    )


def close_rag_safely(rag: ZeroTraceRAG) -> None:
    try:
        run_coro(rag.close())
    except Exception:
        pass


def validate_lm_url(lm_url: str, *, active_provider: str | None = None) -> None:
    strict_local = os.getenv("STRICT_LOCAL_LLM", "true").lower() != "false"
    resolved_provider = str(active_provider or st.session_state.get("active_provider", PROVIDER_LOCAL)).strip()
    if resolved_provider != PROVIDER_LOCAL:
        strict_local = False
    ZeroTraceRAG._validate_lm_url(lm_url.rstrip("/"), strict_local)


def resolve_provider_connection(
    active_provider: str,
    provider_settings: dict,
    lm_url: str | None = None,
) -> tuple[str, str]:
    return core_resolve_provider_connection(active_provider, provider_settings, lm_url=lm_url)


def resolve_active_provider_connection(
    lm_url: str | None = None,
    *,
    active_provider: str | None = None,
    provider_settings: dict | None = None,
) -> tuple[str, str]:
    if active_provider is not None and provider_settings is not None:
        return resolve_provider_connection(active_provider, provider_settings, lm_url=lm_url)

    ensure_provider_state_consistency()
    return resolve_provider_connection(
        st.session_state.active_provider,
        st.session_state.provider_settings,
        lm_url=lm_url,
    )


def get_llm_client(
    lm_url: str | None = None,
    *,
    active_provider: str | None = None,
    provider_settings: dict | None = None,
) -> OpenAI:
    if active_provider is not None and provider_settings is not None:
        resolved_provider = str(active_provider).strip()
        resolved_settings = provider_settings
        resolved_lm_url = lm_url
    else:
        ensure_provider_state_consistency()
        resolved_provider = str(st.session_state.get("active_provider", PROVIDER_LOCAL)).strip()
        resolved_settings = st.session_state.provider_settings
        resolved_lm_url = lm_url

    return core_get_llm_client(
        resolved_lm_url,
        active_provider=resolved_provider,
        provider_settings=resolved_settings,
    )


def verify_tor_now(lm_url: str, model_name: str, tor_proxy: str) -> tuple[bool, str]:
    rag = None
    try:
        rag = create_rag(
            lm_url=lm_url,
            model_name=model_name,
            tor_proxy=tor_proxy,
            searx_instances=DEFAULT_SEARX_INSTANCES,
        )
        run_coro(rag.verify_tor())
        return True, "Tor connection verified."
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    finally:
        if rag is not None:
            close_rag_safely(rag)


def render_tor_badge() -> None:
    status = st.session_state.tor_verified_status
    detail = st.session_state.tor_verified_detail

    if status == "ok":
        klass = "zt-ok"
        label = "Tor connected"
        dot_color = "#10b981"
    elif status == "error":
        klass = "zt-bad"
        label = "Tor unavailable"
        dot_color = "#ef4444"
    else:
        klass = "zt-warn"
        label = "Tor unverified"
        dot_color = "#f59e0b"

    st.markdown(
        (
            f"<div class='zt-badge {klass}'>"
            f"<span class='zt-dot' style='background:{dot_color};'></span>{label} (egress)</div>"
        ),
        unsafe_allow_html=True,
    )
    st.markdown(f"<div class='zt-small'>{detail}</div>", unsafe_allow_html=True)


def render_lm_badge() -> None:
    active_provider = str(st.session_state.get("active_provider", PROVIDER_LOCAL)).strip()
    status = st.session_state.lm_status
    detail = st.session_state.lm_status_detail

    if active_provider == PROVIDER_LOCAL:
        if status == "ok":
            klass = "zt-ok"
            label = "LM Studio active"
            dot_color = "#10b981"
        elif status == "error":
            klass = "zt-bad"
            label = "LM Studio unavailable"
            dot_color = "#ef4444"
        else:
            klass = "zt-warn"
            label = "LM Studio unverified"
            dot_color = "#f59e0b"
    else:
        if status == "error":
            klass = "zt-bad"
            label = f"{active_provider} error"
            dot_color = "#ef4444"
        elif status == "ok":
            klass = "zt-ok"
            label = f"{active_provider} active"
            dot_color = "#10b981"
        else:
            klass = "zt-warn"
            label = f"{active_provider} pending"
            dot_color = "#f59e0b"

    st.markdown(
        (
            f"<div class='zt-badge {klass}'>"
            f"<span class='zt-dot' style='background:{dot_color};'></span>{label}</div>"
        ),
        unsafe_allow_html=True,
    )
    st.markdown(f"<div class='zt-small'>{detail}</div>", unsafe_allow_html=True)


def render_tor_daemon_badge() -> None:
    status = st.session_state.tor_daemon_status
    detail = st.session_state.tor_daemon_detail

    if status == "ok":
        klass = "zt-ok"
        label = "Tor daemon active"
        dot_color = "#10b981"
    elif status == "error":
        klass = "zt-bad"
        label = "Tor daemon offline"
        dot_color = "#ef4444"
    else:
        klass = "zt-warn"
        label = "Tor daemon unverified"
        dot_color = "#f59e0b"

    st.markdown(
        (
            f"<div class='zt-badge {klass}'>"
            f"<span class='zt-dot' style='background:{dot_color};'></span>{label}</div>"
        ),
        unsafe_allow_html=True,
    )
    st.markdown(f"<div class='zt-small'>{detail}</div>", unsafe_allow_html=True)


def check_lm_studio(lm_url: str) -> tuple[str, str]:
    session = requests.Session()
    session.trust_env = False
    try:
        validate_lm_url(lm_url)
        resp = session.get(
            f"{lm_url.rstrip('/')}/models",
            timeout=(1.5, 3.5),
            allow_redirects=False,
        )
        if resp.ok:
            return "ok", "API is responding correctly."
        return "error", f"API returned HTTP {resp.status_code}."
    except Exception as exc:  # noqa: BLE001
        return "error", str(exc)
    finally:
        session.close()


def check_tor_daemon(port: str) -> tuple[str, str]:
    try:
        port_num = int(port)
        with socket.create_connection(("127.0.0.1", port_num), timeout=1.0):
            return "ok", f"Local port {port_num} is open."
    except Exception as exc:  # noqa: BLE001
        return "error", f"No listener on 127.0.0.1:{port}. ({exc})"


def refresh_service_status(lm_url: str, tor_port: str) -> None:
    active_provider = str(st.session_state.get("active_provider", PROVIDER_LOCAL)).strip()
    if active_provider == PROVIDER_LOCAL:
        lm_status, lm_detail = check_lm_studio(lm_url)
    else:
        provider_cfg = normalize_provider_settings(st.session_state.get("provider_settings", {})).get(active_provider, {})
        provider_api_key = str(provider_cfg.get("api_key", "")).strip()
        if provider_api_key:
            lm_status, lm_detail = "ok", "Remote provider configured."
        else:
            lm_status, lm_detail = "unknown", "Configure an API key for the remote provider."

    tor_status, tor_detail = check_tor_daemon(tor_port)

    st.session_state.lm_status = lm_status
    st.session_state.lm_status_detail = lm_detail
    st.session_state.tor_daemon_status = tor_status
    st.session_state.tor_daemon_detail = tor_detail
    st.session_state.last_monitor_update = datetime.now().strftime("%H:%M:%S")

    if tor_status != "ok":
        st.session_state.tor_verified_status = "unknown"
        st.session_state.tor_verified_detail = "Waiting for Tor daemon before egress verification."
        st.session_state.pending_tor_revalidate = True


def maybe_auto_revalidate_tor(
    lm_url: str,
    model_name: str,
    tor_port: str,
    privacy_profile: str,
    web_enabled: bool,
) -> None:
    model_name_clean = str(model_name or "").strip()
    should_validate = (
        privacy_profile == "max_tor"
        and web_enabled
        and bool(model_name_clean)
        and st.session_state.tor_daemon_status == "ok"
        and (st.session_state.pending_tor_revalidate or st.session_state.tor_verified_status != "ok")
    )
    if not should_validate:
        return

    tor_proxy = tor_proxy_from_port(tor_port)
    ok, detail = verify_tor_now(lm_url=lm_url, model_name=model_name_clean, tor_proxy=tor_proxy)
    st.session_state.tor_verified_status = "ok" if ok else "error"
    st.session_state.tor_verified_detail = detail
    st.session_state.pending_tor_revalidate = not ok


def render_live_monitor(
    lm_url: str,
    model_name: str,
    tor_port: str,
    privacy_profile: str,
    web_enabled: bool,
) -> None:
    startup_deadline = float(st.session_state.get("startup_healthcheck_deadline", 0.0) or 0.0)
    startup_active = time.time() < startup_deadline

    st.session_state.live_monitor_enabled = st.toggle(
        "Live LM/Tor Detection",
        value=st.session_state.live_monitor_enabled,
        help="Refresh statuses automatically without restarting the app.",
    )
    st.session_state.live_monitor_interval = st.slider(
        "Check Interval (sec)",
        min_value=3,
        max_value=20,
        value=int(st.session_state.live_monitor_interval),
    )

    if st.button("Refresh Statuses Now", use_container_width=True):
        refresh_service_status(lm_url, tor_port)
        maybe_auto_revalidate_tor(
            lm_url=lm_url,
            model_name=model_name,
            tor_port=tor_port,
            privacy_profile=privacy_profile,
            web_enabled=web_enabled,
        )
        st.session_state.last_live_monitor_probe_at = time.time()
        st.rerun()

    should_poll = startup_active or bool(st.session_state.live_monitor_enabled)
    poll_interval_seconds = 1 if startup_active else int(st.session_state.live_monitor_interval)
    now = time.time()
    last_probe = float(st.session_state.get("last_live_monitor_probe_at", 0.0) or 0.0)

    if should_poll and (now - last_probe) >= max(1, poll_interval_seconds):
        refresh_service_status(lm_url, tor_port)
        maybe_auto_revalidate_tor(
            lm_url=lm_url,
            model_name=model_name,
            tor_port=tor_port,
            privacy_profile=privacy_profile,
            web_enabled=web_enabled,
        )
        st.session_state.last_live_monitor_probe_at = now
    elif st.session_state.lm_status == "unknown" or st.session_state.tor_daemon_status == "unknown":
        refresh_service_status(lm_url, tor_port)
        maybe_auto_revalidate_tor(
            lm_url=lm_url,
            model_name=model_name,
            tor_port=tor_port,
            privacy_profile=privacy_profile,
            web_enabled=web_enabled,
        )
        st.session_state.last_live_monitor_probe_at = now

    if startup_active:
        remaining = max(0.0, startup_deadline - now)
        st.caption(
            "Initial LM/Tor verification is active "
            f"({remaining:.1f}s remaining) | last: {st.session_state.last_monitor_update}"
        )
    elif should_poll:
        st.caption(
            f"Auto-check every {poll_interval_seconds}s | last: {st.session_state.last_monitor_update}"
        )

    st.caption(f"Last update: {st.session_state.last_monitor_update}")


def build_direct_messages(history: list[dict], context_limit_tokens: int) -> list[dict]:
    system_message = {"role": "system", "content": DIRECT_SYSTEM_PROMPT}
    reserved_for_output = int(os.getenv("LM_MAX_TOKENS", "1200"))
    available_for_prompt = max(512, context_limit_tokens - reserved_for_output)

    system_tokens = estimate_messages_tokens([system_message])
    history_budget = max(256, available_for_prompt - system_tokens)
    history_window = build_history_window_messages(history, token_budget=history_budget)

    return [system_message, *history_window]


def build_rag_messages(
    user_question: str,
    web_results: list[SearchResult],
    history: list[dict],
    context_limit_tokens: int,
) -> list[dict]:
    sources = []
    for idx, result in enumerate(web_results, start=1):
        sources.append(
            f"[{idx}] Title: {result.title}\n"
            f"URL: {result.url}\n"
            f"Snippet: {result.snippet or 'No snippet available.'}"
        )

    web_context = "\n\n".join(sources) if sources else "No web results available."
    reserved_for_output = int(os.getenv("LM_MAX_TOKENS", "1200"))
    available_for_prompt = max(512, context_limit_tokens - reserved_for_output)
    history_text = format_history_for_rag(history, token_budget=max(180, int(available_for_prompt * 0.25)))
    system_prompt = (
        "You are a precise and honest technical assistant. "
        "Use the web context as evidence, cite links with [n] format, "
        "and do not fabricate sources. If data is missing, say so clearly. "
        "Never fabricate links or expose sensitive personal data."
    )
    user_prompt = (
        "Original user question:\n"
        f"{user_question}\n\n"
        "Recent conversation context:\n"
        f"{history_text}\n\n"
        "Context retrieved from the web:\n"
        f"{web_context}\n\n"
        "Respond in the same language the user used, including: summary, key points, and cited links."
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def build_direct_web_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False

    # Add small jitter so retry timing is less fingerprintable.
    retry_kwargs = {
        "total": 2,
        "connect": 2,
        "read": 2,
        "status": 1,
        "backoff_factor": 0.6,
        "status_forcelist": [429, 500, 502, 503, 504],
        "allowed_methods": frozenset({"GET"}),
        "raise_on_status": False,
        "respect_retry_after_header": True,
    }
    retry_jitter = random.uniform(*RETRY_JITTER_RANGE_SECONDS)
    try:
        retry = Retry(backoff_jitter=retry_jitter, **retry_kwargs)
    except TypeError:
        class _RetryWithJitter(Retry):
            def get_backoff_time(self) -> float:  # noqa: ANN001
                base_delay = super().get_backoff_time()
                if base_delay <= 0:
                    return 0.0
                return base_delay + random.uniform(*RETRY_JITTER_RANGE_SECONDS)

        retry = _RetryWithJitter(**retry_kwargs)

    adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(
        {
            # In direct mode (without Tor), use a generic clearnet user-agent.
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "DNT": "1",
            "Sec-GPC": "1",
        }
    )
    return session


def run_iterative_research(
    *,
    user_text: str,
    chat_history: list[dict],
    lm_url: str,
    model_name: str,
    web_mode: str,
    tor_proxy: str,
    searx_instances: list[str],
    tor_web_engine_preference: str,
    context_limit_tokens: int,
    logger,
    active_provider: str | None = None,
    provider_settings: dict | None = None,
    stop_event: threading.Event | None = None,
    on_tor_status=None,
    use_cache: bool = False,
) -> tuple[list[SearchResult], list[dict], bool]:
    """Run iterative web research through the core.rag_agent module."""
    runtime = {
        "re": re,
        "urlparse": urlparse,
        "parse_duckduckgo_redirect": parse_duckduckgo_redirect,
        "strip_html": strip_html,
        "diversify_results": diversify_results,
        "MAX_WEB_RESULTS_POOL_FACTOR": MAX_WEB_RESULTS_POOL_FACTOR,
        "get_max_instance_attempts": get_max_instance_attempts,
        "split_and_sanitize_queries": split_and_sanitize_queries,
        "get_llm_client": get_llm_client,
        "EVALUATOR_MAX_CONTEXT_SOURCES": EVALUATOR_MAX_CONTEXT_SOURCES,
        "sanitize_query_for_antibot": sanitize_query_for_antibot,
        "time": time,
        "create_rag": create_rag,
        "run_coro": run_coro,
        "RESEARCH_MAX_ITERATIONS": RESEARCH_MAX_ITERATIONS,
        "build_search_cache_key": build_search_cache_key,
        "get_cached_search_results": get_cached_search_results,
        "record_search_cache_event": record_search_cache_event,
        "get_secret": get_secret,
        "search_web_direct": search_web_direct,
        "put_cached_search_results": put_cached_search_results,
        "build_rag_messages": build_rag_messages,
        "build_direct_messages": build_direct_messages,
        "close_rag_safely": close_rag_safely,
    }
    return core_run_research_with_runtime(
        runtime,
        user_text=user_text,
        chat_history=chat_history,
        lm_url=lm_url,
        model_name=model_name,
        web_mode=web_mode,
        tor_proxy=tor_proxy,
        searx_instances=searx_instances,
        tor_web_engine_preference=tor_web_engine_preference,
        context_limit_tokens=context_limit_tokens,
        logger=logger,
        active_provider=active_provider,
        provider_settings=provider_settings,
        stop_event=stop_event,
        on_tor_status=on_tor_status,
        use_cache=use_cache,
    )

def render_copy_button(response_text: str, key_suffix: str) -> None:
    safe_key = re.sub(r"[^a-zA-Z0-9_-]", "_", key_suffix)
    payload = json.dumps(str(response_text or ""), ensure_ascii=False)
    html = f"""
    <div style=\"margin-top:0.45rem;\">
      <button id=\"copy-btn-{safe_key}\" style=\"
        border:1px solid rgba(148,163,184,.45);
        background:rgba(15,23,42,.8);
        color:#e2e8f0;
        border-radius:10px;
        padding:0.26rem 0.62rem;
        cursor:pointer;
        font-size:0.78rem;
      \">
        &#128203; Copy
      </button>
      <span id=\"copy-msg-{safe_key}\" style=\"margin-left:.5rem;color:#9ca3af;font-size:.74rem;\"></span>
    </div>
    <script>
      const textToCopy = {payload};
      const btn = document.getElementById("copy-btn-{safe_key}");
      const msg = document.getElementById("copy-msg-{safe_key}");
      async function doCopy() {{
        try {{
          await navigator.clipboard.writeText(textToCopy);
          msg.textContent = "Copied";
        }} catch (err) {{
          const ta = document.createElement("textarea");
          ta.value = textToCopy;
          document.body.appendChild(ta);
          ta.select();
          document.execCommand("copy");
          document.body.removeChild(ta);
          msg.textContent = "Copied";
        }}
        setTimeout(() => {{ msg.textContent = ""; }}, 1500);
      }}
      btn.addEventListener("click", doCopy);
    </script>
    """
    iframe_src = "data:text/html;charset=utf-8," + quote(html, safe="")
    st.iframe(iframe_src, height=44)


def generate_response_worker(job: dict) -> None:
    event_queue: queue.Queue = job["event_queue"]
    stop_event: threading.Event = job["stop_event"]

    def emit(event_type: str, payload) -> None:
        try:
            event_queue.put((event_type, payload), timeout=GENERATION_EVENT_PUT_TIMEOUT_SECONDS)
        except queue.Full:
            pass

    def log(message: str) -> None:
        emit("log", message)

    user_text = job["user_text"]
    chat_history = job["chat_history"]
    lm_url = job["lm_url"]
    model_name = job["model_name"]
    tor_proxy = job["tor_proxy"]
    privacy_profile = job["privacy_profile"]
    web_enabled = job["web_enabled"]
    searx_instances = job["searx_instances"]
    tor_web_engine_preference = job["tor_web_engine_preference"]
    smart_web_mode = job["smart_web_mode"]
    context_limit_tokens = int(job["context_limit_tokens"])
    active_provider = str(job.get("active_provider", PROVIDER_LOCAL)).strip()
    provider_settings = normalize_provider_settings(job.get("provider_settings", {}))
    llm_thinking_enabled = bool(job.get("llm_thinking_enabled", False))

    try:
        profile_cfg = PRIVACY_PROFILES[privacy_profile]
        web_mode = profile_cfg["web_mode"]
        use_web_now = (
            web_enabled
            and web_mode in {"tor", "direct", "brave"}
            and should_use_web_search(user_text=user_text, smart_mode=smart_web_mode)
        )

        log(build_msg_start_log(user_text))
        log(f"User input received ({summarize_query_for_log(user_text)}).")
        log(f"Web search decision: {'YES' if use_web_now else 'NO'}")

        sources: list[SearchResult] = []

        if use_web_now:
            if stop_event.is_set():
                emit("done", {"text": "", "sources": None, "stopped": True})
                return

            try:
                sources, llm_messages, _ = run_iterative_research(
                    user_text=user_text,
                    chat_history=chat_history,
                    lm_url=lm_url,
                    model_name=model_name,
                    web_mode=web_mode,
                    tor_proxy=tor_proxy,
                    searx_instances=searx_instances,
                    tor_web_engine_preference=tor_web_engine_preference,
                    context_limit_tokens=context_limit_tokens,
                    logger=log,
                    active_provider=active_provider,
                    provider_settings=provider_settings,
                    stop_event=stop_event,
                    on_tor_status=lambda status, detail: emit("tor_status", (status, detail)),
                    use_cache=False,
                )
            except Exception as search_exc:  # noqa: BLE001
                log(f"Web search failed: {search_exc}. The model will try to answer with local knowledge.")
                if web_mode == "tor":
                    emit("tor_status", ("error", str(search_exc)))
                sources = []
                llm_messages = build_direct_messages(
                    chat_history,
                    context_limit_tokens=context_limit_tokens,
                )
        else:
            llm_messages = build_direct_messages(chat_history, context_limit_tokens=context_limit_tokens)

        if stop_event.is_set():
            emit("done", {"text": "", "sources": None, "stopped": True})
            return

        llm_messages = inject_thinking_prompt_into_messages(
            llm_messages,
            thinking_enabled=llm_thinking_enabled,
        )
        serialized_sources = [asdict(item) for item in sources] if sources else None
        emit("rag_done", {"messages": llm_messages, "sources": serialized_sources})
    except Exception as exc:  # noqa: BLE001
        emit("error", str(exc))


def start_generation_job(
    conv_id: str,
    user_text: str,
    chat_history: list[dict],
    lm_url: str,
    model_name: str,
    tor_proxy: str,
    privacy_profile: str,
    web_enabled: bool,
    tor_web_engine_preference: str,
    searx_instances: list[str],
    smart_web_mode: bool,
    context_limit_tokens: int,
    active_provider: str,
    provider_settings: dict,
    llm_thinking_enabled: bool,
) -> None:
    if st.session_state.generation_active:
        return

    # Bounded queue prevents unbounded growth and CPU spikes under backpressure.
    event_queue: queue.Queue = queue.Queue(maxsize=GENERATION_EVENT_QUEUE_MAXSIZE)
    stop_event = threading.Event()

    st.session_state.generation_active = True
    st.session_state.generation_queue = event_queue
    st.session_state.generation_stop_event = stop_event
    st.session_state.generation_buffer = ""
    st.session_state.generation_sources = None
    st.session_state.generation_rag_done = False
    st.session_state.generation_messages = None
    st.session_state.generation_target_conv_id = conv_id
    st.session_state.generation_cancel_requested = False
    st.session_state.generation_last_render_len = 0
    st.session_state.generation_last_render_at = 0.0

    job = {
        "event_queue": event_queue,
        "stop_event": stop_event,
        "user_text": user_text,
        "chat_history": [dict(m) for m in chat_history],
        "lm_url": lm_url,
        "model_name": model_name,
        "tor_proxy": tor_proxy,
        "privacy_profile": privacy_profile,
        "web_enabled": web_enabled,
        "tor_web_engine_preference": tor_web_engine_preference,
        "searx_instances": list(searx_instances),
        "smart_web_mode": smart_web_mode,
        "context_limit_tokens": int(context_limit_tokens),
        "active_provider": str(active_provider or PROVIDER_LOCAL),
        "provider_settings": normalize_provider_settings(provider_settings),
        "llm_thinking_enabled": bool(llm_thinking_enabled),
    }

    worker = threading.Thread(
        target=generate_response_worker,
        args=(job,),
        daemon=True,
        name=f"zt-gen-{conv_id[:8]}",
    )
    st.session_state.generation_thread = worker
    save_conversation_to_disk(get_current_conversation())
    worker.start()


def request_stop_generation() -> None:
    if bool(st.session_state.get("generation_cancel_requested", False)):
        return

    stop_event = st.session_state.generation_stop_event
    if isinstance(stop_event, threading.Event):
        stop_event.set()

    st.session_state.generation_cancel_requested = True


def finalize_cancelled_generation_now() -> None:
    conv_id = st.session_state.generation_target_conv_id or st.session_state.current_conversation_id
    conv = get_conversation_by_id(conv_id)
    partial_text = str(st.session_state.get("generation_buffer", "") or "").strip()
    normalized_partial_text = normalize_thinking_markup_for_storage(partial_text)
    thinking_elapsed = float(st.session_state.get("generation_think_elapsed", 0.0) or 0.0)

    if conv is not None and normalized_partial_text:
        conv["messages"].append(
            {
                "role": "assistant",
                "content": f"{normalized_partial_text}\n\n[Response stopped by user.]",
                "sources": st.session_state.get("generation_sources"),
                "thinking_elapsed_seconds": thinking_elapsed if thinking_elapsed > 0.0 else None,
            }
        )
        save_conversation_to_disk(conv)

    append_log(conv_id, "Generation stopped by user.")
    reset_generation_state()


def drain_generation_events() -> tuple[bool, bool]:
    event_queue = st.session_state.generation_queue
    if not isinstance(event_queue, queue.Queue):
        return False, False

    conv_id = st.session_state.generation_target_conv_id
    conv = get_conversation_by_id(conv_id)
    if conv is None:
        reset_generation_state()
        return True, True

    changed, logs_changed = False, False
    while True:
        try:
            event_type, payload = event_queue.get_nowait()
        except queue.Empty:
            break

        if event_type == "log":
            append_log(conv_id, str(payload))
            changed = logs_changed = True
        elif event_type == "tor_status":
            st.session_state.tor_verified_status, st.session_state.tor_verified_detail = payload
            changed = logs_changed = True
        elif event_type == "rag_done":
            st.session_state.generation_rag_done = True
            st.session_state.generation_messages = payload.get("messages")
            st.session_state.generation_sources = payload.get("sources")
            changed = logs_changed = True
        elif event_type in {"done", "error"}:
            if event_type == "error":
                err_text = f"Error: {payload}"
                conv["messages"].append({"role": "assistant", "content": err_text})
                append_log(conv_id, err_text)
                st.session_state.tor_verified_status = "error"
                st.session_state.tor_verified_detail = str(payload)
            reset_generation_state()
            changed = logs_changed = True

    if changed and conv_id == st.session_state.current_conversation_id:
        save_conversation_to_disk(conv)

    return changed, logs_changed


def extract_results(payload: dict, top_k: int) -> list[SearchResult]:
    raw_results = payload.get("results", [])
    clean: list[SearchResult] = []
    pool_limit = max(top_k, top_k * MAX_WEB_RESULTS_POOL_FACTOR)
    seen_urls = set()

    for item in raw_results:
        title = ZeroTraceRAG._normalize_text(item.get("title", ""))[:220]
        url = ZeroTraceRAG._strip_tracking_params(ZeroTraceRAG._normalize_text(item.get("url", "")))
        snippet = ZeroTraceRAG._normalize_text(item.get("content", ""))[:600]

        if not title or not url or url in seen_urls:
            continue

        seen_urls.add(url)
        clean.append(SearchResult(title=title, url=url, snippet=snippet))
        if len(clean) >= pool_limit:
            break

    return diversify_results(clean, top_k)


def search_web_direct(query: str, searx_instances: list[str], top_k: int = 5) -> list[SearchResult]:
    sanitized_query, _ = ZeroTraceRAG._sanitize_web_query(query)
    if len(sanitized_query) < 3:
        raise PrivacyError("Query became too short after sanitization.")

    # Exclude onion destinations in direct mode to avoid DNS resolution failures outside Tor.
    clearnet_instances = [url for url in searx_instances if not is_onion_instance_url(url)]
    try:
        instances = ZeroTraceRAG._sanitize_instances(clearnet_instances)
    except ValueError:
        instances = []

    params = {
        "q": sanitized_query,
        "format": "json",
        "language": "en-US",
        "safesearch": 0,
    }

    session = build_direct_web_session()
    failures = []
    try:
        if instances:
            ordered_instances = random.sample(instances, k=len(instances))
            max_attempts = get_max_instance_attempts()
            if len(ordered_instances) > max_attempts:
                failures.append(
                    f"instancias limitadas por latencia: {max_attempts}/{len(ordered_instances)}"
                )
                ordered_instances = ordered_instances[:max_attempts]

            for base_url in ordered_instances:
                endpoint = f"{base_url}/search"
                try:
                    parsed = urlparse(endpoint)
                    host = (parsed.hostname or "").lower()
                    if parsed.scheme != "https" or not host:
                        failures.append(f"{base_url}: invalid endpoint")
                        continue
                    if ZeroTraceRAG._is_blocked_host(host):
                        failures.append(f"{base_url}: blocked host")
                        continue

                    resp = session.get(
                        endpoint,
                        params=params,
                        timeout=(8, 25),
                        allow_redirects=False,
                    )
                    if 300 <= resp.status_code < 400:
                        failures.append(f"{base_url}: redirect blocked")
                        continue
                    if resp.status_code in {403, 429, 503}:
                        failures.append(f"{base_url}: HTTP rejected {resp.status_code}")
                        continue

                    resp.raise_for_status()
                    payload = resp.json()
                    results = extract_results(payload, top_k)
                    if results:
                        return results
                    failures.append(f"{base_url}: no useful results")
                except (RequestException, ValueError) as exc:
                    failures.append(f"{base_url}: {exc}")
        else:
            failures.append("No valid clearnet SearXNG instances for direct mode.")

        # Direct fallbacks improve success rate when SearXNG is blocked or rate-limited.
        try:
            ddg_results = search_duckduckgo_direct(sanitized_query, top_k=top_k, session=session)
            if ddg_results:
                return ddg_results
            failures.append("DuckDuckGo HTML: no useful results")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"DuckDuckGo HTML: {exc}")

        try:
            wiki_results = search_wikipedia_direct(sanitized_query, top_k=top_k, session=session)
            if wiki_results:
                return wiki_results
            failures.append("Wikipedia API: no useful results")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"Wikipedia API: {exc}")
    finally:
        session.close()

    detail = " | ".join(failures) if failures else "no details"
    raise RuntimeError(f"Could not get web results in direct mode. Details: {detail}")


def search_duckduckgo_direct(
    query: str,
    top_k: int = 5,
    *,
    session: requests.Session | None = None,
) -> list[SearchResult]:
    sanitized_query, _ = ZeroTraceRAG._sanitize_web_query(query)
    if len(sanitized_query) < 3:
        return []

    owns_session = session is None
    client = session or build_direct_web_session()
    try:
        resp = client.get(
            "https://html.duckduckgo.com/html/",
            params={"q": sanitized_query, "kl": "wt-wt"},
            timeout=(8, 25),
            allow_redirects=False,
        )
        if 300 <= resp.status_code < 400:
            raise RuntimeError("redirect blocked")
        if resp.status_code in {403, 429, 503}:
            raise RuntimeError(f"HTTP rejected {resp.status_code}")
        resp.raise_for_status()

        html_text = resp.text
        link_matches = list(
            re.finditer(
                r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                html_text,
                flags=re.IGNORECASE | re.DOTALL,
            )
        )
        snippet_matches = re.findall(
            r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
            html_text,
            flags=re.IGNORECASE | re.DOTALL,
        )

        results: list[SearchResult] = []
        pool_limit = max(top_k, top_k * MAX_WEB_RESULTS_POOL_FACTOR)
        seen_urls = set()
        for idx, match in enumerate(link_matches):
            raw_url = parse_duckduckgo_redirect(match.group(1).strip())
            parsed = urlparse(raw_url)
            host = (parsed.hostname or "").lower()
            if parsed.scheme not in {"http", "https"} or not host:
                continue
            if ZeroTraceRAG._is_blocked_host(host):
                continue

            clean_url = ZeroTraceRAG._strip_tracking_params(raw_url)
            if not clean_url or clean_url in seen_urls:
                continue

            title = strip_html(match.group(2))[:220]
            snippet = strip_html(snippet_matches[idx] if idx < len(snippet_matches) else "")[:600]
            if not title:
                continue

            seen_urls.add(clean_url)
            results.append(SearchResult(title=title, url=clean_url, snippet=snippet))
            if len(results) >= pool_limit:
                break

        return diversify_results(results, top_k)
    finally:
        if owns_session:
            client.close()


def search_wikipedia_direct(
    query: str,
    top_k: int = 5,
    *,
    session: requests.Session | None = None,
) -> list[SearchResult]:
    sanitized_query, _ = ZeroTraceRAG._sanitize_web_query(query)
    if len(sanitized_query) < 3:
        return []

    owns_session = session is None
    client = session or build_direct_web_session()
    try:
        pool_limit = max(top_k, top_k * MAX_WEB_RESULTS_POOL_FACTOR)
        resp = client.get(
            "https://es.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "format": "json",
                "utf8": 1,
                "srlimit": min(pool_limit, 20),
                "srsearch": sanitized_query,
            },
            timeout=(8, 25),
            allow_redirects=False,
        )
        if 300 <= resp.status_code < 400:
            raise RuntimeError("redirect blocked")
        if resp.status_code in {403, 429, 503}:
            raise RuntimeError(f"HTTP rejected {resp.status_code}")
        resp.raise_for_status()
        payload = resp.json()

        results: list[SearchResult] = []
        for item in (payload.get("query", {}) or {}).get("search", []):
            title = " ".join(str(item.get("title", "")).split())[:220]
            pageid = item.get("pageid")
            snippet = strip_html(str(item.get("snippet", "")))[:600]
            if not title or not pageid:
                continue
            url = f"https://es.wikipedia.org/?curid={pageid}"
            results.append(SearchResult(title=title, url=url, snippet=snippet))
            if len(results) >= pool_limit:
                break

        return diversify_results(results, top_k)
    finally:
        if owns_session:
            client.close()


def stream_local_llm(
    messages: list[dict],
    lm_url: str,
    model_name: str,
    *,
    active_provider: str | None = None,
    provider_settings: dict | None = None,
) -> Generator[str, None, None]:
    client = get_llm_client(
        lm_url=lm_url,
        active_provider=active_provider,
        provider_settings=provider_settings,
    )

    try:
        stream = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0.2,
            max_tokens=int(os.getenv("LM_MAX_TOKENS", "1200")),
            stream=True,
        )

        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content or ""
            if delta:
                yield delta
    except APITimeoutError as exc:
        raise RuntimeError("Timeout al conectar con el proveedor LLM activo.") from exc
    except APIConnectionError as exc:
        raise RuntimeError("Could not connect to the active LLM provider at the configured base URL.") from exc
    except APIStatusError as exc:
        raise RuntimeError(f"El proveedor LLM activo devolvio error HTTP: {exc.status_code}") from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Error inesperado en streaming del LLM: {exc}") from exc
    finally:
        try:
            client.close()
        except Exception:
            pass


def render_sources(sources: list[dict] | None) -> None:
    if not sources:
        return

    with st.expander("Sources Used", expanded=False):
        for idx, src in enumerate(sources, start=1):
            title = src.get("title", "Untitled")
            url = src.get("url", "")
            snippet = src.get("snippet", "") or "No snippet available."

            st.markdown(f"**[{idx}] {title}**")
            if url:
                st.markdown(f"[{url}]({url})")
            st.caption(snippet)
            if idx < len(sources):
                st.divider()


def render_cache_indicator(from_cache: bool) -> None:
    if not from_cache:
        return
    st.markdown(
        "<div class='zt-cache-indicator'>Resultado servido desde cache efimera de sesion.</div>",
        unsafe_allow_html=True,
    )


def split_thinking_blocks(raw_text: str) -> list[tuple[str, str, bool]]:
    text = str(raw_text or "")
    # Normaliza variantes de formato para robustecer el parser (< THINK >, </ Think>, etc.).
    text = re.sub(r"<\s*think\s*>", "<think>", text, flags=re.IGNORECASE)
    text = re.sub(r"<\s*/\s*think\s*>", "</think>", text, flags=re.IGNORECASE)

    blocks: list[tuple[str, str, bool]] = []
    cursor = 0
    open_tag = "<think>"
    close_tag = "</think>"

    def _strip_inner_think_tags(value: str) -> str:
        return str(value or "").replace(open_tag, "").replace(close_tag, "")

    while True:
        start_idx = text.find(open_tag, cursor)
        if start_idx < 0:
            tail = text[cursor:]
            if tail:
                blocks.append(("text", tail, True))
            break

        before = text[cursor:start_idx]
        if before:
            blocks.append(("text", before, True))

        think_start = start_idx + len(open_tag)
        first_end_idx = text.find(close_tag, think_start)
        last_end_idx = text.rfind(close_tag, think_start)

        end_idx = first_end_idx
        if first_end_idx >= 0 and last_end_idx > first_end_idx:
            next_open_after_first_close = text.find(open_tag, first_end_idx + len(close_tag))
            if next_open_after_first_close < 0:
                # If repeated close tags appear without new <think>, use the last close tag.
                end_idx = last_end_idx

        if end_idx < 0:
            blocks.append(("think", _strip_inner_think_tags(text[think_start:]), False))
            break

        think_body = _strip_inner_think_tags(text[think_start:end_idx])
        blocks.append(("think", think_body, True))
        cursor = end_idx + len(close_tag)

    if not blocks:
        return [("text", text, True)]
    return blocks


def normalize_thinking_markup_for_storage(raw_text: str) -> str:
    blocks = split_thinking_blocks(raw_text)
    normalized_parts: list[str] = []

    for block_type, block_text, _closed in blocks:
        if block_type == "text":
            clean_text = str(block_text or "").replace("<think>", "").replace("</think>", "")
            if clean_text:
                normalized_parts.append(clean_text)
            continue

        think_text = str(block_text or "").strip()
        if think_text:
            # Se guarda en formato canonico para evitar cierres erraticos por etiquetas internas.
            normalized_parts.append(f"<think>{think_text}</think>")

    return "".join(normalized_parts).strip()


def ensure_thinking_block_output(raw_text: str, thinking_enabled: bool) -> str:
    text = str(raw_text or "").strip()
    if not thinking_enabled:
        return text

    has_think_tag = bool(re.search(r"<\s*think\s*>", text, flags=re.IGNORECASE))
    if has_think_tag:
        return text

    fallback = "<think>Model reasoning is not exposed; returning a direct answer.</think>"
    return f"{fallback}\n{text}" if text else fallback


def update_generation_think_timer(partial_text: str) -> float | None:
    blocks = split_thinking_blocks(partial_text)
    has_open_think = any(block_type == "think" and not closed for block_type, _text, closed in blocks)
    has_closed_think = any(block_type == "think" and closed for block_type, _text, closed in blocks)

    now = time.time()
    started_at = float(st.session_state.get("generation_think_started_at", 0.0) or 0.0)
    elapsed = float(st.session_state.get("generation_think_elapsed", 0.0) or 0.0)

    if has_open_think:
        if started_at <= 0.0:
            started_at = now
            st.session_state.generation_think_started_at = started_at
        st.session_state.generation_think_closed = False
        elapsed = max(0.0, now - started_at)
        st.session_state.generation_think_elapsed = elapsed
        return elapsed

    if has_closed_think:
        if started_at > 0.0 and not bool(st.session_state.get("generation_think_closed", False)):
            elapsed = max(0.0, now - started_at)
            st.session_state.generation_think_elapsed = elapsed
        st.session_state.generation_think_closed = True
        frozen = float(st.session_state.get("generation_think_elapsed", 0.0) or 0.0)
        return frozen if frozen > 0.0 else None

    return None


def render_assistant_content(content: str, thinking_elapsed_seconds: float | None = None) -> None:
    ui_render_assistant_content(
        content,
        thinking_elapsed_seconds=thinking_elapsed_seconds,
        split_thinking_blocks_fn=split_thinking_blocks,
    )


def render_message_bubble(
    role: str,
    content: str,
    sources: list[dict] | None = None,
    *,
    from_cache: bool = False,
    copy_key: str | None = None,
    thinking_elapsed_seconds: float | None = None,
) -> None:
    ui_render_message_bubble(
        role=role,
        content=content,
        sources=sources,
        from_cache=from_cache,
        copy_key=copy_key,
        thinking_elapsed_seconds=thinking_elapsed_seconds,
        split_thinking_blocks_fn=split_thinking_blocks,
        render_cache_indicator_fn=render_cache_indicator,
        render_sources_fn=render_sources,
        render_copy_button_fn=render_copy_button,
    )


def sidebar_controls() -> tuple[str, str, str, bool, str, List[str]]:
    """Render sidebar controls through the ui.sidebar module."""
    runtime = {
        "save_ui_settings_to_disk": save_ui_settings_to_disk,
        "save_conversation_to_disk": save_conversation_to_disk,
        "create_new_conversation": create_new_conversation,
        "delete_current_conversation": delete_current_conversation,
        "ensure_provider_state_consistency": ensure_provider_state_consistency,
        "PROVIDER_OPTIONS": PROVIDER_OPTIONS,
        "safe_option_index": safe_option_index,
        "sync_active_provider_runtime_state": sync_active_provider_runtime_state,
        "DEFAULT_LM_URL": DEFAULT_LM_URL,
        "DEFAULT_OPENAI_COMPAT_URL": DEFAULT_OPENAI_COMPAT_URL,
        "OPENROUTER_BASE_URL": OPENROUTER_BASE_URL,
        "PROVIDER_LOCAL": PROVIDER_LOCAL,
        "PROVIDER_OPENAI_COMPAT": PROVIDER_OPENAI_COMPAT,
        "PROVIDER_OPENROUTER": PROVIDER_OPENROUTER,
        "_normalize_provider_custom_models": _normalize_provider_custom_models,
        "DEFAULT_PROVIDER_MODELS": DEFAULT_PROVIDER_MODELS,
        "save_provider_credentials_to_vault": save_provider_credentials_to_vault,
        "save_brave_api_key_to_vault": save_brave_api_key_to_vault,
        "MAX_CONTEXT_LIMIT_TOKENS": MAX_CONTEXT_LIMIT_TOKENS,
        "render_lm_badge": render_lm_badge,
        "PRIVACY_PROFILES": PRIVACY_PROFILES,
        "DEFAULT_TOR_PORT": DEFAULT_TOR_PORT,
        "TOR_WEB_ENGINE_OPTIONS": TOR_WEB_ENGINE_OPTIONS,
        "render_tor_daemon_badge": render_tor_daemon_badge,
        "render_tor_badge": render_tor_badge,
        "tor_proxy_from_port": tor_proxy_from_port,
        "verify_tor_now": verify_tor_now,
        "render_live_monitor": render_live_monitor,
        "clear_search_cache": clear_search_cache,
        "get_current_conversation": get_current_conversation,
        "save_current_conversation": save_current_conversation,
        "parse_searx_instances": parse_searx_instances,
        "re": re,
    }
    return ui_sidebar_controls(runtime)


def render_chat_history(messages: list[dict]) -> None:
    ui_render_chat_history(messages, render_message_bubble_fn=render_message_bubble)


def render_logs_console(conversation: dict, placeholder=None) -> None:
    ui_render_logs_console(
        conversation,
        generation_active=bool(st.session_state.generation_active),
        placeholder=placeholder,
    )


def render_token_meter(messages: list[dict], context_limit_tokens: int) -> None:
    in_use_tokens, full_history_tokens = compute_conversation_tokens_in_use(messages, context_limit_tokens)
    ratio = min(1.0, in_use_tokens / max(1, context_limit_tokens))
    percent = ratio * 100

    if percent >= 90:
        bar_color = "#ef4444"
    elif percent >= 70:
        bar_color = "#f59e0b"
    else:
        bar_color = "#10b981"

    st.markdown(
        (
            "<div class='zt-sticky-context'>"
            "<div class='zt-sticky-topline'>"
            f"<span>Context in use: <strong>{in_use_tokens}/{context_limit_tokens}</strong> tokens</span>"
            f"<span><strong>{percent:.1f}%</strong></span>"
            "</div>"
            "<div class='zt-token-track'>"
            f"<div class='zt-token-fill' style='width:{percent:.2f}%; background:{bar_color};'></div>"
            "</div>"
            f"<div class='zt-sticky-subline'>Total stored history: {full_history_tokens} estimated tokens.</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )
    st.markdown("<div class='zt-context-spacer'></div>", unsafe_allow_html=True)


def render_chat_input_mode_style(is_generating: bool) -> None:
    if not is_generating:
        return
    st.markdown(
        """
        <style>
            [data-testid="stChatInput"] button,
            [data-testid="stChatInputSubmitButton"],
            [data-testid="stChatInput"] [aria-label*="Send"],
            [data-testid="stChatInput"] [aria-label*="Enviar"] {
                display: none !important;
                visibility: hidden !important;
                opacity: 0 !important;
                pointer-events: none !important;
            }

            .st-key-cancel_generation_button {
                position: fixed;
                right: calc(var(--zt-right-console-width) + var(--zt-right-gap) + 2.1rem);
                bottom: 1.9rem;
                z-index: 2000;
                width: 2.45rem;
            }

            .st-key-cancel_generation_button button {
                width: 2.45rem;
                height: 2.45rem;
                min-height: 2.45rem;
                border-radius: 0.65rem;
                border: 1px solid rgba(148, 163, 184, 0.35);
                background: rgba(30, 41, 59, 0.95);
                color: #e5e7eb;
                font-weight: 700;
            }

            @media (max-width: 1200px) {
                .st-key-cancel_generation_button {
                    right: 1.8rem;
                    bottom: 1.7rem;
                }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    inject_styles()
    init_session_state()
    ensure_conversation_state()

    try:
        lm_url, model_name, tor_proxy, web_enabled, tor_web_engine_preference, searx_instances = sidebar_controls()
    except Exception:
        if not bool(st.session_state.get("sidebar_widget_recovery_attempted", False)):
            st.session_state.sidebar_widget_recovery_attempted = True
            clear_dynamic_sidebar_widget_state()
            st.rerun()
        st.session_state.sidebar_widget_recovery_attempted = False
        raise

    st.session_state.sidebar_widget_recovery_attempted = False
    current_conv = get_current_conversation()
    messages = current_conv["messages"]
    profile_key = st.session_state.privacy_profile
    profile_label = PRIVACY_PROFILES[profile_key]["label"]
    context_limit_tokens = get_context_limit_tokens()

    # Drain worker events and render console immediately.
    drain_generation_events()
    render_logs_console(current_conv)

    st.markdown("<div class='zt-header'>Zero-Trace RAG Chat</div>", unsafe_allow_html=True)
    st.markdown(
        (
            "<div class='zt-subtitle'>ChatGPT-style interface for LM Studio. "
            f"Current profile: {profile_label}.</div>"
        ),
        unsafe_allow_html=True,
    )
    render_token_meter(messages, context_limit_tokens)

    render_chat_history(messages)
    render_chat_input_mode_style(bool(st.session_state.generation_active))

    if st.session_state.generation_active:
        if st.session_state.get("generation_rag_done", False):
            # Phase 2: RAG finished. Native smooth streaming on the main thread.
            st.chat_input("Writing response...", disabled=True, key="main_chat_input_streaming")

            # Reuse the same column layout as render_message_bubble.
            bubble_col, _, right_spacer = st.columns([1.75, 0.35, 0.9], gap="small")
            _ = right_spacer

            with bubble_col:
                with st.chat_message("assistant"):
                    sources = st.session_state.get("generation_sources")
                    render_sources(sources)

                    try:
                        # stream_local_llm returns a generator compatible with write_stream.
                        stream_gen = stream_local_llm(
                            messages=st.session_state.generation_messages,
                            lm_url=lm_url,
                            model_name=model_name,
                            active_provider=st.session_state.active_provider,
                            provider_settings=st.session_state.provider_settings,
                        )
                        # Streamlit handles token-by-token rendering efficiently.
                        answer_text = st.write_stream(stream_gen)

                        answer_text = ensure_thinking_block_output(
                            answer_text,
                            bool(st.session_state.llm_thinking_enabled),
                        )

                        current_conv["messages"].append(
                            {
                                "role": "assistant",
                                "content": answer_text,
                                "sources": sources,
                            }
                        )
                        append_log(current_conv["id"], "Generation completed successfully.")
                        save_current_conversation()
                    except Exception as exc:
                        st.error(f"Streaming error: {exc}")
                        append_log(current_conv["id"], f"Error: {exc}")
                    finally:
                        reset_generation_state()
                        st.rerun()
        else:
            # Phase 1: RAG still running in the worker.
            st.chat_input("Searching for information...", disabled=True, key="main_chat_input_disabled")
            cancel_requested = bool(st.session_state.get("generation_cancel_requested", False))
            if st.button("✕", key="cancel_generation_button", help="Cancel generation", disabled=cancel_requested):
                request_stop_generation()
                finalize_cancelled_generation_now()
                st.rerun()

            # Near-real-time refresh cycle for the right-side console.
            time.sleep(0.3)
            st.rerun()
        return

    user_input = st.chat_input("Write your message...", disabled=False, key="main_chat_input")

    if not user_input:
        return

    clean_input = user_input.strip()
    if not clean_input:
        return

    had_user_messages_before = any(str(msg.get("role", "")) == "user" for msg in messages if isinstance(msg, dict))
    current_title = str(current_conv.get("title", "")).strip()
    if not had_user_messages_before and should_auto_name_conversation(current_title):
        current_conv["title"] = build_auto_conversation_title(clean_input)

    messages.append({"role": "user", "content": clean_input})
    append_log(current_conv["id"], "User sent a message.")
    save_current_conversation()

    start_generation_job(
        conv_id=current_conv["id"],
        user_text=clean_input,
        chat_history=messages,
        lm_url=lm_url,
        model_name=model_name,
        tor_proxy=tor_proxy,
        privacy_profile=profile_key,
        web_enabled=web_enabled,
        tor_web_engine_preference=tor_web_engine_preference,
        searx_instances=searx_instances,
        smart_web_mode=bool(st.session_state.auto_web_for_informational_queries),
        context_limit_tokens=context_limit_tokens,
        active_provider=st.session_state.active_provider,
        provider_settings=st.session_state.provider_settings,
        llm_thinking_enabled=bool(st.session_state.llm_thinking_enabled),
    )

    st.rerun()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        st.error(
            "An internal UI error was detected. "
            "The screen should not remain blank; review technical details below."
        )
        st.exception(exc)
