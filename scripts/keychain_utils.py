"""
keychain_utils.py — Generic macOS Keychain credential helper.

Bundled copy — each plugin repo carries its own copy so it is fully self-contained.
Tool-specific credential loading should call fetch_credential() here
and should NOT duplicate this logic.

Usage:
    from keychain_utils import store_credential, fetch_credential, credential_status

Note: callers should fetch each credential once per process/invocation and cache
it in memory. Repeated Keychain reads can trigger repeated macOS approval dialogs.
"""

import os

import keyring


class CredentialError(Exception):
    """Raised when a required credential cannot be found."""
    pass


def store_credential(service: str, key: str, value: str) -> None:
    """Store a credential in macOS Keychain."""
    keyring.set_password(service, key, value)


def fetch_credential(service: str, key: str, env_fallback: str | None = None) -> str:
    """Fetch a credential from macOS Keychain with optional env var fallback."""
    val = keyring.get_password(service, key)
    if val:
        return val

    if env_fallback and os.environ.get(env_fallback):
        return os.environ[env_fallback]

    raise CredentialError(
        f"Credential not found: service='{service}' key='{key}'"
        + (f" (also checked env var '{env_fallback}')" if env_fallback else "")
        + "\nRun the plugin's setup script to store credentials: ./setup.sh install"
    )


def delete_credential(service: str, key: str) -> None:
    """Delete a credential from macOS Keychain. Silently ignores if not found."""
    try:
        keyring.delete_password(service, key)
    except Exception:
        pass


def credential_status(service: str, keys_and_env: dict) -> dict:
    """Check which credentials are present without revealing values."""
    result = {}
    for key, env_var in keys_and_env.items():
        val = keyring.get_password(service, key)
        if val:
            result[key] = "keychain"
        elif env_var and os.environ.get(env_var):
            result[key] = "env"
        else:
            result[key] = "missing"
    return result
