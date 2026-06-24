"""
Smoke tests for hermes-plugin-databricks.
Run with: python setup.py test

Covers:
- databricks_list_workspaces (no auth needed)
- databricks_ping (default workspace)
- databricks_list_warehouses (default workspace)
- databricks_list_catalogs (default workspace)
- databricks_run_sql basic query (default workspace)
- databricks_run_sql with explicit workspace param
- databricks_run_sql with explicit warehouse_id param
- databricks_ping with bad workspace name (error handling)
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from hermes_plugin_core.testing import TestSuite, expect_ok


def register_tests(suite: TestSuite):
    suite.add("list workspaces", test_list_workspaces)
    suite.add("ping (default workspace)", test_ping)
    suite.add("list warehouses (default workspace)", test_list_warehouses)
    suite.add("list catalogs (default workspace)", test_list_catalogs)
    suite.add("run sql basic", test_run_sql_basic)
    suite.add("run sql explicit workspace", test_run_sql_explicit_workspace)
    suite.add("run sql warehouse_id override", test_run_sql_warehouse_override)
    suite.add("ping bad workspace name (error handling)", test_ping_bad_workspace)


# ── helpers ───────────────────────────────────────────────────────────────────

def _is_auth_error(err: str) -> bool:
    s = str(err).lower()
    return "401" in s or "unauthorized" in s or "forbidden" in s


def _skip_if_auth(result: dict, label: str) -> bool:
    """Return True and print a warning if this looks like an auth error."""
    if "error" in result and _is_auth_error(result["error"]):
        print(f"  [auth error] in {label}: {result['error']}")
        return True
    return False


def _get_default_workspace_name() -> str:
    """Read the default workspace name from keychain."""
    from hermes_plugin_core.keychain import cred_get
    return (cred_get("hermes-databricks", "default_workspace") or "").strip()


def _get_default_workspace_auth_type() -> str:
    """Return 'oauth' or 'pat' for the default workspace."""
    from hermes_plugin_core.keychain import cred_get
    ws = _get_default_workspace_name()
    if not ws:
        return "oauth"
    return (cred_get(f"hermes-databricks-{ws}", "auth_type") or "oauth").lower()


def _get_running_warehouse_id(ws_name: str) -> str | None:
    """Return the ID of any RUNNING warehouse in ws_name, or None."""
    from tools import databricks_list_warehouses
    result = json.loads(databricks_list_warehouses({"workspace": ws_name}))
    if "error" in result:
        return None
    running = [w for w in result if w.get("state") == "RUNNING"]
    return running[0]["id"] if running else (result[0]["id"] if result else None)


# ── tests ─────────────────────────────────────────────────────────────────────

def test_list_workspaces():
    """databricks_list_workspaces: no auth required — just reads keychain manifest."""
    from tools import databricks_list_workspaces
    result = json.loads(databricks_list_workspaces({}))
    assert "error" not in result, f"list_workspaces error: {result.get('error')}"
    assert "workspaces" in result, f"missing 'workspaces' key: {result}"
    # May be empty if no workspaces configured — that's a valid state for the smoke test
    for ws in result["workspaces"]:
        assert "auth_type" in ws, f"missing auth_type on workspace {ws.get('name')}: {ws}"
    print(f"  workspaces: {[(w['name'], w['auth_type']) for w in result['workspaces']]}  default: {result.get('default')}")


def test_ping():
    """databricks_ping with no args: uses default workspace."""
    from tools import databricks_ping
    result = json.loads(databricks_ping({}))
    if _skip_if_auth(result, "ping"):
        return
    assert "error" not in result, f"ping error: {result.get('error')}"
    assert result.get("status") == "ok", f"unexpected status: {result}"
    assert "workspace" in result, f"missing 'workspace' key: {result}"
    print(f"  user={result.get('user')}  host={result.get('host')}  workspace={result.get('workspace')}")


def test_list_warehouses():
    """databricks_list_warehouses with no args: uses default workspace."""
    from tools import databricks_list_warehouses
    result = json.loads(databricks_list_warehouses({}))
    if _skip_if_auth(result, "list_warehouses"):
        return
    assert "error" not in result, f"list_warehouses error: {result.get('error')}"
    assert isinstance(result, list), f"expected list, got: {type(result)}"
    print(f"  warehouses: {[w.get('name') for w in result]}")


def test_list_catalogs():
    """databricks_list_catalogs with no args: uses default workspace."""
    from tools import databricks_list_catalogs
    result = json.loads(databricks_list_catalogs({}))
    if _skip_if_auth(result, "list_catalogs"):
        return
    assert "error" not in result, f"list_catalogs error: {result.get('error')}"
    assert isinstance(result, list), f"expected list, got: {type(result)}"
    print(f"  catalogs ({len(result)}): {result[:5]}")


def test_run_sql_basic():
    """databricks_run_sql with no workspace arg: uses default workspace."""
    from tools import databricks_run_sql
    result = json.loads(databricks_run_sql({"sql": "SELECT current_user() AS user"}))
    if _skip_if_auth(result, "run_sql_basic"):
        return
    assert "error" not in result, f"run_sql error: {result.get('error')}"
    assert result.get("row_count", 0) == 1, f"expected 1 row: {result}"
    print(f"  current_user={result['rows'][0][0]}")


def test_run_sql_explicit_workspace():
    """databricks_run_sql with explicit workspace= matching the default."""
    from tools import databricks_run_sql
    ws = _get_default_workspace_name()
    if not ws:
        print("  [skip] no default workspace configured")
        return
    result = json.loads(databricks_run_sql({"sql": "SELECT 42 AS n", "workspace": ws}))
    if _skip_if_auth(result, "run_sql_explicit_workspace"):
        return
    assert "error" not in result, f"run_sql error: {result.get('error')}"
    assert result.get("row_count", 0) == 1, f"expected 1 row: {result}"
    print(f"  workspace={ws}  result={result['rows'][0][0]}")


def test_run_sql_warehouse_override():
    """databricks_run_sql with explicit warehouse_id override."""
    from tools import databricks_run_sql
    ws = _get_default_workspace_name()
    if not ws:
        print("  [skip] no default workspace configured")
        return
    wh_id = _get_running_warehouse_id(ws)
    if not wh_id:
        print(f"  [skip] no warehouse ID available for workspace={ws}")
        return
    result = json.loads(databricks_run_sql({
        "sql": "SELECT 99 AS answer",
        "workspace": ws,
        "warehouse_id": wh_id,
    }))
    if _skip_if_auth(result, "run_sql_warehouse_override"):
        return
    assert "error" not in result, f"run_sql warehouse override error: {result.get('error')}"
    assert result.get("row_count", 0) == 1, f"expected 1 row: {result}"
    print(f"  warehouse_id={wh_id}  result={result['rows'][0][0]}")


def test_ping_bad_workspace():
    """databricks_ping with a nonexistent workspace name: must return {"error": ...}."""
    from tools import databricks_ping
    result = json.loads(databricks_ping({"workspace": "_nonexistent_workspace_xyz_"}))    
    assert "error" in result, f"expected error for bad workspace, got: {result}"
    assert "_nonexistent_workspace_xyz_" in result["error"], (
        f"error message should mention workspace name: {result['error']}"
    )
    print(f"  error (expected): {result['error'][:100]}")
