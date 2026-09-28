# dremio_handoff_bronze — Table Inventory & Caveats
**Workspace:** dev (`dbc-c35981f5-b091.cloud.databricks.com`)
**Catalog/Schema:** `cat_data_science_dev01.dremio_handoff_bronze`
**Source:** Mirrors `s3://dremio-handoff` S3 bucket as external Parquet tables.
**Verified:** 2026-07-02

## Tables

| Table | Row Count | Notes |
|-------|-----------|-------|
| `fomod_arc_model_monitoring` | 37.4M | ARC model scoring monitoring data |
| `net_new_acquisition` | 2.0M | New acquisition signals |
| `retention_and_regage` | 2.35B ⚠️ | Massive — always filter on `obs_date` |
| `retention_and_regage_perm` | 158.2M | Perm-specific retention/reengagement |
| `zoominfo_intents` | 4.0M | ZoomInfo intent signals |
| `zoominfo_scoops` | 14.0M | ZoomInfo company activity/hiring/M&A signals (updated daily — most recent records from 2026-07-01) |

## zoominfo_scoops Schema
| Column | Type | Notes |
|--------|------|-------|
| `id` | LONG | Scoop ID |
| `publisheddate` | TIMESTAMP_NTZ | Date scoop was published (use for recency filtering) |
| `originalpublisheddate` | TIMESTAMP_NTZ | Usually same as publisheddate |
| `linktext` | STRING | Link label (e.g. "See details") |
| `description` | STRING | Full scoop text — leadership changes, M&A, job postings, conferences |
| `updatetext` | STRING | Update notes (often empty) |
| `company_id` | LONG | ZoomInfo company ID |
| `company_name` | STRING | Company name |

## ⚠️ External Table Partition Pruning Caveat
These are **external Parquet tables with `recursiveFileLookup=true`**. Key differences vs Dremio:
- **Dremio** auto-generates `dir0`, `dir1` partition columns from S3 folder paths (e.g. `2026/06/` → `dir0='2026'`, `dir1='06'`).
- **Databricks** does NOT expose folder structure as columns — folder paths are invisible to queries.
- Spark scans ALL files on every query, then applies your WHERE clause — no folder-based pruning.
- **Always filter on columns inside the Parquet files** (e.g. `publisheddate`, `obs_date`) to avoid full scans.
- `retention_and_regage` at 2.35B rows is especially dangerous — never query without a tight date filter.

## Context
Documented by Benjamin Trinh (HRFS Data Services) in email to Keely Weisbeck + Matthew Twomey, 2026-06-26.
Tables set up as zero-copy external tables (no data moved from S3).
