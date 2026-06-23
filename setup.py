"""
setup.py for the databricks Hermes plugin.

Usage:
    ./setup.sh install [--yes]   # Install (symlink, enable, store creds)
    ./setup.sh remove  [--yes]   # Uninstall (remove symlink, disable plugin)
    ./setup.sh status            # Show current install/credential state
    ./setup.sh creds  [--yes]    # Re-enter or update stored credentials
    ./setup.sh log debug         # Enable DEBUG logging (requires Hermes restart)
    ./setup.sh log quiet         # Disable debug logging (back to WARNING)
    ./setup.sh log status        # Show current log level setting
"""

import argparse
import os
import sys
from pathlib import Path

from ruamel.yaml import YAML  # preserves comments and key order
import keyring


# ── Constants ─────────────────────────────────────────────────────────────────

PLUGIN_NAME = "databricks"
KEYCHAIN_SERVICE = "hermes-databricks"

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
PLUGINS_DIR = HERMES_HOME / "plugins"
CONFIG_FILE = HERMES_HOME / "config.yaml"

REPO_DIR = Path(__file__).resolve().parent
PLUGIN_LINK = PLUGINS_DIR / PLUGIN_NAME

# Credential keys — must match keychain_utils.py usage in tools.py
KEYS = ["host", "client_id", "client_secret", "warehouse_id"]

CRED_PROMPTS = {
    "host": {
        "label": "Workspace URL (e.g. https://dbc-e0b9d669-efb7.cloud.databricks.com)",
        "default": "",
        "is_secret": False,
    },
    "client_id": {
        "label": "Service Principal Client ID",
        "default": "",
        "is_secret": False,
    },
    "client_secret": {
        "label": "Client Secret",
        "default": "",
        "is_secret": True,
    },
    "warehouse_id": {
        "label": "SQL Warehouse ID (e.g. ed4e7a4296f9661b)",
        "default": "",
        "is_secret": False,
    },
}

_KEYCHAIN_CACHE: dict[str, str | None] = {}


# ── Keychain helpers ──────────────────────────────────────────────────────────

def _keychain_store(key: str, value: str) -> None:
    keyring.set_password(KEYCHAIN_SERVICE, key, value)
    _KEYCHAIN_CACHE[key] = value


def _keychain_read(key: str) -> str | None:
    if key in _KEYCHAIN_CACHE:
        return _KEYCHAIN_CACHE[key]
    val = keyring.get_password(KEYCHAIN_SERVICE, key)
    _KEYCHAIN_CACHE[key] = val
    return val


def _keychain_delete(key: str) -> None:
    try:
        keyring.delete_password(KEYCHAIN_SERVICE, key)
    except Exception:
        pass
    _KEYCHAIN_CACHE.pop(key, None)


def _prompt_cred(key: str, existing: str | None = None) -> str:
    info = CRED_PROMPTS.get(key, {"label": key, "default": "", "is_secret": False})
    label = info["label"]
    default = existing or info.get("default", "")
    hint = f" [{default[:4]}{'...' if len(default) > 4 else ''}]" if default else ""

    if info.get("is_secret"):
        import getpass
        value = getpass.getpass(f"  {label}{hint}: ").strip()
    else:
        value = input(f"  {label}{hint}: ").strip()

    return value or default


def cred_status() -> dict[str, bool]:
    return {k: _keychain_read(k) is not None for k in KEYS}


# ── Config helpers ────────────────────────────────────────────────────────────

def _read_config():
    yaml = YAML()
    yaml.preserve_quotes = True
    with open(CONFIG_FILE) as f:
        return yaml.load(f), yaml


def _write_config(data, yaml):
    with open(CONFIG_FILE, "w") as f:
        yaml.dump(data, f)


def _is_enabled() -> bool:
    if not CONFIG_FILE.exists():
        return False
    data, _ = _read_config()
    plugins = data.get("plugins", {})
    return PLUGIN_NAME in (plugins.get("enabled") or [])


def _enable_plugin() -> None:
    data, yaml = _read_config()
    if "plugins" not in data:
        data["plugins"] = {}
    if "enabled" not in data["plugins"] or data["plugins"]["enabled"] is None:
        data["plugins"]["enabled"] = []
    if PLUGIN_NAME not in data["plugins"]["enabled"]:
        data["plugins"]["enabled"].append(PLUGIN_NAME)
        _write_config(data, yaml)
        print(f"  ✓ Added '{PLUGIN_NAME}' to plugins.enabled in config.yaml")
    else:
        print(f"  ✓ '{PLUGIN_NAME}' already in plugins.enabled")


def _disable_plugin() -> None:
    data, yaml = _read_config()
    plugins = data.get("plugins", {})
    enabled = plugins.get("enabled") or []
    if PLUGIN_NAME in enabled:
        enabled.remove(PLUGIN_NAME)
        data["plugins"]["enabled"] = enabled
        _write_config(data, yaml)
        print(f"  ✓ Removed '{PLUGIN_NAME}' from plugins.enabled")
    else:
        print(f"  ✓ '{PLUGIN_NAME}' was not in plugins.enabled")


# ── Connectivity smoke test ───────────────────────────────────────────────────

def _test_connection(host: str, client_id: str, client_secret: str, warehouse_id: str) -> None:
    """Run a quick OAuth2 + SQL smoke test after credential setup."""
    try:
        import requests as _req
    except ImportError:
        print("  ⚠️  'requests' not installed — skipping connectivity test.")
        return

    host = host.rstrip("/")
    print("\n  Testing connectivity...")

    # OAuth2 token
    try:
        r = _req.post(
            f"{host}/oidc/v1/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "all-apis",
            },
            timeout=15,
        )
        if r.status_code != 200:
            print(f"  ✗ OAuth failed (HTTP {r.status_code}): {r.text[:200]}")
            return
        token = r.json().get("access_token")
        print("  ✓ OAuth2 token obtained")
    except _req.RequestException as e:
        print(f"  ✗ Request failed: {e}")
        return

    # SQL test
    try:
        r2 = _req.post(
            f"{host}/api/2.0/sql/statements",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "statement": "SELECT current_user()",
                "warehouse_id": warehouse_id,
                "wait_timeout": "30s",
            },
            timeout=45,
        )
        if r2.status_code in (200, 201):
            state = r2.json().get("status", {}).get("state", "UNKNOWN")
            if state in ("SUCCEEDED", "RUNNING", "PENDING"):
                print(f"  ✓ SQL test passed (state={state})")
                return
        print(f"  ✗ SQL failed (HTTP {r2.status_code}): {r2.text[:200]}")
    except _req.RequestException as e:
        print(f"  ✗ Request failed: {e}")


# ── Commands ──────────────────────────────────────────────────────────────────

def _finish_install():
    print(f"\n  ✅ {PLUGIN_NAME} plugin installed.")
    print("  ➡  Restart Hermes to activate tools.\n")


def cmd_status():
    print(f"\n{'─'*52}")
    print(f" Status: {PLUGIN_NAME} plugin")
    print(f"{'─'*52}")

    link_ok = PLUGIN_LINK.is_symlink() and PLUGIN_LINK.resolve() == REPO_DIR
    enabled_ok = _is_enabled()

    print(f"  Plugin symlink : {'✓' if link_ok else '✗'} {PLUGIN_LINK}")
    print(f"  Enabled        : {'✓' if enabled_ok else '✗'} (plugins.enabled in config.yaml)")

    creds = cred_status()
    for key, stored in creds.items():
        print(f"  Cred [{key:15s}]: {'✓' if stored else '✗ NOT STORED'}")

    print()
    all_creds = all(creds.values())
    if link_ok and enabled_ok and all_creds:
        print("  ✅ Ready — restart Hermes to activate the plugin.")
    else:
        print("  ❌ Run: ./setup.sh install")
    print()


def cmd_install(yes: bool = False):
    print(f"\nInstalling {PLUGIN_NAME} plugin...")

    # 1. Create plugin symlink
    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    if PLUGIN_LINK.is_symlink():
        if PLUGIN_LINK.resolve() == REPO_DIR:
            print(f"  ✓ Symlink already correct: {PLUGIN_LINK}")
        else:
            PLUGIN_LINK.unlink()
            PLUGIN_LINK.symlink_to(REPO_DIR)
            print(f"  ✓ Symlink updated: {PLUGIN_LINK} → {REPO_DIR}")
    elif PLUGIN_LINK.exists():
        print(f"  ⚠️  {PLUGIN_LINK} exists but is not a symlink. Remove it manually.")
        sys.exit(1)
    else:
        PLUGIN_LINK.symlink_to(REPO_DIR)
        print(f"  ✓ Symlink created: {PLUGIN_LINK} → {REPO_DIR}")

    # 2. Enable plugin in config.yaml
    _enable_plugin()

    # 3. Store credentials
    existing_creds = cred_status()
    all_stored = all(existing_creds.values())

    # BUG FIX: if all creds stored + --yes, skip prompts entirely (no stdin to read from)
    if all_stored and yes:
        print("  ✓ All credentials already stored. Skipping re-entry (--yes).")
        _finish_install()
        return

    if all_stored and not yes:
        ans = input("\n  Credentials already stored. Re-enter? [y/N]: ").strip().lower()
        if ans != "y":
            print("  ✓ Using existing credentials.")
            _finish_install()
            return

    print("\n  Enter credentials (leave blank to keep existing value):\n")
    for key in KEYS:
        existing = _keychain_read(key)
        value = _prompt_cred(key, existing)
        if value:
            _keychain_store(key, value)
            print(f"  ✓ Stored: {key}")
        elif existing:
            print(f"  ✓ Kept existing: {key}")
        else:
            print(f"  ⚠️  Skipped (no value): {key}")

    # Smoke test with whatever is in keychain now
    host = _keychain_read("host") or ""
    cid  = _keychain_read("client_id") or ""
    csec = _keychain_read("client_secret") or ""
    wid  = _keychain_read("warehouse_id") or ""
    if host and cid and csec and wid:
        _test_connection(host, cid, csec, wid)

    _finish_install()


def cmd_remove(yes: bool = False):
    print(f"\nRemoving {PLUGIN_NAME} plugin...")
    if not yes:
        ans = input("  This will remove the symlink and disable the plugin. Continue? [y/N]: ").strip().lower()
        if ans != "y":
            print("  Aborted.")
            return

    if PLUGIN_LINK.is_symlink():
        PLUGIN_LINK.unlink()
        print(f"  ✓ Removed symlink: {PLUGIN_LINK}")
    else:
        print(f"  ✓ No symlink found at {PLUGIN_LINK}")

    _disable_plugin()

    ans = input("\n  Also delete stored credentials from Keychain? [y/N]: ").strip().lower()
    if ans == "y":
        for key in KEYS:
            _keychain_delete(key)
        print("  ✓ Credentials removed from Keychain.")

    print(f"\n  ✅ {PLUGIN_NAME} plugin removed. Restart Hermes to deactivate.\n")


def cmd_creds(yes: bool = False):
    print(f"\nUpdating credentials for {PLUGIN_NAME}...\n")
    for key in KEYS:
        existing = _keychain_read(key)
        value = _prompt_cred(key, existing)
        if value:
            _keychain_store(key, value)
            print(f"  ✓ Updated: {key}")
        elif existing:
            print(f"  ✓ Kept existing: {key}")
        else:
            print(f"  ⚠️  No value provided for: {key}")
    print()


# ── Log level management ──────────────────────────────────────────────────────

def cmd_log(action: str = "status"):
    if not _is_enabled():
        print(f"  ⚠️  Plugin '{PLUGIN_NAME}' is not enabled — run './setup.sh install' first")
        sys.exit(1)

    data, yaml = _read_config()

    def _get_level():
        plugins = data.get("plugins") or {}
        config  = plugins.get("config") or {}
        plugin  = config.get(PLUGIN_NAME) or {}
        return plugin.get("log_level")

    def _set_level(level_or_none):
        from ruamel.yaml import CommentedMap
        if "plugins" not in data or data["plugins"] is None:
            data["plugins"] = CommentedMap()
        if "config" not in data["plugins"] or data["plugins"]["config"] is None:
            data["plugins"]["config"] = CommentedMap()
        if PLUGIN_NAME not in data["plugins"]["config"] or data["plugins"]["config"][PLUGIN_NAME] is None:
            data["plugins"]["config"][PLUGIN_NAME] = CommentedMap()
        if level_or_none is None:
            if "log_level" in data["plugins"]["config"][PLUGIN_NAME]:
                del data["plugins"]["config"][PLUGIN_NAME]["log_level"]
        else:
            data["plugins"]["config"][PLUGIN_NAME]["log_level"] = level_or_none
        _write_config(data, yaml)

    if action == "status":
        level = _get_level() or "WARNING (default)"
        print(f"\n  Log level for plugins.config.{PLUGIN_NAME}: {level}")
        log_file = HERMES_HOME / "logs" / f"{PLUGIN_NAME}.log"
        if log_file.exists():
            print(f"  Log file: {log_file}  ({log_file.stat().st_size // 1024} KB)")
        else:
            print(f"  Log file: {log_file}  (not yet created)")
        print()
    elif action == "debug":
        _set_level("DEBUG")
        print(f"  ✓ Log level set to DEBUG. Restart Hermes to apply.")
        print(f"  ➡  tail -f {HERMES_HOME}/logs/{PLUGIN_NAME}.log")
    elif action == "quiet":
        _set_level(None)
        print(f"  ✓ Log level reset to WARNING (default). Restart Hermes to apply.")
    else:
        print(f"  Unknown log action: {action!r}. Use: debug | quiet | status")
        sys.exit(1)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(prog="setup.py", description=f"{PLUGIN_NAME} plugin setup")
    sub = parser.add_subparsers(dest="command")

    install_p = sub.add_parser("install", help="Install plugin (symlink + enable + credentials)")
    install_p.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompts")

    remove_p = sub.add_parser("remove", help="Remove plugin (unlink + disable)")
    remove_p.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompts")

    sub.add_parser("status", help="Show install and credential status")

    creds_p = sub.add_parser("creds", help="Re-enter stored credentials")
    creds_p.add_argument("--yes", "-y", action="store_true")

    log_p = sub.add_parser("log", help="Manage plugin log level")
    log_p.add_argument("log_action", nargs="?", choices=["debug", "quiet", "status"],
                       default="status")

    args = parser.parse_args()

    if args.command == "install":
        cmd_install(yes=args.yes)
    elif args.command == "remove":
        cmd_remove(yes=args.yes)
    elif args.command == "status":
        cmd_status()
    elif args.command == "creds":
        cmd_creds(yes=args.yes)
    elif args.command == "log":
        cmd_log(args.log_action)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
