# PAT Auth Support for hermes-plugin-databricks

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Add Personal Access Token (PAT) authentication as an alternative to OAuth2 client_credentials for individual Databricks workspaces, with both modes supported simultaneously across workspaces.

**Architecture:**
Each workspace stores an `auth_type` credential key (`"oauth"` or `"pat"`). The `_get_token()` function is split into two paths: the existing OAuth2 flow for `oauth` workspaces, and a trivial passthrough returning the stored PAT for `pat` workspaces (no HTTP call, no expiry). The `setup.py workspace add/update` CLI detects auth type via an upfront prompt and only asks for the relevant credential keys.

**Tech Stack:** Python 3, macOS Keychain via `hermes_plugin_core.keychain`, `requests`, `hermes_plugin_core.setup_cli.SetupCLI`

---

## Invariants (must hold throughout all tasks)

- Every handler returns `json.dumps({...})` — never a raw dict.
- Credentials load lazily on first tool call.
- `cred_get` returns `None` — always check `if not val:` explicitly.
- `ctx.register_tool()` always uses `name=` and `toolset=` as explicit kwargs.
- `plugin.yaml`, `schemas.py`, `__init__.py` do **not** change — this is a pure auth-layer and setup-CLI change.
- All changes in `tools.py` and `setup.py` must pass `python setup.py audit` (private `_*` helper warnings are acceptable).

---

## Files That Change

| File | What changes |
|------|-------------|
| `tools.py` | `WORKSPACE_KEYS` list + `_get_workspace_state()` + `_get_token()` / `_headers()` — PAT branch |
| `setup.py` | `WORKSPACE_KEYS`, `WORKSPACE_KEY_LABELS`, `cmd_workspace` (add/update/list subcommands) |
| `SKILL.md` | Keychain Layout table, Authentication section, Pitfalls, Setup |
| `tests/plugin_tests.py` | Auth-type introspection helper + `test_list_workspaces` assertion for `auth_type` field |

---

## Task 1 — Extend the credential schema in `tools.py`

**Objective:** Make `_get_workspace_state()` load `auth_type` and either `client_id`/`client_secret` (oauth) or `pat` (pat), and make `_get_token()` / `_headers()` branch accordingly.

**Files:**
- Modify: `tools.py` lines 26–87

**Step 1: Replace `WORKSPACE_KEYS` constant**

Current (line 26):
```python
WORKSPACE_KEYS = ["host", "client_id", "client_secret", "warehouse_id"]
```

Replace with:
```python
WORKSPACE_KEYS_COMMON = ["host", "warehouse_id"]
WORKSPACE_KEYS_OAUTH  = ["client_id", "client_secret"]
WORKSPACE_KEYS_PAT    = ["pat"]
```

**Step 2: Replace `_get_workspace_state()`**

Replace the entire function (lines 40–57) with:

```python
def _get_workspace_state(ws_name: str) -> dict:
    """Load credentials for ws_name from keychain on first call; return cached dict thereafter."""
    if ws_name not in _workspace_states:
        svc = f"hermes-databricks-{ws_name}"
        state: dict = {}

        # Common keys
        for key in WORKSPACE_KEYS_COMMON:
            val = cred_get(svc, key)
            if not val:
                raise RuntimeError(
                    f"Workspace '{ws_name}' credential '{key}' not found. "
                    f"Run: python setup.py workspace add {ws_name}"
                )
            state[key] = val

        state["host"] = state["host"].rstrip("/")

        # Auth type
        auth_type = (cred_get(svc, "auth_type") or "oauth").lower().strip()
        if auth_type not in ("oauth", "pat"):
            raise RuntimeError(
                f"Workspace '{ws_name}' has unknown auth_type '{auth_type}'. "
                f"Expected 'oauth' or 'pat'."
            )
        state["auth_type"] = auth_type

        if auth_type == "oauth":
            for key in WORKSPACE_KEYS_OAUTH:
                val = cred_get(svc, key)
                if not val:
                    raise RuntimeError(
                        f"Workspace '{ws_name}' credential '{key}' not found. "
                        f"Run: python setup.py workspace update {ws_name}"
                    )
                state[key] = val
            state["token"] = None
            state["token_expires_at"] = 0
        else:  # pat
            val = cred_get(svc, "pat")
            if not val:
                raise RuntimeError(
                    f"Workspace '{ws_name}' credential 'pat' not found. "
                    f"Run: python setup.py workspace update {ws_name}"
                )
            state["pat"] = val

        _workspace_states[ws_name] = state
    return _workspace_states[ws_name]
```

**Step 3: Replace `_get_token()` and `_headers()`**

Replace lines 60–87 with:

```python
def _get_token(ws_name: str) -> str:
    """Return a valid Bearer token for ws_name.

    - oauth: fetches/caches OAuth2 client_credentials token, refreshed 100s before expiry.
    - pat:   returns the stored PAT directly (no HTTP call, PATs do not expire automatically).
    """
    state = _get_workspace_state(ws_name)
    if state["auth_type"] == "pat":
        return state["pat"]

    # oauth path
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
```

**Step 4: Verify no other references to old `WORKSPACE_KEYS` list in tools.py**

Search for `WORKSPACE_KEYS` in `tools.py`. The only reference should be the three new constants at the top. (The old `WORKSPACE_KEYS` list no longer exists in tools.py — the setup.py still has its own copy, which is updated separately in Task 2.)

**Step 5: Run a quick import check**
```bash
cd ~/Git_Repos/hermes-plugin-databricks
python -c "import tools; print('import ok')"
```
Expected: `import ok`

**Step 6: Commit**
```bash
git add tools.py
git commit -m "feat: add PAT auth branch to _get_workspace_state and _get_token"
```

---

## Task 2 — Update `setup.py` workspace CLI for dual auth types

**Objective:** `workspace add <name>` asks auth type upfront and prompts only for the relevant keys. `workspace update <name>` shows current auth type and prompts the right keys. `workspace list` shows `auth_type` per workspace. `workspace remove <name>` deletes the correct auth-type keys from Keychain.

**Files:**
- Modify: `setup.py` lines 27–186

**Step 1: Replace constants at the top of setup.py**

Current:
```python
WORKSPACE_KEYS = ["host", "client_id", "client_secret", "warehouse_id"]
WORKSPACE_KEY_LABELS = {
    "host":          ("Workspace URL (e.g. https://dbc-xxx.cloud.databricks.com)", False),
    "client_id":     ("Service Principal Client ID", False),
    "client_secret": ("Client Secret", True),
    "warehouse_id":  ("SQL Warehouse ID (e.g. ed4e7a4296f9661b)", False),
}
```

Replace with:
```python
WORKSPACE_KEYS_COMMON = ["host", "warehouse_id"]
WORKSPACE_KEYS_OAUTH  = ["client_id", "client_secret"]
WORKSPACE_KEYS_PAT    = ["pat"]
# All possible credential keys — used by workspace remove to clean up Keychain completely
WORKSPACE_KEYS_ALL    = WORKSPACE_KEYS_COMMON + WORKSPACE_KEYS_OAUTH + WORKSPACE_KEYS_PAT + ["auth_type"]

WORKSPACE_KEY_LABELS = {
    "host":          ("Workspace URL (e.g. https://dbc-xxx.cloud.databricks.com)", False),
    "warehouse_id":  ("SQL Warehouse ID (e.g. ed4e7a4296f9661b)", False),
    "client_id":     ("Service Principal Client ID", False),
    "client_secret": ("Client Secret", True),
    "pat":           ("Personal Access Token", True),
}
```

**Step 2: Add `_prompt_auth_type()` helper**

Insert after `_prompt()`:
```python
def _prompt_auth_type(current: str = "") -> str:
    """Prompt for auth type; return 'oauth' or 'pat'."""
    hint = f" [{current}]" if current else " [oauth]"
    while True:
        val = input(f"  Auth type (oauth / pat){hint}: ").strip().lower() or current or "oauth"
        if val in ("oauth", "pat"):
            return val
        print("  Must be 'oauth' or 'pat'. Try again.")
```

**Step 3: Replace `workspace add` block**

Replace the `elif subcmd == "add":` block (lines 83–120) with:

```python
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

    # Common keys
    vals = {}
    for key in WORKSPACE_KEYS_COMMON:
        label, is_secret = WORKSPACE_KEY_LABELS[key]
        vals[key] = _prompt(label, is_secret)
        if not vals[key]:
            print(f"  Error: {key} is required.")
            sys.exit(1)

    # Auth type
    auth_type = _prompt_auth_type()
    vals["auth_type"] = auth_type

    # Auth-specific keys
    auth_keys = WORKSPACE_KEYS_OAUTH if auth_type == "oauth" else WORKSPACE_KEYS_PAT
    for key in auth_keys:
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
    print(f"  Workspace '{name}' saved (auth_type={auth_type}).")

    set_default = input("  Set as default workspace? [y/N]: ").strip().lower()
    if set_default == "y":
        cred_set(PLUGIN_SERVICE, "default_workspace", name)
        print(f"  '{name}' is now the default workspace.")

    if not cred_get(PLUGIN_SERVICE, "default_workspace"):
        cred_set(PLUGIN_SERVICE, "default_workspace", name)
        print(f"  No default was set — '{name}' auto-set as default.")
```

**Step 4: Replace `workspace remove` block**

Update the `for key in WORKSPACE_KEYS:` loop in the remove block to use `WORKSPACE_KEYS_ALL`:
```python
for key in WORKSPACE_KEYS_ALL:
    try:
        cred_delete(svc, key)
    except Exception:
        pass
```

**Step 5: Replace `workspace update` block**

Replace the `elif subcmd == "update":` block with:
```python
elif subcmd == "update":
    if not name:
        print("Usage: python setup.py workspace update <name>")
        sys.exit(1)
    manifest = _get_manifest()
    if name not in manifest:
        print(f"Workspace '{name}' not found.")
        sys.exit(1)
    svc = _workspace_service(name)
    current_auth = (cred_get(svc, "auth_type") or "oauth").lower()
    print(f"Updating workspace '{name}' (auth_type={current_auth}, leave blank to keep current value):")

    # Common keys
    for key in WORKSPACE_KEYS_COMMON:
        label, is_secret = WORKSPACE_KEY_LABELS[key]
        current = "" if is_secret else (cred_get(svc, key) or "")
        new_val = _prompt(label, is_secret, current)
        if new_val:
            cred_set(svc, key, new_val)

    # Auth type (can change — if switching, old auth keys are deleted)
    new_auth = _prompt_auth_type(current=current_auth)
    if new_auth != current_auth:
        # Delete stale auth keys from old type
        old_keys = WORKSPACE_KEYS_OAUTH if current_auth == "oauth" else WORKSPACE_KEYS_PAT
        for key in old_keys:
            try:
                cred_delete(svc, key)
            except Exception:
                pass
        cred_set(svc, "auth_type", new_auth)
        print(f"  Switched auth_type from '{current_auth}' to '{new_auth}'.")
        current_auth = new_auth

    # Auth-specific keys for the (possibly new) type
    auth_keys = WORKSPACE_KEYS_OAUTH if current_auth == "oauth" else WORKSPACE_KEYS_PAT
    for key in auth_keys:
        label, is_secret = WORKSPACE_KEY_LABELS[key]
        # Never display current value for secrets (client_secret, pat)
        current = "" if is_secret else (cred_get(svc, key) or "")
        new_val = _prompt(label, is_secret, current)
        if new_val:
            cred_set(svc, key, new_val)
    print(f"  Workspace '{name}' updated.")
```

**Step 6: Replace `workspace list` block**

Update the print line inside the `for n in manifest:` loop to include `auth_type`:
```python
auth_type = cred_get(_workspace_service(n), "auth_type") or "oauth"
print(f"  {n}{marker}  auth={auth_type}  host={host}  warehouse={wh}")
```

**Step 7: Verify import**
```bash
cd ~/Git_Repos/hermes-plugin-databricks
python -c "import setup; print('import ok')"
```
Expected: `import ok`

**Step 8: Commit**
```bash
git add setup.py
git commit -m "feat: workspace CLI prompts for auth type, stores auth_type + PAT in Keychain"
```

---

## Task 3 — Update `databricks_list_workspaces` tool to expose `auth_type`

**Objective:** The tool response for each workspace includes `auth_type` so the LLM (and humans running `workspace list`) can see at a glance which workspaces use PAT vs. OAuth.

**Files:**
- Modify: `tools.py` — `databricks_list_workspaces` handler (lines 147–172)

**Step 1: Add `auth_type` to the per-workspace result dict**

Inside the `for name in names:` loop, add after `"warehouse_id"`:
```python
"auth_type": cred_get(svc, "auth_type") or "oauth",
```

Full updated dict:
```python
result.append({
    "name": name,
    "host": cred_get(svc, "host") or "(missing)",
    "warehouse_id": cred_get(svc, "warehouse_id") or "(missing)",
    "auth_type": cred_get(svc, "auth_type") or "oauth",
    "is_default": name == default,
})
```

**Step 2: Commit**
```bash
git add tools.py
git commit -m "feat: expose auth_type in databricks_list_workspaces response"
```

---

## Task 4 — Update tests

**Objective:** Smoke tests verify the `auth_type` field is present in `list_workspaces`, and a new helper correctly reads auth type from Keychain for use in other tests. The `_skip_if_auth` helper message is updated to not hard-code "SP auth".

**Files:**
- Modify: `tests/plugin_tests.py`

**Step 1: Update `_skip_if_auth` message to be auth-type-agnostic**

```python
def _skip_if_auth(result: dict, label: str) -> bool:
    """Return True and print a warning if this looks like an auth error."""
    if "error" in result and _is_auth_error(result["error"]):
        print(f"  [auth error] in {label}: {result['error']}")
        return True
    return False
```

**Step 2: Add `_get_default_workspace_auth_type()` helper**

```python
def _get_default_workspace_auth_type() -> str:
    """Return 'oauth' or 'pat' for the default workspace."""
    from hermes_plugin_core.keychain import cred_get
    ws = _get_default_workspace_name()
    if not ws:
        return "oauth"
    return (cred_get(f"hermes-databricks-{ws}", "auth_type") or "oauth").lower()
```

**Step 3: Update `test_list_workspaces` to assert `auth_type` present**

Add assertion after existing ones:
```python
for ws in result["workspaces"]:
    assert "auth_type" in ws, f"missing auth_type on workspace {ws.get('name')}: {ws}"
print(f"  workspaces: {[(w['name'], w['auth_type']) for w in result['workspaces']]}  default: {result.get('default')}")
```

**Step 4: Run tests**
```bash
cd ~/Git_Repos/hermes-plugin-databricks
python setup.py test
```
Expected: all existing tests pass (list_workspaces now also checks `auth_type`).

**Step 5: Commit**
```bash
git add tests/plugin_tests.py
git commit -m "test: assert auth_type in list_workspaces, update skip helper message"
```

---

## Task 5 — Update `SKILL.md`

**Objective:** The bundled skill accurately reflects the new dual-auth model.

**Files:**
- Modify: `SKILL.md`

**Step 1: Update the `## Authentication` section**

Replace:
```
OAuth2 service principal (client_credentials flow) via `/oidc/v1/token`.
Tokens expire after 3600s and are refreshed automatically per-workspace in-process when within 100s of expiry.
No manual refresh needed during normal operation.
```

With:
```
Two auth modes — configured per workspace, set at `workspace add` time:

**OAuth2 (service principal):** client_credentials flow via `/oidc/v1/token`.
Tokens expire after 3600s and are refreshed automatically per-workspace in-process when within 100s of expiry.

**PAT (Personal Access Token):** Token is stored in Keychain and passed directly as `Authorization: Bearer <pat>`.
No HTTP round-trip for auth, no expiry tracking. If a PAT is rotated, run `python setup.py workspace update <name>`.
```

**Step 2: Update the `## Keychain Layout` table**

Replace the table with:
```markdown
| Service | Key | Value |
|---------|-----|-------|
| `hermes-databricks` | `default_workspace` | Name of the default workspace (e.g. `prod`) |
| `hermes-databricks` | `workspaces` | Comma-separated list of workspace names |
| `hermes-databricks-<name>` | `host` | Workspace URL |
| `hermes-databricks-<name>` | `auth_type` | `"oauth"` or `"pat"` (defaults to `"oauth"` if absent) |
| `hermes-databricks-<name>` | `client_id` | Service principal client ID *(oauth only)* |
| `hermes-databricks-<name>` | `client_secret` | Service principal client secret *(oauth only)* |
| `hermes-databricks-<name>` | `pat` | Personal access token *(pat only)* |
| `hermes-databricks-<name>` | `warehouse_id` | SQL warehouse ID |
```

**Step 3: Add PAT pitfall to `## Pitfalls`**

Add:
```markdown
- **PAT rotation** — if a PAT is rotated on the Databricks side, all calls will return 401 until you run `python setup.py workspace update <name>` and enter the new token. The plugin will clear the in-process cache automatically on next restart.
- **Legacy workspaces without `auth_type`** — workspaces added before PAT support default to `"oauth"` gracefully (no migration needed).
- **Switching auth type** — `workspace update <name>` lets you switch between `oauth` and `pat`; old auth keys are deleted from Keychain automatically.
```

**Step 4: Update `## Setup` section**

Update the workspace add line to note the auth-type prompt:
```bash
python setup.py workspace add prod  # prompts: host, warehouse_id, auth type (oauth/pat), then auth-specific keys
```

**Step 5: Update `plugin.yaml` description to mention dual auth**

In `plugin.yaml` change the description line:
```yaml
description: >
  Interact with Databricks workspaces via REST API: multi-workspace support,
  OAuth2 service-principal auth or PAT auth per workspace, Unity Catalog browsing
  (catalogs, schemas, tables, columns), SQL Statement API execution,
  and SQL warehouse management.
```

**Step 6: Commit**
```bash
git add SKILL.md plugin.yaml
git commit -m "docs: update SKILL.md and plugin.yaml for dual auth (OAuth2 + PAT)"
```

---

## Task 6 — Add new PAT workspace and run full verification

**Objective:** Configure the new PAT workspace (`https://dbc-c35981f5-b091.cloud.databricks.com`), verify connectivity, and run `audit` to confirm no regressions.

**Step 1: Add the workspace**
```bash
cd ~/Git_Repos/hermes-plugin-databricks
python setup.py workspace add <name>
# Auth type prompt: pat
# Enter: host = https://dbc-c35981f5-b091.cloud.databricks.com
# Enter: warehouse_id = <from Databricks UI>
# Enter: PAT = <from https://dbc-c35981f5-b091.cloud.databricks.com/settings/user/developer/access-tokens>
```

**Step 2: List workspaces to confirm**
```bash
python setup.py workspace list
```
Expected: new workspace appears with `auth=pat`.

**Step 3: Run smoke tests**
```bash
python setup.py test
```
Expected: all pass (or `_skip_if_auth` for transient auth on other workspaces).

**Step 4: Run audit**
```bash
python setup.py audit
```
Expected: all checks pass (private `_*` helper warnings acceptable).

**Step 5: Restart Hermes** (tools.py changed)

**Step 6: Verify via tool call**
```
→ databricks_ping(workspace="<new-workspace-name>")
```
Expected: `{"status": "ok", "user": "...", "host": "https://dbc-c35981f5-b091.cloud.databricks.com", "workspace": "<name>"}`

---

## Open Questions / Notes

- The workspace name for `dbc-c35981f5-b091` has not been decided — choose something memorable (e.g. `uat`, `sandbox`, `env2`). Just needs to be alphanumeric/hyphens/underscores.
- The in-process `_workspace_states` cache holds the PAT for the process lifetime. If the PAT is rotated mid-session, a Hermes restart is required to pick up the new value (same as any credential change).
- `workspace update` supports switching a workspace from `oauth` → `pat` or vice versa; old keys are cleaned up automatically. This is a forward-looking capability, not needed for the immediate task.
