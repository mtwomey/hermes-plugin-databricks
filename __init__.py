"""
Hermes plugin entry point for the databricks plugin.

Hermes calls register(ctx) once at startup. Keep this file thin —
all logic lives in tools.py and schemas.py.
"""
from pathlib import Path
from hermes_plugin_core import setup_logging
from hermes_plugin_core.config import get_log_level
from . import schemas, tools

_SKILL_MD = Path(__file__).parent / "SKILL.md"


def register(ctx) -> None:
    """Register all databricks tools and the bundled skill."""
    setup_logging("databricks", get_log_level("databricks"))

    _REGISTRY = [
        (schemas.LIST_WORKSPACES,  tools.databricks_list_workspaces),
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
            name=schema["name"],
            toolset="databricks",
            schema=schema,
            handler=handler,
        )

    if _SKILL_MD.exists():
        ctx.register_skill("databricks", _SKILL_MD)
