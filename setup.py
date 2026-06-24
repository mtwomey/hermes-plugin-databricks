#!/usr/bin/env python3
"""
setup.py for hermes-plugin-databricks.

Usage:
    python setup.py install                        # install plugin into Hermes
    python setup.py uninstall                      # remove plugin from Hermes
    python setup.py status                         # show installation status
    python setup.py log                            # manage log level
    python setup.py audit                          # check compliance
    python setup.py test                           # run smoke tests

    python setup.py workspace list                 # list configured workspaces
    python setup.py workspace add <name>           # add a new workspace
    python setup.py workspace remove <name>        # remove a workspace
    python setup.py workspace update <name>        # update workspace credentials
    python setup.py workspace set-default <name>   # set the default workspace
"""
import re
import sys
from pathlib import Path

from hermes_plugin_core.keychain import cred_get, cred_set, cred_delete
from hermes_plugin_core.setup_cli import SetupCLI, PluginConfig

PLUGIN_SERVICE = "hermes-databricks"
WORKSPACE_KEYS = ["host", "client_id", "client_secret", "warehouse_id"]
WORKSPACE_KEY_LABELS = {
    "host":          ("Workspace URL (e.g. https://dbc-xxx.cloud.databricks.com)", False),
    "client_id":     ("Service Principal Client ID", False),
    "client_secret": ("Client Secret", True),
    "warehouse_id":  ("SQL Warehouse ID (e.g. ed4e7a4296f9661b)", False),
}
NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _workspace_service(name: str) -> str:
    return f"hermes-databricks-{name}"


def _get_manifest() -> list:
    raw = cred_get(PLUGIN_SERVICE, "workspaces") or ""
    return [n for n in raw.split(",") if n]


def _save_manifest(names: list) -> None:
    cred_set(PLUGIN_SERVICE, "workspaces", ",".join(names))


def _prompt(label: str, is_secret: bool, current: str = "") -> str:
    import getpass
    hint = " (leave blank to keep current)" if current else ""
    if is_secret:
        val = getpass.getpass(f"  {label}{hint}: ")
    else:
        display = f" [{current}]" if current else ""
        val = input(f"  {label}{display}{hint}: ").strip()
    return val or current


def cmd_workspace(args: list) -> None:
    if not args:
        print("Usage: python setup.py workspace <list|add|remove|update|set-default> [name]")
        sys.exit(1)

    subcmd = args[0]
    name = args[1] if len(args) > 1 else None

    # ── list ──────────────────────────────────────────────────────────────────
    if subcmd == "list":
        manifest = _get_manifest()
        default = cred_get(PLUGIN_SERVICE, "default_workspace") or "(none)"
        if not manifest:
            print("No workspaces configured. Run: python setup.py workspace add <name>")
            return
        print(f"Configured workspaces (default: {default}):")
        for n in manifest:
            marker = " *" if n == default else ""
            host = cred_get(_workspace_service(n), "host") or "(missing)"
            wh   = cred_get(_workspace_service(n), "warehouse_id") or "(missing)"
            print(f"  {n}{marker}  host={host}  warehouse={wh}")

    # ── add ───────────────────────────────────────────────────────────────────
    elif subcmd == "add":
        if not name:
            print("Usage: python setup.py workspace add <name>")
            sys.exit(1)
        if not NAME_RE.match(name):
            print(f"Invalid workspace name '{name}'. Use alphanumeric, hyphens, underscores only.")
            sys.exit(1)
        manifest = _get_manifest()
        if name in manifest:
            print(f"Workspace '{name}' already exists. Use 'update' to change it.")
            sys.exit(1)

        print(f"Adding workspace '{name}':")
        vals = {}
        for key in WORKSPACE_KEYS:
            label, is_secret = WORKSPACE_KEY_LABELS[key]
            vals[key] = _prompt(label, is_secret)
            if not vals[key]:
                print(f"  Error: {key} is required.")
                sys.exit(1)

        svc = _workspace_service(name)
        for key, val in vals.items():
            cred_set(svc, key, val)

        manifest.append(name)
        _save_manifest(manifest)
        print(f"  Workspace '{name}' saved.")

        set_default = input("  Set as default workspace? [y/N]: ").strip().lower()
        if set_default == "y":
            cred_set(PLUGIN_SERVICE, "default_workspace", name)
            print(f"  '{name}' is now the default workspace.")

        if not cred_get(PLUGIN_SERVICE, "default_workspace"):
            cred_set(PLUGIN_SERVICE, "default_workspace", name)
            print(f"  No default was set — '{name}' auto-set as default.")

    # ── remove ────────────────────────────────────────────────────────────────
    elif subcmd == "remove":
        if not name:
            print("Usage: python setup.py workspace remove <name>")
            sys.exit(1)
        manifest = _get_manifest()
        if name not in manifest:
            print(f"Workspace '{name}' not found.")
            sys.exit(1)
        confirm = input(f"Remove workspace '{name}'? This deletes its keychain credentials. [y/N]: ")
        if confirm.strip().lower() != "y":
            print("Aborted.")
            return
        svc = _workspace_service(name)
        for key in WORKSPACE_KEYS:
            try:
                cred_delete(svc, key)
            except Exception:
                pass
        manifest.remove(name)
        _save_manifest(manifest)

        default = cred_get(PLUGIN_SERVICE, "default_workspace")
        if default == name:
            try:
                cred_delete(PLUGIN_SERVICE, "default_workspace")
            except Exception:
                pass
            print(f"  Warning: '{name}' was the default workspace. Run 'set-default' to choose a new one.")
        print(f"  Workspace '{name}' removed.")

    # ── update ────────────────────────────────────────────────────────────────
    elif subcmd == "update":
        if not name:
            print("Usage: python setup.py workspace update <name>")
            sys.exit(1)
        manifest = _get_manifest()
        if name not in manifest:
            print(f"Workspace '{name}' not found.")
            sys.exit(1)
        svc = _workspace_service(name)
        print(f"Updating workspace '{name}' (leave blank to keep current value):")
        for key in WORKSPACE_KEYS:
            label, is_secret = WORKSPACE_KEY_LABELS[key]
            current = "" if is_secret else (cred_get(svc, key) or "")
            new_val = _prompt(label, is_secret, current)
            if new_val:
                cred_set(svc, key, new_val)
        print(f"  Workspace '{name}' updated.")

    # ── set-default ────────────────────────────────────────────────────────────
    elif subcmd == "set-default":
        if not name:
            print("Usage: python setup.py workspace set-default <name>")
            sys.exit(1)
        manifest = _get_manifest()
        if name not in manifest:
            print(f"Workspace '{name}' not found. Add it first.")
            sys.exit(1)
        cred_set(PLUGIN_SERVICE, "default_workspace", name)
        print(f"  Default workspace set to '{name}'.")

    else:
        print(f"Unknown subcommand '{subcmd}'. Use: list, add, remove, update, set-default")
        sys.exit(1)


config = PluginConfig(
    plugin_key="databricks",
    service=PLUGIN_SERVICE,
    repo_dir=Path(__file__).parent.resolve(),
    keys=[],           # workspace creds managed by cmd_workspace, not SetupCLI
    cred_prompts={},
    requirements=[],
    has_skill_stub=True,
    skill_stub_category="data-science",
)


class DatabricksSetupCLI(SetupCLI):
    def _register_extra_subparsers(self, sub) -> None:
        wp = sub.add_parser("workspace", help="Manage workspaces (list, add, remove, update, set-default)")
        wp.add_argument(
            "ws_action",
            nargs="?",
            choices=["list", "add", "remove", "update", "set-default"],
            metavar="ACTION",
            help="list | add | remove | update | set-default",
        )
        wp.add_argument("name", nargs="?", help="Workspace name")

    def _dispatch_extra(self, command: str, args, parser) -> bool:
        if command == "workspace":
            ws_args = []
            if getattr(args, "ws_action", None):
                ws_args.append(args.ws_action)
            if getattr(args, "name", None):
                ws_args.append(args.name)
            cmd_workspace(ws_args)
            return True
        return False


if __name__ == "__main__":
    DatabricksSetupCLI(config).run()
