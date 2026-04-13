"""Encrypted secrets vault utilities for Zero-Trace RAG."""

from __future__ import annotations

import json
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VAULT_DIR = PROJECT_ROOT / ".secrets"
VAULT_KEY_PATH = VAULT_DIR / "vault.key"
VAULT_DATA_PATH = VAULT_DIR / "secrets.enc"


def ensure_vault_dir() -> Path:
    """Ensure the encrypted vault directory exists.

    Returns:
        Path: The vault directory path.
    """
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    return VAULT_DIR


class SecretsVault:
    """Manage encrypted secret storage using Fernet symmetric encryption."""

    def __init__(self, key_path: Path = VAULT_KEY_PATH, data_path: Path = VAULT_DATA_PATH) -> None:
        """Initialize a secrets vault.

        Args:
            key_path: Path to the Fernet key file.
            data_path: Path to the encrypted data payload.
        """
        self.key_path = key_path
        self.data_path = data_path

    def get_or_create_key(self) -> bytes:
        """Load the current key or create a new one if missing.

        Returns:
            bytes: The Fernet key bytes.
        """
        ensure_vault_dir()
        if self.key_path.exists():
            key_data = self.key_path.read_bytes()
            if key_data:
                return key_data

        key_data = Fernet.generate_key()
        self.key_path.write_bytes(key_data)
        return key_data

    def load_secrets(self) -> dict:
        """Load and decrypt secrets from disk.

        Returns:
            dict: Decrypted secrets dictionary, or an empty dict on failure.
        """
        ensure_vault_dir()
        fernet = Fernet(self.get_or_create_key())
        if not self.data_path.exists():
            return {}

        try:
            encrypted_payload = self.data_path.read_bytes()
            decrypted_payload = fernet.decrypt(encrypted_payload)
            parsed = json.loads(decrypted_payload.decode("utf-8"))
            return parsed if isinstance(parsed, dict) else {}
        except (InvalidToken, OSError, ValueError, json.JSONDecodeError):
            return {}

    def save_secrets(self, data: dict) -> None:
        """Encrypt and persist secrets to disk.

        Args:
            data: Secrets payload to store.
        """
        ensure_vault_dir()
        payload = data if isinstance(data, dict) else {}
        encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        fernet = Fernet(self.get_or_create_key())
        encrypted_payload = fernet.encrypt(encoded)
        self.data_path.write_bytes(encrypted_payload)


def get_secret(secret_name: str) -> str:
    """Read a single secret value by key name.

    Args:
        secret_name: Secret key name.

    Returns:
        str: Secret value or an empty string when unset.
    """
    payload = SecretsVault().load_secrets()
    if not isinstance(payload, dict):
        return ""
    return str(payload.get(secret_name, "") or "").strip()
