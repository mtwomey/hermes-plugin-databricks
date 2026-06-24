"""
schemas.py — Tool schemas for the databricks plugin.

Defines what the LLM sees for each databricks_* tool.
Names must EXACTLY match handler function names in tools.py.
"""

_WORKSPACE_PARAM = {
    "workspace": {
        "type": "string",
        "description": (
            "Friendly workspace name to query (e.g. \"prod\", \"dev\"). "
            "Defaults to the configured default workspace if omitted."
        ),
    },
}

# ── List Workspaces ────────────────────────────────────────────────────────────

LIST_WORKSPACES = {
    "name": "databricks_list_workspaces",
    "description": (
        "List all configured Databricks workspaces with their host, default warehouse, "
        "and which is the current default. "
        "Returns: {\"workspaces\": [{\"name\": \"...\", \"host\": \"...\", "
        "\"warehouse_id\": \"...\", \"is_default\": bool}], \"default\": \"...\"} "
        "or {\"error\": \"...\"}."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

# ── Ping ──────────────────────────────────────────────────────────────────────

PING = {
    "name": "databricks_ping",
    "description": (
        "Test Databricks connectivity and authentication. "
        "Executes SELECT current_user() against the configured warehouse. "
        "Returns: {\"status\": \"ok\", \"user\": \"...\", \"host\": \"...\", \"workspace\": \"...\"} or {\"error\": \"...\"}."
    ),
    "parameters": {
        "type": "object",
        "properties": {**_WORKSPACE_PARAM},
        "required": [],
    },
}

# ── List Catalogs ─────────────────────────────────────────────────────────────

LIST_CATALOGS = {
    "name": "databricks_list_catalogs",
    "description": (
        "List all Unity Catalog catalogs visible to the service principal. "
        "Returns: [\"catalog_name\", ...] or {\"error\": \"...\"}."
    ),
    "parameters": {
        "type": "object",
        "properties": {**_WORKSPACE_PARAM},
        "required": [],
    },
}

# ── List Schemas ──────────────────────────────────────────────────────────────

LIST_SCHEMAS = {
    "name": "databricks_list_schemas",
    "description": (
        "List all schemas in a Databricks catalog (excluding information_schema). "
        "Returns: [\"schema_name\", ...] or {\"error\": \"...\"}."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "catalog": {
                "type": "string",
                "description": "Catalog name, e.g. \"cat_salesforce_fomod_prod01\".",
            },
            **_WORKSPACE_PARAM,
        },
        "required": ["catalog"],
    },
}

# ── List Tables ───────────────────────────────────────────────────────────────

LIST_TABLES = {
    "name": "databricks_list_tables",
    "description": (
        "List all tables in a catalog.schema. "
        "Returns: [{\"name\": \"...\", \"type\": \"...\"}, ...] or {\"error\": \"...\"}."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "catalog": {
                "type": "string",
                "description": "Catalog name, e.g. \"cat_salesforce_fomod_prod01\".",
            },
            "schema": {
                "type": "string",
                "description": "Schema name, e.g. \"silver\".",
            },
            **_WORKSPACE_PARAM,
        },
        "required": ["catalog", "schema"],
    },
}

# ── Get Schema ────────────────────────────────────────────────────────────────

GET_SCHEMA = {
    "name": "databricks_get_schema",
    "description": (
        "Get the column schema for a Databricks table. "
        "Accepts a fully-qualified three-part name: catalog.schema.table. "
        "Returns: [{\"name\": \"...\", \"type\": \"...\", \"position\": N}, ...] or {\"error\": \"...\"}."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "table": {
                "type": "string",
                "description": (
                    "Fully-qualified table name: catalog.schema.table, "
                    "e.g. \"cat_salesforce_fomod_prod01.silver.account\"."
                ),
            },
            **_WORKSPACE_PARAM,
        },
        "required": ["table"],
    },
}

# ── Run SQL ───────────────────────────────────────────────────────────────────

RUN_SQL = {
    "name": "databricks_run_sql",
    "description": (
        "Execute a SQL query on Databricks via the Statement API. "
        "The warehouse auto-starts if stopped (may add 30-90s for first query). "
        "All values in the result are strings — cast as needed. "
        "Returns: {\"columns\": [...], \"rows\": [...], \"row_count\": N} or {\"error\": \"...\"}."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": "SQL query to execute.",
            },
            "max_rows": {
                "type": "integer",
                "description": "Maximum rows to return (default 100).",
            },
            "warehouse_id": {
                "type": "string",
                "description": "Override the workspace default SQL warehouse ID for this query.",
            },
            **_WORKSPACE_PARAM,
        },
        "required": ["sql"],
    },
}

# ── List Warehouses ───────────────────────────────────────────────────────────

LIST_WAREHOUSES = {
    "name": "databricks_list_warehouses",
    "description": (
        "List all SQL warehouses in the workspace with their IDs, names, sizes, and states. "
        "Useful for finding the right warehouse_id. "
        "Returns: [{\"id\": \"...\", \"name\": \"...\", \"size\": \"...\", \"state\": \"RUNNING|STOPPED\"}] "
        "or {\"error\": \"...\"}."
    ),
    "parameters": {
        "type": "object",
        "properties": {**_WORKSPACE_PARAM},
        "required": [],
    },
}
