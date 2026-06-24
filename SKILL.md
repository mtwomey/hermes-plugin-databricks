---
name: databricks
description: "Interact with Databricks workspaces via REST API: multi-workspace support, OAuth2 service-principal auth, Unity Catalog browsing, SQL Statement API execution, and warehouse management."
version: 2.0.0
tags: [databricks, unity-catalog, sql, rest-api, data-platform, delta-lake, multi-workspace]
triggers:
  - "query Databricks"
  - "run SQL on Databricks"
  - "list Databricks catalogs"
  - "browse Unity Catalog"
  - "Databricks SQL"
  - "Databricks Statement API"
  - "Databricks REST API"
  - "list Databricks tables or schemas"
  - "Databricks warehouse"
  - "list Databricks workspaces"
  - "switch Databricks workspace"
---

# Databricks Plugin

Native Hermes plugin for multi-workspace Databricks Unity Catalog browsing and SQL execution via the REST API.
Credentials are stored in macOS Keychain — one service per workspace (`hermes-databricks-<name>`) plus a sentinel service (`hermes-databricks`) that tracks the default workspace and workspace manifest.

## Workspaces

Manage workspaces via the CLI (read-only listing available as a tool):

```bash
cd ~/Git_Repos/hermes-plugin-databricks

# List all configured workspaces
python setup.py workspace list

# Add a new workspace
python setup.py workspace add prod

# Update credentials for an existing workspace
python setup.py workspace update prod

# Set the default workspace
python setup.py workspace set-default prod

# Remove a workspace
python setup.py workspace remove dev
```

To query a specific workspace in a tool call, pass `workspace="<name>"`. Omit it to use the default.

## Available Tools

| Tool | Description |
|------|-------------|
| `databricks_list_workspaces` | List all configured workspaces (name, host, warehouse, default flag). No args. |
| `databricks_ping` | Test connectivity. Returns current user, host, and workspace. |
| `databricks_list_catalogs` | List all Unity Catalog catalogs. |
| `databricks_list_schemas` | List schemas in a catalog. Params: `catalog`. |
| `databricks_list_tables` | List tables in a catalog.schema. Params: `catalog`, `schema`. |
| `databricks_get_schema` | Get columns for a table. Param: `table` as `catalog.schema.table`. |
| `databricks_run_sql` | Execute SQL. Optional `warehouse_id` override. Returns `{"columns": [...], "rows": [...], "row_count": N}`. |
| `databricks_list_warehouses` | List all SQL warehouses with IDs, names, sizes, and states. |

All tools accept an optional `workspace` param (e.g. `workspace="dev"`). Omit to use the default workspace.

## Common Patterns

### Check which workspaces are configured
```
→ databricks_list_workspaces()
```

### Check connectivity on the default workspace
```
→ databricks_ping()
```

### Check connectivity on a specific workspace
```
→ databricks_ping(workspace="dev")
```

### Browse Unity Catalog (default workspace)
```
→ databricks_list_catalogs()
→ databricks_list_schemas(catalog="cat_salesforce_fomod_prod01")
→ databricks_list_tables(catalog="cat_salesforce_fomod_prod01", schema="silver")
→ databricks_get_schema(table="cat_salesforce_fomod_prod01.silver.account")
```

### Browse Unity Catalog on a specific workspace
```
→ databricks_list_catalogs(workspace="dev")
→ databricks_list_schemas(catalog="cat_salesforce_fomod_prod01", workspace="dev")
```

### Run a SQL query
```
→ databricks_run_sql(sql="SELECT COUNT(*) FROM cat_salesforce_fomod_prod01.silver.account")
→ databricks_run_sql(sql="SELECT id, name FROM cat_salesforce_fomod_prod01.silver.contact LIMIT 10")
→ databricks_run_sql(sql="SELECT ...", max_rows=500)
→ databricks_run_sql(sql="SELECT ...", workspace="dev")
→ databricks_run_sql(sql="SELECT ...", warehouse_id="abc123")  # override warehouse
```

### Find available warehouses
```
→ databricks_list_warehouses()
→ databricks_list_warehouses(workspace="dev")
```

## Keychain Layout

| Service | Key | Value |
|---------|-----|-------|
| `hermes-databricks` | `default_workspace` | Name of the default workspace (e.g. `prod`) |
| `hermes-databricks` | `workspaces` | Comma-separated list of workspace names |
| `hermes-databricks-<name>` | `host` | Workspace URL |
| `hermes-databricks-<name>` | `client_id` | Service principal client ID |
| `hermes-databricks-<name>` | `client_secret` | Service principal client secret |
| `hermes-databricks-<name>` | `warehouse_id` | SQL warehouse ID |

## Known Catalog Structure (prod workspace)

| Catalog | Schema | Contents |
|---------|--------|----------|
| `cat_salesforce_fomod_prod01` | silver | 266 tables — FoMod SF org (production). Primary SF source. |
| `cat_salesforce_fomod_dm3_qs` | silver | 262 tables — FoMod SF org (QS/staging). Includes SCD2 variants. |
| `cat_salesforce_classic_prod01` | silver | 165 tables — Classic/legacy SF org. Larger row counts. |
| `cat_data_science_prod` | bronze/silver/gold/staging | Feature engineering pipeline (future). |
| `cat_data_science_playground` | various | Personal sandbox schemas. |

All SF catalogs use the `silver` schema. Both base tables and `_scd2` (SCD Type 2 history) variants exist in fomod_prod01 and dm3_qs.

### Commonly Used Tables (fomod_prod01.silver)
```sql
cat_salesforce_fomod_prod01.silver.account
cat_salesforce_fomod_prod01.silver.contact
cat_salesforce_fomod_prod01.silver.event
cat_salesforce_fomod_prod01.silver.task
cat_salesforce_fomod_prod01.silver.opportunity
cat_salesforce_fomod_prod01.silver.job_order__c
cat_salesforce_fomod_prod01.silver.lead
cat_salesforce_fomod_prod01.silver.rh_contract__c
```

## Authentication

OAuth2 service principal (client_credentials flow) via `/oidc/v1/token`.
Tokens expire after 3600s and are refreshed automatically per-workspace in-process when within 100s of expiry.
No manual refresh needed during normal operation.

## Statement API Response Shape

```
{
  "statement_id": "...",
  "status": {"state": "PENDING|RUNNING|SUCCEEDED|FAILED|CANCELED|CLOSED"},
  "manifest": {
    "schema": {
      "columns": [{"name": "col1", "type_name": "STRING", "position": 0}, ...]
    }
  },
  "result": {
    "data_array": [["val1", "val2"], ...]  // null when 0 rows — always use `or []`
  }
}
```

**All values in `data_array` are strings.** Cast explicitly: `int(row[0])` for counts.

## Pitfalls

- **UNION ALL across many tables times out** — submit one COUNT(*) per table and poll in parallel.
- **data_array values are all strings** — even INT/TIMESTAMP columns come back as strings. Cast explicitly.
- **Warehouse auto-start takes 30-90s** — first query after a stop adds latency. Plugin uses `wait_timeout=0s` + polling so this is transparent.
- **Skip information_schema when iterating schemas** — filtered out automatically in `databricks_list_schemas`.
- **SCD2 variants** — many tables have a `_scd2` suffixed variant. For most analysis, use base table names.
- **Token expiry** — tokens expire after 3600s. Plugin refreshes per-workspace automatically.
- **result.data_array can be null** — even on SUCCEEDED with 0 rows. Always use `r["result"]["data_array"] or []`.
- **Bad workspace name** — passing an unknown `workspace=` returns `{"error": "Workspace 'x' credential 'host' not found..."}` with setup instructions.
- **No default configured** — if `default_workspace` is empty, all tools return `{"error": "No default workspace configured. Run: python setup.py workspace add <name>"}`. Fix with `python setup.py workspace set-default <name>`.

## Setup

```bash
cd ~/Git_Repos/hermes-plugin-databricks
python setup.py install            # symlink plugin into Hermes
python setup.py workspace add prod # enter credentials for 'prod' workspace
python setup.py workspace list     # verify setup
python setup.py audit              # check compliance
python setup.py test               # smoke test
```

Restart Hermes after install.
