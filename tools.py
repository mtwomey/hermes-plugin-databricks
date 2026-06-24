"""
tools.py — Tool handler functions for the databricks plugin.

Rules:
- Every handler signature: def databricks_verb(args: dict, **kwargs) -> str
- Every handler returns json.dumps({...}) — never a raw dict or None
- Every handler has a try/except that returns {"error": "..."} on failure
- Credentials are loaded LAZILY on first call via _get_state() — NOT at import time
- OAuth2 token is cached in-process and refreshed 100s before expiry (3600s lifetime)
"""

import json
import logging
import os
import time

import requests
from hermes_plugin_core.keychain import cred_get

log = logging.getLogger("databricks")

# ── Lazy credential / token singleton ─────────────────────────────────────────

_state: dict = {}   # keys: host, client_id, client_secret, warehouse_id, token, token_expires_at


def _get_state() -> dict:
    """Load credentials from keychain on first call; return cached dict thereafter."""
    if not _state:
        try:
            SERVICE = "hermes-databricks"
            ENV_MAP = {
                "host":           "DATABRICKS_HOST",
                "client_id":      "DATABRICKS_CLIENT_ID",
                "client_secret":  "DATABRICKS_CLIENT_SECRET",
                "warehouse_id":   "DATABRICKS_WAREHOUSE_ID",
            }
            for key, env_var in ENV_MAP.items():
                val = cred_get(SERVICE, key) or os.environ.get(env_var)
                if not val:
                    raise RuntimeError(
                        f"Credential not found: service='{SERVICE}' key='{key}' "
                        f"(also checked env var '{env_var}')\n"
                        f"Run `python setup.py install` to store credentials."
                    )
                _state[key] = val

            # Strip trailing slash from host
            _state["host"] = _state["host"].rstrip("/")
            _state["token"] = None
            _state["token_expires_at"] = 0

        except Exception as e:
            raise RuntimeError(
                f"Databricks credentials not found. "
                f"Run `python setup.py install` in the plugin directory to store credentials. ({e})"
            )
    return _state


def _get_token() -> str:
    """Return a valid OAuth2 token, refreshing if within 100s of expiry."""
    state = _get_state()
    if state["token"] and time.time() < state["token_expires_at"]:
        return state["token"]

    log.debug("Fetching OAuth2 token for host=%s", state["host"])
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
    log.debug("Token obtained, expires_in=%s", data.get("expires_in", 3600))
    return state["token"]


def _headers() -> dict:
    return {"Authorization": f"Bearer {_get_token()}", "Content-Type": "application/json"}


def _run_sql(sql: str, timeout_s: int = 120):
    """Submit SQL to Statement API, poll until done.

    Returns (columns, data_array) on success.
    Raises RuntimeError on failure, TimeoutError on timeout.

    Notes:
    - Uses wait_timeout=0s + polling so the warehouse auto-starts transparently.
    - data_array values are all strings even for numeric/timestamp columns.
    - data_array may be None on SUCCEEDED with 0 rows — always use `or []`.
    """
    state = _get_state()
    log.debug("Submitting SQL: %s", sql[:200])
    resp = requests.post(
        f"{state['host']}/api/2.0/sql/statements",
        headers=_headers(),
        json={
            "statement": sql,
            "warehouse_id": state["warehouse_id"],
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
            headers=_headers(),
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

def databricks_ping(args: dict, **kwargs) -> str:
    """Test Databricks connectivity and authentication."""
    try:
        state = _get_state()
        cols, rows = _run_sql("SELECT current_user() AS user")
        user = rows[0][0] if rows else "unknown"
        log.info("ping ok: user=%s host=%s", user, state["host"])
        return json.dumps({"status": "ok", "user": user, "host": state["host"]})
    except Exception as e:
        log.error("ping failed: %s", e)
        return json.dumps({"error": str(e)})


def databricks_list_catalogs(args: dict, **kwargs) -> str:
    """List all Unity Catalog catalogs visible to the service principal."""
    try:
        cols, rows = _run_sql(
            "SELECT catalog_name FROM system.information_schema.catalogs ORDER BY catalog_name"
        )
        catalogs = [row[0] for row in rows]
        log.info("list_catalogs: found %d catalogs", len(catalogs))
        return json.dumps(catalogs)
    except Exception as e:
        log.error("list_catalogs failed: %s", e)
        return json.dumps({"error": str(e)})


def databricks_list_schemas(args: dict, **kwargs) -> str:
    """List all schemas in a Databricks catalog (excluding information_schema)."""
    try:
        catalog = args.get("catalog", "").strip()
        if not catalog:
            return json.dumps({"error": "catalog is required"})
        sql = (
            f"SELECT schema_name FROM {catalog}.information_schema.schemata "
            f"WHERE schema_name != 'information_schema' ORDER BY schema_name"
        )
        cols, rows = _run_sql(sql)
        schemas = [row[0] for row in rows]
        log.info("list_schemas: catalog=%s found %d schemas", catalog, len(schemas))
        return json.dumps(schemas)
    except Exception as e:
        log.error("list_schemas failed: catalog=%s error=%s", args.get("catalog"), e)
        return json.dumps({"error": str(e)})


def databricks_list_tables(args: dict, **kwargs) -> str:
    """List all tables in a catalog.schema."""
    try:
        catalog = args.get("catalog", "").strip()
        schema = args.get("schema", "").strip()
        if not catalog or not schema:
            return json.dumps({"error": "catalog and schema are required"})
        sql = (
            f"SELECT table_name, table_type FROM {catalog}.information_schema.tables "
            f"WHERE table_schema = '{schema}' ORDER BY table_name"
        )
        cols, rows = _run_sql(sql)
        tables = [{"name": row[0], "type": row[1]} for row in rows]
        log.info("list_tables: %s.%s found %d tables", catalog, schema, len(tables))
        return json.dumps(tables)
    except Exception as e:
        log.error("list_tables failed: catalog=%s schema=%s error=%s",
                  args.get("catalog"), args.get("schema"), e)
        return json.dumps({"error": str(e)})


def databricks_get_schema(args: dict, **kwargs) -> str:
    """Get the column schema for a fully-qualified Databricks table (catalog.schema.table)."""
    try:
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
        cols, rows = _run_sql(sql)
        columns = [{"name": row[0], "type": row[1], "position": int(row[2])} for row in rows]
        log.info("get_schema: %s returned %d columns", table, len(columns))
        return json.dumps(columns)
    except Exception as e:
        log.error("get_schema failed: table=%s error=%s", args.get("table"), e)
        return json.dumps({"error": str(e)})


def databricks_run_sql(args: dict, **kwargs) -> str:
    """Execute a SQL query on Databricks. Warehouse auto-starts if stopped."""
    try:
        sql = args.get("sql", "").strip()
        if not sql:
            return json.dumps({"error": "sql is required"})
        max_rows = int(args.get("max_rows", 100))
        columns, rows = _run_sql(sql)
        trimmed = rows[:max_rows]
        log.info("run_sql: returned %d rows (max_rows=%d)", len(trimmed), max_rows)
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
        state = _get_state()
        resp = requests.get(
            f"{state['host']}/api/2.0/sql/warehouses",
            headers=_headers(),
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
        log.info("list_warehouses: found %d warehouses", len(result))
        return json.dumps(result)
    except Exception as e:
        log.error("list_warehouses failed: %s", e)
        return json.dumps({"error": str(e)})
