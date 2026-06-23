"""
Hermes plugin entry point for the databricks plugin.

Hermes calls register(ctx) once at startup. Keep this file thin —
all logic lives in tools.py and schemas.py.
"""

import logging
import os
import sys
from pathlib import Path

from . import schemas, tools

_SKILL_MD = Path(__file__).parent / "SKILL.md"
_PLUGIN_DIR = Path(__file__).parent


def _get_log_level() -> str:
    """
    Read plugins.config.databricks.log_level from config.yaml.
    Falls back to WARNING on any error (missing key, missing file, parse error).

    Set via: ./setup.sh log debug|quiet
    Applied at Hermes startup — requires restart to take effect.
    """
    try:
        from ruamel.yaml import YAML
        hermes_home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
        config_yaml = hermes_home / "config.yaml"
        if not config_yaml.exists():
            return "WARNING"
        yaml = YAML()
        with open(config_yaml) as f:
            data = yaml.load(f) or {}
        plugins = data.get("plugins") or {}
        config  = plugins.get("config") or {}
        plugin  = config.get("databricks") or {}
        return str(plugin.get("log_level") or "WARNING").upper()
    except Exception:
        return "WARNING"


def register(ctx) -> None:
    """Register all databricks tools and the bundled skill with the Hermes plugin context."""

    # Ensure scripts/ is on sys.path for keychain_utils / logging_utils
    _scripts = Path(__file__).parent / "scripts"
    if str(_scripts) not in sys.path:
        sys.path.insert(0, str(_scripts))

    from logging_utils import setup_logging  # noqa: E402
    setup_logging("databricks", _get_log_level())

    log = logging.getLogger("databricks")
    log.debug("Registering databricks plugin tools")

    # ------------------------------------------------------------------
    # IMPORTANT: ctx.register_tool() requires BOTH name= and toolset=
    # Omitting either causes a silent failure — plugin appears enabled
    # but registers ZERO tools.
    # ------------------------------------------------------------------
    _REGISTRY = [
        (schemas.PING,             tools.databricks_ping),
        (schemas.LIST_CATALOGS,    tools.databricks_list_catalogs),
        (schemas.LIST_SCHEMAS,     tools.databricks_list_schemas),
        (schemas.LIST_TABLES,      tools.databricks_list_tables),
        (schemas.GET_SCHEMA,       tools.databricks_get_schema),
        (schemas.RUN_SQL,          tools.databricks_run_sql),
        (schemas.LIST_WAREHOUSES,  tools.databricks_list_warehouses),
    ]

    for schema, handler in _REGISTRY:
        ctx.register_tool(
            name=schema["name"],      # ← REQUIRED — do not omit
            toolset="databricks",     # ← REQUIRED — do not omit
            schema=schema,
            handler=handler,
        )

    log.debug("Registered %d databricks tools", len(_REGISTRY))

    # Register the bundled skill so agents can load it via
    # skill_view(name="databricks:databricks")
    # No ~/.hermes/skills/ symlink needed.
    if _SKILL_MD.exists():
        ctx.register_skill("databricks", _SKILL_MD)
        log.debug("Registered bundled SKILL.md")
