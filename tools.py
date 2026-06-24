"""
tools.py — Tool handler functions for the databricks plugin.

Rules:
- Every handler signature: def databricks_verb(args: dict, **kwargs) -> str
- Every handler returns json.dumps({...}) — never a raw dict or None
- Every handler has a try/except that returns {"error": "..."} on failure
- Credentials are loaded LAZILY per workspace on first call — NOT at import time
- OAuth2 token is cached per workspace; refreshed 100s before expiry (3600s lifetime)
"""

import json
import logging
import time

import requests
from hermes_plugin_core.keychain import cred_get

log = logging.getLogger("databricks")

# ── Per-workspace lazy credential / token store ────────────────────────────────

_workspace_states: dict = {}  # workspace_name -> state dict

PLUGIN_SERVICE = "hermes-databricks"
WORKSPACE_KEYS = ["host", "client_id", "client_secret", "warehouse_id"]


def _get_default_workspace() -> str:
    """Return the configured default workspace name, or raise RuntimeError."""
    name = (cred_get(PLUGIN_SERVICE, "default_workspace") or "").strip()
    if not name:
        raise RuntimeError(
            "No default workspace configured. "
            "Run: python setup.py workspace add <name>  (then set it as default)"
        )
    return name


def _get_workspace_state(ws_name: str) -> dict:
    """Load credentials for ws_name from keychain on first call; return cached dict thereafter."""
    if ws_name not in _workspace_states:
        svc = f"hermes-databricks-{ws_name}"
        state: dict = {}
        for key in WORKSPACE_KEYS:
            val = cred_get(svc, key)
            if not val:
                raise RuntimeError(
                    f"Workspace '{ws_name}' credential '{key}' not found. "
                    f"Run: python setup.py workspace add {ws_name}"
                )
            state[key] = val
        state["host"] = state["host"].rstrip("/")
        state["token"] = None
        state["token_expires_at"] = 0
        _workspace_states[ws_name] = state
    return _workspace_states[ws_name]


def _get_token(ws_name: str) -> str:
    """Return a valid OAuth2 token for ws_name, refreshing if within 100s of expiry."""
    state = _get_workspace_state(ws_name)
    if state["token"] and time.time() < state["token_expires_at"]:
        return state["token"]

    log.debug("Fetching OAuth2 token for workspace=%s host=%s", ws_name, state["host"])
    resp = requests.post(
        f"{state['host']}/oidc/v1/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "client_credentials",
            "client_id": state["client_id"],
            "client_secret": state["client_secret"],
            "scope": "all-apis",
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    state["token"] = data["access_token"]
    state["token_expires_at"] = time.time() + data.get("expires_in", 3600) - 100
    log.debug("Token obtained for workspace=%s expires_in=%s", ws_name, data.get("expires_in", 3600))
    return state["token"]


def _headers(ws_name: str) -> dict:
    return {"Authorization": f"Bearer {_get_token(ws_name)}", "Content-Type": "application/json"}


def _resolve_workspace(args: dict) -> str:
    """Return the workspace name from args['workspace'], falling back to the configured default."""
    return (args.get("workspace") or "").strip() or _get_default_workspace()


def _run_sql(sql: str, ws_name: str, warehouse_id: str = None, timeout_s: int = 120):
    """Submit SQL to Statement API, poll until done.

    Returns (columns, data_array) on success.
    Raises RuntimeError on failure, TimeoutError on timeout.

    Notes:
    - Uses wait_timeout=0s + polling so the warehouse auto-starts transparently.
    - data_array values are all strings even for numeric/timestamp columns.
    - data_array may be None on SUCCEEDED with 0 rows — always use `or []`.
    """
    state = _get_workspace_state(ws_name)
    effective_warehouse = warehouse_id or state["warehouse_id"]
    log.debug("Submitting SQL to workspace=%s warehouse=%s: %s", ws_name, effective_warehouse, sql[:200])
    resp = requests.post(
        f"{state['host']}/api/2.0/sql/statements",
        headers=_headers(ws_name),
        json={
            "statement": sql,
            "warehouse_id": effective_warehouse,
            "wait_timeout": "0s",
            "on_wait_timeout": "CONTINUE",
        },
        timeout=30,
    )
    resp.raise_for_status()
    sid = resp.json()["statement_id"]
    log.debug("Statement ID: %s", sid)

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(3)
        r = requests.get(
            f"{state['host']}/api/2.0/sql/statements/{sid}",
            headers=_headers(ws_name),
            timeout=30,
        ).json()
        state_val = r["status"]["state"]
        log.debug("Statement %s state=%s", sid, state_val)
        if state_val == "SUCCEEDED":
            cols = [c["name"] for c in r["manifest"]["schema"]["columns"]]
            rows = r["result"]["data_array"] or []
            return cols, rows
        elif state_val in ("FAILED", "CANCELED", "CLOSED"):
            err = r["status"].get("error", {}).get("message", state_val)
            raise RuntimeError(err)

    raise TimeoutError(f"SQL timed out after {timeout_s}s (statement_id={sid})")


# ── Tool handlers ──────────────────────────────────────────────────────────────

def databricks_list_workspaces(args: dict, **kwargs) -> str:
    """List all configured Databricks workspaces."""
    try:
        raw = cred_get(PLUGIN_SERVICE, "workspaces") or ""
        names = [n for n in raw.split(",") if n]
        default = (cred_get(PLUGIN_SERVICE, "default_workspace") or "").strip()
        if not names:
            return json.dumps({
                "workspaces": [],
                "default": None,
                "message": "No workspaces configured. Run: python setup.py workspace add <name>",
            })
        result = []
        for name in names:
            svc = f"hermes-databricks-{name}"
            result.append({
                "name": name,
                "host": cred_get(svc, "host") or "(missing)",
                "warehouse_id": cred_get(svc, "warehouse_id") or "(missing)",
                "is_default": name == default,
            })
        log.info("list_workspaces: found %d workspaces, default=%s", len(result), default)
        return json.dumps({"workspaces": result, "default": default or None})
    except Exception as e:
        log.error("list_workspaces failed: %s", e)
        return json.dumps({"error": str(e)})


def databricks_ping(args: dict, **kwargs) -> str:
    """Test Databricks connectivity and authentication."""
    try:
        ws = _resolve_workspace(args)
        state = _get_workspace_state(ws)
        cols, rows = _run_sql("SELECT current_user() AS user", ws)
        user = rows[0][0] if rows else "unknown"
        log.info("ping ok: workspace=%s user=%s host=%s", ws, user, state["host"])
        return json.dumps({"status": "ok", "user": user, "host": state["host"], "workspace": ws})
    except Exception as e:
        log.error("ping failed: %s", e)
        return json.dumps({"error": str(e)})


def databricks_list_catalogs(args: dict, **kwargs) -> str:
    """List all Unity Catalog catalogs visible to the service principal."""
    try:
        ws = _resolve_workspace(args)
        cols, rows = _run_sql(
            "SELECT catalog_name FROM system.information_schema.catalogs ORDER BY catalog_name",
            ws,
        )
        catalogs = [row[0] for row in rows]
        log.info("list_catalogs: workspace=%s found %d catalogs", ws, len(catalogs))
        return json.dumps(catalogs)
    except Exception as e:
        log.error("list_catalogs failed: %s", e)
        return json.dumps({"error": str(e)})


def databricks_list_schemas(args: dict, **kwargs) -> str:
    """List all schemas in a Databricks catalog (excluding information_schema)."""
    try:
        ws = _resolve_workspace(args)
        catalog = args.get("catalog", "").strip()
        if not catalog:
            return json.dumps({"error": "catalog is required"})
        sql = (
            f"SELECT schema_name FROM {catalog}.information_schema.schemata "
            f"WHERE schema_name != 'information_schema' ORDER BY schema_name"
        )
        cols, rows = _run_sql(sql, ws)
        schemas = [row[0] for row in rows]
        log.info("list_schemas: workspace=%s catalog=%s found %d schemas", ws, catalog, len(schemas))
        return json.dumps(schemas)
    except Exception as e:
        log.error("list_schemas failed: catalog=%s error=%s", args.get("catalog"), e)
        return json.dumps({"error": str(e)})


def databricks_list_tables(args: dict, **kwargs) -> str:
    """List all tables in a catalog.schema."""
    try:
        ws = _resolve_workspace(args)
        catalog = args.get("catalog", "").strip()
        schema = args.get("schema", "").strip()
        if not catalog or not schema:
            return json.dumps({"error": "catalog and schema are required"})
        sql = (
            f"SELECT table_name, table_type FROM {catalog}.information_schema.tables "
            f"WHERE table_schema = '{schema}' ORDER BY table_name"
        )
        cols, rows = _run_sql(sql, ws)
        tables = [{"name": row[0], "type": row[1]} for row in rows]
        log.info("list_tables: workspace=%s %s.%s found %d tables", ws, catalog, schema, len(tables))
        return json.dumps(tables)
    except Exception as e:
        log.error("list_tables failed: catalog=%s schema=%s error=%s",
                  args.get("catalog"), args.get("schema"), e)
        return json.dumps({"error": str(e)})


def databricks_get_schema(args: dict, **kwargs) -> str:
    """Get the column schema for a fully-qualified Databricks table (catalog.schema.table)."""
    try:
        ws = _resolve_workspace(args)
        table = args.get("table", "").strip()
        parts = table.split(".")
        if len(parts) != 3:
            return json.dumps({"error": f"Expected catalog.schema.table, got: {table!r}"})
        catalog, schema, table_name = parts
        sql = (
            f"SELECT column_name, data_type, ordinal_position "
            f"FROM {catalog}.information_schema.columns "
            f"WHERE table_schema = '{schema}' AND table_name = '{table_name}' "
            f"ORDER BY ordinal_position"
        )
        cols, rows = _run_sql(sql, ws)
        columns = [{"name": row[0], "type": row[1], "position": int(row[2])} for row in rows]
        log.info("get_schema: workspace=%s %s returned %d columns", ws, table, len(columns))
        return json.dumps(columns)
    except Exception as e:
        log.error("get_schema failed: table=%s error=%s", args.get("table"), e)
        return json.dumps({"error": str(e)})


def databricks_run_sql(args: dict, **kwargs) -> str:
    """Execute a SQL query on Databricks. Warehouse auto-starts if stopped."""
    try:
        ws = _resolve_workspace(args)
        sql = args.get("sql", "").strip()
        if not sql:
            return json.dumps({"error": "sql is required"})
        max_rows = int(args.get("max_rows", 100))
        warehouse_id = (args.get("warehouse_id") or "").strip() or None
        columns, rows = _run_sql(sql, ws, warehouse_id=warehouse_id)
        trimmed = rows[:max_rows]
        log.info("run_sql: workspace=%s returned %d rows (max_rows=%d)", ws, len(trimmed), max_rows)
        return json.dumps({
            "columns": columns,
            "rows": trimmed,
            "row_count": len(trimmed),
        })
    except Exception as e:
        log.error("run_sql failed: %s", e)
        return json.dumps({"error": str(e)})


def databricks_list_warehouses(args: dict, **kwargs) -> str:
    """List all SQL warehouses in the workspace."""
    try:
        ws = _resolve_workspace(args)
        state = _get_workspace_state(ws)
        resp = requests.get(
            f"{state['host']}/api/2.0/sql/warehouses",
            headers=_headers(ws),
            timeout=30,
        )
        resp.raise_for_status()
        warehouses = resp.json().get("warehouses", [])
        result = [
            {
                "id": w.get("id"),
                "name": w.get("name"),
                "size": w.get("cluster_size") or w.get("size"),
                "state": w.get("state"),
            }
            for w in warehouses
        ]
        log.info("list_warehouses: workspace=%s found %d warehouses", ws, len(result))
        return json.dumps(result)
    except Exception as e:
        log.error("list_warehouses failed: %s", e)
        return json.dumps({"error": str(e)})
