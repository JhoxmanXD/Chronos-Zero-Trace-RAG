"""Persistence and JSON normalization helpers for chat and model storage."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONVERSATIONS_DIR = PROJECT_ROOT / "conversations_json"
CHAT_STORE_PATH = CONVERSATIONS_DIR / "chats_store.json"
MODELS_STORE_PATH = CONVERSATIONS_DIR / "custom_models.json"
CHAT_SCHEMA_VERSION = 2

SAVE_CONVERSATION_LOCK = threading.Lock()
SAVE_MODELS_LOCK = threading.Lock()


def ensure_conversations_dir() -> Path:
    """Ensure the conversations storage directory exists.

    Returns:
        Path: The conversations directory path.
    """
    CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
    return CONVERSATIONS_DIR


def utc_now() -> datetime:
    """Return the current UTC datetime.

    Returns:
        datetime: Current UTC datetime.
    """
    return datetime.now(timezone.utc)


def make_default_conversation(
    conv_id: str | None = None,
    *,
    is_incognito: bool = True,
    title: str | None = None,
) -> dict:
    """Create a normalized default conversation payload.

    Args:
        conv_id: Optional explicit conversation id.
        is_incognito: Whether this conversation should skip disk persistence.
        title: Optional explicit title.

    Returns:
        dict: Conversation payload.
    """
    conv_id = conv_id or f"conv-{uuid.uuid4().hex[:8]}"
    default_title = "Incognito chat" if is_incognito else "Regular chat"
    return {
        "id": conv_id,
        "title": title or default_title,
        "messages": [],
        "logs": [],
        "created_at": utc_now().isoformat(),
        "is_incognito": bool(is_incognito),
    }


def normalize_loaded_conversation(payload: dict) -> dict | None:
    """Validate and normalize conversation payloads loaded from disk.

    Args:
        payload: Raw conversation payload.

    Returns:
        dict | None: Normalized conversation, or None when invalid.
    """
    conv_id = str(payload.get("id", "")).strip()
    title = str(payload.get("title", "")).strip() or "Untitled chat"
    created_at = str(payload.get("created_at", "")).strip() or utc_now().isoformat()
    messages = payload.get("messages", [])
    logs = payload.get("logs", [])

    if not conv_id or not isinstance(messages, list):
        return None

    normalized_messages = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content", "")
        if role not in {"user", "assistant"}:
            continue
        normalized_messages.append(
            {
                "role": role,
                "content": str(content),
                "sources": msg.get("sources"),
            }
        )

    normalized_logs = []
    if isinstance(logs, list):
        normalized_logs = [str(line) for line in logs if isinstance(line, (str, int, float))]

    return {
        "id": conv_id,
        "title": title,
        "messages": normalized_messages,
        "logs": normalized_logs,
        "created_at": created_at,
        "is_incognito": bool(payload.get("is_incognito", False)),
    }


def build_store_payload(conversations: dict[str, dict]) -> dict:
    """Build a versioned chat storage payload with non-incognito conversations only.

    Args:
        conversations: In-memory conversations dictionary.

    Returns:
        dict: JSON-ready storage payload.
    """
    chats: dict[str, dict] = {}
    for conv_id, conversation in (conversations or {}).items():
        if not isinstance(conversation, dict):
            continue
        if bool(conversation.get("is_incognito", False)):
            continue

        normalized = normalize_loaded_conversation(conversation)
        if normalized is None:
            continue
        normalized["id"] = conv_id
        chats[conv_id] = normalized

    return {"version": CHAT_SCHEMA_VERSION, "chats": chats}


def save_conversations_to_disk(conversations: dict[str, dict]) -> None:
    """Persist all non-incognito conversations to disk.

    Args:
        conversations: In-memory conversations dictionary.
    """
    ensure_conversations_dir()
    payload = build_store_payload(conversations)
    with SAVE_CONVERSATION_LOCK:
        with CHAT_STORE_PATH.open("w", encoding="utf-8") as fp:
            json.dump(payload, fp, ensure_ascii=False, indent=2)


def save_conversation_to_disk(conversation: dict, conversations: dict[str, dict]) -> None:
    """Persist one updated conversation by writing the full non-incognito store.

    Args:
        conversation: Updated conversation payload.
        conversations: Full conversations mapping from session state.
    """
    if bool((conversation or {}).get("is_incognito", False)):
        return

    if not isinstance(conversations, dict):
        return

    non_incognito = {
        conv_id: conv
        for conv_id, conv in conversations.items()
        if isinstance(conv, dict) and not bool(conv.get("is_incognito", False))
    }
    save_conversations_to_disk(non_incognito)


def delete_conversation_from_disk(conv_id: str) -> None:
    """Delete one persisted conversation from disk store.

    Args:
        conv_id: Conversation id to delete.
    """
    if not conv_id:
        return

    ensure_conversations_dir()
    if not CHAT_STORE_PATH.exists():
        return

    with SAVE_CONVERSATION_LOCK:
        try:
            with CHAT_STORE_PATH.open("r", encoding="utf-8") as fp:
                payload = json.load(fp)
        except Exception:
            return

        if not isinstance(payload, dict):
            return

        if isinstance(payload.get("chats"), dict):
            payload["chats"].pop(conv_id, None)
        else:
            payload.pop(conv_id, None)

        with CHAT_STORE_PATH.open("w", encoding="utf-8") as fp:
            json.dump(payload, fp, ensure_ascii=False, indent=2)


def load_conversations_from_disk() -> dict:
    """Load conversations from disk and normalize schema variants.

    Returns:
        dict: Conversations indexed by id.
    """
    ensure_conversations_dir()
    if not CHAT_STORE_PATH.exists():
        return {}

    try:
        with CHAT_STORE_PATH.open("r", encoding="utf-8") as fp:
            payload = json.load(fp)
    except Exception:
        return {}

    if not isinstance(payload, dict):
        return {}

    raw_chats: dict[str, object] = {}
    if isinstance(payload.get("chats"), dict):
        raw_chats = payload.get("chats", {})
    elif isinstance(payload.get("chats"), list):
        for item in payload.get("chats", []):
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id", "")).strip()
            if item_id:
                raw_chats[item_id] = item
    else:
        raw_chats = payload

    loaded: dict[str, dict] = {}
    for conv_id, chat_payload in raw_chats.items():
        if not isinstance(chat_payload, dict):
            continue
        merged_payload = dict(chat_payload)
        merged_payload.setdefault("id", str(conv_id))
        normalized = normalize_loaded_conversation(merged_payload)
        if normalized is None:
            continue
        loaded[normalized["id"]] = normalized

    return loaded


def load_custom_models() -> dict:
    """Load custom model mappings from disk.

    Returns:
        dict: Display name -> model id mapping.
    """
    ensure_conversations_dir()
    if not MODELS_STORE_PATH.exists():
        return {}

    try:
        with MODELS_STORE_PATH.open("r", encoding="utf-8") as fp:
            payload = json.load(fp)
    except Exception:
        return {}

    if not isinstance(payload, dict):
        return {}

    cleaned: dict[str, str] = {}
    for display_name, model_id in payload.items():
        name = str(display_name or "").strip()
        value = str(model_id or "").strip()
        if not name or not value:
            continue
        cleaned[name] = value

    return dict(sorted(cleaned.items(), key=lambda item: item[0].casefold()))


def save_custom_models(models_dict: dict) -> None:
    """Persist custom model mappings to disk.

    Args:
        models_dict: Display name -> model id mapping.
    """
    normalized: dict[str, str] = {}
    for display_name, model_id in (models_dict or {}).items():
        name = str(display_name or "").strip()
        value = str(model_id or "").strip()
        if not name or not value:
            continue
        normalized[name] = value

    ordered = dict(sorted(normalized.items(), key=lambda item: item[0].casefold()))
    ensure_conversations_dir()
    with SAVE_MODELS_LOCK:
        with MODELS_STORE_PATH.open("w", encoding="utf-8") as fp:
            json.dump(ordered, fp, ensure_ascii=False, indent=2)
