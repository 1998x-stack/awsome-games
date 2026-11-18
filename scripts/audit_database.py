#!/usr/bin/env python3
"""Read-only inspection of the committed SQLite catalog (no schema creation).

Unlike db.connect(), this command never runs schema DDL, enables WAL, or
creates a missing database. Intended for CI and pre-migration audits.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "catalog.sqlite"

CORE_TABLES = (
    "projects", "categories", "project_categories", "repositories",
    "project_repositories", "links", "prompts", "evidence_sources",
    "project_evidence", "repository_files", "aliases", "ingest_runs",
    "ingest_errors",
)
RESEARCH_TABLES = (
    "research_repositories", "research_works", "research_posts",
    "research_post_prompt_evidence", "research_source_records",
    "research_claims", "research_project_links", "research_browser_runs",
    "research_runtime_evidence", "research_work_reviews",
    "research_post_reviews", "research_ingest_meta",
)
# research_review_history is created by a separate explicit review operation.
REQUIRED_COLUMNS = {
    "projects": ("id", "slug", "title", "playable_status"),
    "repositories": ("id", "full_name", "clone_status", "commit_sha"),
    "project_repositories": (
        "project_id", "repository_id", "entry_path", "game_path",
        "playable_status",
    ),
    "project_evidence": ("project_id", "evidence_source_id", "evidence_type"),
    "research_works": ("work_id", "repository_full_name", "entry_path"),
    "research_runtime_evidence": (
        "evidence_id", "work_id", "repo_commit_sha", "entry_sha256",
        "report_status",
    ),
}


def inspect_database(path: Path, profile: str = "full") -> dict:
    """Return a structural report without writing to the database."""
    problems: list[str] = []
    report: dict = {
        "database": str(path),
        "profile": profile,
        "database_exists": path.is_file(),
        "integrity_check": "NOT_RUN",
        "foreign_key_errors": None,
        "user_version": None,
        "schema_sha256": None,
        "tables": {},
        "object_counts": {},
        "problems": problems,
    }
    if not path.is_file():
        problems.append("Database does not exist (no file was created)")
        return report

    try:
        # mode=ro (without immutable=1) respects live WAL records.
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA query_only=ON")
            conn.execute("PRAGMA foreign_keys=ON")
            report["user_version"] = conn.execute("PRAGMA user_version").fetchone()[0]
            integrity_rows = [r[0] for r in conn.execute("PRAGMA integrity_check")]
            report["integrity_check"] = "ok" if integrity_rows == ["ok"] else integrity_rows[:5]
            if integrity_rows != ["ok"]:
                problems.append("SQLite integrity_check is not ok")
            fks = conn.execute("PRAGMA foreign_key_check").fetchall()
            report["foreign_key_errors"] = len(fks)
            if fks:
                problems.append(f"{len(fks)} foreign key violation(s)")

            objects = conn.execute(
                "SELECT type, name, sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
            ).fetchall()
            all_tables = {r["name"] for r in objects if r["type"] == "table"}
            report["object_counts"] = {
                kind: sum(1 for r in objects if r["type"] == kind)
                for kind in ("table", "index", "view", "trigger")
            }
            schema_text = "\n".join(
                f"{r['type']}|{r['name']}|{r['sql'] or ''}" for r in objects
            )
            report["schema_sha256"] = hashlib.sha256(
                schema_text.encode("utf-8")
            ).hexdigest()
            required = CORE_TABLES + (RESEARCH_TABLES if profile == "full" else ())
            for name in required:
                if name not in all_tables:
                    problems.append(f"Missing required table: {name}")
            for name in sorted(all_tables):
                # Names come only from SQLite's own schema.
                safe_name = '"' + name.replace('"', '""') + '"'
                columns = [r["name"] for r in conn.execute(
                    f"PRAGMA table_info({safe_name})"
                )]
                rows = conn.execute(f"SELECT COUNT(*) FROM {safe_name}").fetchone()[0]
                report["tables"][name] = {"rows": rows, "columns": columns}
                for col in REQUIRED_COLUMNS.get(name, ()):
                    if col not in columns:
                        problems.append(f"Missing required column: {name}.{col}")

            if "project_repositories" in all_tables and {
                "game_path", "playable_status"
            }.issubset(report["tables"]["project_repositories"]["columns"]):
                missing_path = conn.execute(
                    "SELECT COUNT(*) FROM project_repositories "
                    "WHERE playable_status='entrypoint_found' "
                    "AND TRIM(COALESCE(game_path,''))=''"
                ).fetchone()[0]
                report["entrypoint_found_without_game_path"] = missing_path
                if missing_path:
                    problems.append(
                        f"{missing_path} entrypoint_found mapping(s) without game_path"
                    )
        finally:
            conn.close()
    except (sqlite3.DatabaseError, sqlite3.OperationalError, OSError) as exc:
        problems.append("Database inspection failed: " + str(exc))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--profile", choices=("core", "full"), default="full")
    parser.add_argument("--out", type=Path, help="Optional JSON report path")
    args = parser.parse_args(argv)
    result = inspect_database(args.db, args.profile)
    body = json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    print(body, end="")
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(body, encoding="utf-8")
    return 1 if result["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
