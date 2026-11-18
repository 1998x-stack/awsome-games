# SQLite data inventory, integrity and migration baseline

> Source audit of the post-PR-#15 main branch (2026-11-18). Use the CLI below for actual database counts; historical counts are not new live measurements.

## Data flow and authority

```text
config/ + data/seeds/ + data/research/v1/ (reviewed inputs)
           |
           v
data/catalog.sqlite (versioned operational snapshot)
           | build_catalog.py / build_site.py
           v
data/catalog.json + CSV -> site/data/ -> GitHub Pages
```

**Do not confuse projections, raw evidence, reviewed facts and public publication approval.** The committed SQLite file is operational state, but `scripts/db.py` and `scripts/research_pipeline.py` are the schema declarations. `CREATE TABLE IF NOT EXISTS` does not migrate changed columns. A proper migration ledger is currently absent; `PRAGMA user_version` should not be mistaken for a vetted schema version.

## Table groups

| Group | Tables | Meaning |
| --- | --- | --- |
| Core (13) | `projects`, `categories`, `project_categories`, `repositories`, `project_repositories`, `links`, `prompts`, `evidence_sources`, `project_evidence`, `repository_files`, `aliases`, `ingest_runs`, `ingest_errors` | Stable catalog identifiers, category labels, repository mappings, source evidence and collection history |
| Research (12) | `research_repositories`, `research_works`, `research_posts`, `research_post_prompt_evidence`, `research_source_records`, `research_claims`, `research_project_links`, `research_browser_runs`, `research_runtime_evidence`, `research_work_reviews`, `research_post_reviews`, `research_ingest_meta` | Source observations, independent works, human review and measured browser evidence |
| Optional review | `research_review_history` | Created by the explicit reviewer tool; not always present before reviewing |

A project is **not** a repository. A research post is **not** a work. `project_repositories` maps projects to repositories with a composite PK and one recorded entrypoint per project/repository mapping. Supporting multiple entrypoints on one mapping would require a new normalized entrypoints table and migration, not duplicate rows. `projects.playable_status` is an aggregate while `project_repositories.playable_status` is per relation; their precedence logic should eventually be shared and tested.

## Read-only audit added in this PR

```bash
python scripts/audit_database.py --db data/catalog.sqlite --profile full
python scripts/audit_database.py --db data/catalog.sqlite --profile core
python scripts/audit_database.py --profile full --out .cache/database-audit.json
```

The auditor opens SQLite with URI `mode=ro` and `PRAGMA query_only=ON`; it **never** calls the schema-creating `db.connect()` and refuses to create missing databases. It records table/column inventory, row counts, index/view/trigger totals, SQLite integrity and FK checks, schema SHA-256 fingerprint, `user_version`, required table/column checks and empty `game_path` on `entrypoint_found` rows. It exits nonzero on failures.

Schema SHA-256 is a **structure signature**, not a row-content hash or an evidence authenticity guarantee. Read-only WAL readers may still require SQLite sidecar files. Use `check_catalog.py` as well for filesystem-path validation, secret-looking filenames and catalog.json parity.

## Historical baseline versus current audits

PR #15 documented 155 catalog projects, 54 repositories, 150 project-to-repository mappings, 123 local entrypoint probes across 32 repositories, 4 attributable input responses, **0 gameplay-verified** and 1 public playable artifact. These are historical report metrics, not proof of 123 playable games. CI should supply current database counts after import.

## Migration / backup protocol (not yet implemented)

1. Before **any** destructive operation, create a WAL-safe `sqlite3.Connection.backup()` snapshot. Validate destination `integrity_check` and record source commit, backup SHA-256, time and expected counts.
2. Introduce a numbered schema migration ledger/`user_version` and fail closed on unknown future versions. Test forward migration and restore before using on main.
3. Preserve `projects.id`, `research_works.work_id`, source-record compound identity and human review history through any refactor.
4. Apply migrations transactionally on a copy first. Compare IDs/counts, FK checks, schema fingerprint, generated JSON and published site count. Never rewrite a database from seed without retaining reviewed runtime state.
5. Treat runtime timeouts as environment evidence, not proof a game is broken. Do not infer rights, gameplay validation or identity from a positive pixel change.
6. PR #12 changes SQLite and seed provenance, but is conflicted with main. Rebase in a separate PR; avoid overwriting PR #15's audit and runtime evidence.

## What is not established

This audit does **not** perform a versioned migration, license audit, external URL verification or full game behavior E2E test. `build_catalog.py --check` writes the imported snapshot before checking it; `check_catalog.py` calls a DDL-initializing connection. Only the new auditor is designed to be non-mutating.
