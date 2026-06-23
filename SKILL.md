---
name: databricks
description: "Interact with Databricks via REST API: OAuth2 service-principal auth, Unity Catalog browsing, SQL Statement API execution, and warehouse management."
version: 1.0.0
tags: [databricks, unity-catalog, sql, rest-api, data-platform, delta-lake]
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
---

# Databricks Plugin

Native Hermes plugin for Databricks Unity Catalog browsing and SQL execution via the REST API.
Credentials are stored in macOS Keychain under the `hermes-databricks` service.

## This User's Workspace

| Setting | Value |
|---------|-------|
| **Workspace** | `https://dbc-e0b9d669-efb7.cloud.databricks.com` |
| **Default warehouse** | `ed4e7a4296f9661b` (XS — cheapest, use for metadata/analysis) |
| **SP client_id** | `cf46964f-f46a-4a86-a6dc-6fdc27994699` |
| **Keychain service** | `hermes-databricks` |

## Available Tools

| Tool | Description |
|------|-------------|
| `databricks_ping` | Test connectivity. Returns current user and workspace host. |
| `databricks_list_catalogs` | List all Unity Catalog catalogs. |
| `databricks_list_schemas` | List schemas in a catalog. Param: `catalog`. |
| `databricks_list_tables` | List tables in a catalog.schema. Params: `catalog`, `schema`. |
| `databricks_get_schema` | Get columns for a table. Param: `table` as `catalog.schema.table`. |
| `databricks_run_sql` | Execute SQL. Returns `{"columns": [...], "rows": [...], "row_count": N}`. Warehouse auto-starts. |
| `databricks_list_warehouses` | List all SQL warehouses with IDs, names, sizes, and states. |

## Common Patterns

### Check connectivity
```
→ databricks_ping()
```

### Browse Unity Catalog
```
→ databricks_list_catalogs()
→ databricks_list_schemas(catalog="cat_salesforce_fomod_prod01")
→ databricks_list_tables(catalog="cat_salesforce_fomod_prod01", schema="silver")
→ databricks_get_schema(table="cat_salesforce_fomod_prod01.silver.account")
```

### Run a SQL query
```
→ databricks_run_sql(sql="SELECT COUNT(*) FROM cat_salesforce_fomod_prod01.silver.account")
→ databricks_run_sql(sql="SELECT id, name FROM cat_salesforce_fomod_prod01.silver.contact LIMIT 10")
→ databricks_run_sql(sql="SELECT ...", max_rows=500)
```

### Find available warehouses
```
→ databricks_list_warehouses()
```

## Known Catalog Structure

| Catalog | Schema | Contents |
|---------|--------|----------|
| `cat_salesforce_fomod_prod01` | silver | 266 tables — FoMod SF org (production). Primary SF source. |
| `cat_salesforce_fomod_dm3_qs` | silver | 262 tables — FoMod SF org (QS/staging). Includes SCD2 variants. |
| `cat_salesforce_classic_prod01` | silver | 165 tables — Classic/legacy SF org. Larger row counts. |
| `cat_data_science_prod` | bronze/silver/gold/staging | Feature engineering pipeline (future). |
| `cat_data_science_playground` | various | Personal sandbox schemas. |

All SF catalogs use the `silver` schema. Both base tables and `_scd2` (SCD Type 2 history) variants exist in fomod_prod01 and dm3_qs. For most analysis, use base table names only.

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
Tokens expire after 3600s and are refreshed automatically in-process when within 100s of expiry.
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

- **UNION ALL across many tables times out** — submit one COUNT(*) per table and poll in parallel. Do NOT use a single large UNION ALL for multi-table counts.
- **data_array values are all strings** — even INT/TIMESTAMP columns come back as strings. Cast explicitly.
- **Warehouse auto-start takes 30-90s** — the first query after a stop triggers auto-start. The plugin uses `wait_timeout=0s` + polling so this is transparent but adds latency.
- **Skip information_schema when iterating schemas** — `information_schema` always appears in schema listings. The plugin filters it out in `databricks_list_schemas`.
- **SCD2 variants** — many tables have a `_scd2` suffixed variant. For most analysis, use base table names. SCD2 tables track historical changes and have different row counts.
- **Token expiry** — tokens expire after 3600s. The plugin refreshes automatically in-process.
- **result.data_array can be null** — even on SUCCEEDED with 0 rows. Always use `r["result"]["data_array"] or []`.

## Setup

```bash
cd ~/Git_Repos/hermes-plugin-databricks
./setup.sh install   # symlink, enable, store creds, smoke test
./setup.sh status    # verify everything is green
```

Restart Hermes after install.

### Keychain entries

| Service | Key | Value |
|---------|-----|-------|
| `hermes-databricks` | `host` | Workspace URL |
| `hermes-databricks` | `client_id` | Service principal client ID |
| `hermes-databricks` | `client_secret` | Service principal client secret |
| `hermes-databricks` | `warehouse_id` | SQL warehouse ID |
