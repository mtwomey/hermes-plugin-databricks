---
name: databricks
description: >
  Databricks Unity Catalog and SQL warehouses via the databricks native plugin.
  This is a redirect stub — load the full skill with skill_view(name="databricks:databricks").
category: data-science
triggers:
  - "databricks"
  - "unity catalog"
  - "databricks sql"
  - "run sql on databricks"
  - "databricks_"
---

# databricks — redirect stub

The full skill lives inside the `databricks` plugin and is registered at runtime.

**Load it with:**

```
skill_view(name="databricks:databricks")
```

This stub exists solely so `skills_list(category="data-science")` surfaces the skill
and agents can discover the correct namespaced name.

## Session-Specific References

- `references/dremio-handoff-bronze-tables.md` — Inventory of `cat_data_science_dev01.dremio_handoff_bronze` tables (6 external Parquet tables mirroring `s3://dremio-handoff`), row counts, schemas, and the critical partition-pruning caveat for external tables in Databricks vs Dremio. Verified 2026-07-02.
