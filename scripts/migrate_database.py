#!/usr/bin/env python3
"""Fail-closed, WAL-safe SQLite migration ledger.

V1 baselines the *observed* catalog schema; it does not rewrite catalog data.
A migration is never inferred from CREATE TABLE IF NOT EXISTS or an unknown DB.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from audit_database import DEFAULT_DB, inspect_database

# Independently verified by the main-branch SQLite audit in Actions run 44235409998
# (26 tables, 10 indexes, 1 view, foreign_key_errors=0, user_version=0).
APPROVED_V0_SCHEMA = "21fdf1d9dbcb2262ffdbbb77b7120efcc622b70835a6cfbaaa1993bbcfca0cd0"
CURRENT_VERSION = 1
MIGRATION_ID = "0001-baseline-existing-catalog"
MIGRATION_DDL = """
CREATE TABLE schema_migrations (
  version INTEGER PRIMARY KEY,
  migration_id TEXT NOT NULL UNIQUE,
  script_sha256 TEXT NOT NULL,
  pre_schema_sha256 TEXT NOT NULL,
  post_schema_sha256 TEXT NOT NULL,
  applied_at TEXT NOT NULL
)
""".strip()
MIGRATION_SHA256 = hashlib.sha256(MIGRATION_DDL.encode("utf-8")).hexdigest()


class MigrationError(RuntimeError):
    """Unknown schema, invalid version or unsafe migration precondition."""


def fingerprint(conn: sqlite3.Connection) -> str:
    """Same canonical schema hash definition as scripts/audit_database.py."""
    objects = conn.execute(
        "SELECT type,name,sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
    ).fetchall()
    normalized = "\n".join(
        f"{row[0]}|{row[1]}|{row[2] or ''}" for row in objects
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def catalog_digest(conn: sqlite3.Connection) -> str:
    """Deterministic digest of ALL existing rows, excluding the migration ledger."""
    h = hashlib.sha256()
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' AND name!='schema_migrations' ORDER BY name"
    )]
    for name in tables:
        q = '"' + name.replace('"', '""') + '"'
        h.update((name + "\n").encode())
        cursor = conn.execute(f"SELECT * FROM {q} ORDER BY rowid")
        for chunk in iter(lambda: cursor.fetchmany(512), []):
            for row in chunk:
                h.update((json.dumps(list(row), ensure_ascii=False, default=str,
                                     separators=(",", ":")) + "\n").encode("utf-8"))
    return h.hexdigest()


def check_state(path: Path) -> dict:
    inspection = inspect_database(path, profile="full")
    if inspection["problems"]:
        raise MigrationError("database audit failed: " + "; ".join(inspection["problems"]))
    version = inspection["user_version"]
    sha = inspection["schema_sha256"]
    if version == 0:
        if sha != APPROVED_V0_SCHEMA or "schema_migrations" in inspection["tables"]:
            raise MigrationError(
                "Unrecognized version-0 schema; no migration attempted. "
                f"Observed {sha}; approved {APPROVED_V0_SCHEMA}"
            )
        return {"version": 0, "action": "apply_v1", "before_schema_sha256": sha}
    if version != CURRENT_VERSION:
        raise MigrationError(f"Unknown schema version {version} (supported: 0, 1)")
    if "schema_migrations" not in inspection["tables"]:
        raise MigrationError("user_version=1 without a schema_migrations table")
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT version,migration_id,script_sha256,pre_schema_sha256,"
            "post_schema_sha256 FROM schema_migrations"
        ).fetchall()
    finally:
        conn.close()
    if len(rows) != 1 or rows[0][:4] != (
        1, MIGRATION_ID, MIGRATION_SHA256, APPROVED_V0_SCHEMA
    ) or rows[0][4] != sha:
        raise MigrationError("Migration ledger or post-migration schema fingerprint differs")
    return {"version": 1, "action": "already_applied", "after_schema_sha256": sha}


def safe_snapshot(source: sqlite3.Connection, target: Path) -> None:
    """SQLite's backup API includes WAL frames; never use shutil.copyfile."""
    if target.exists():
        raise MigrationError(f"Backup target already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = sqlite3.connect(target)
    try:
        source.backup(backup)
        result = backup.execute("PRAGMA integrity_check").fetchone()[0]
        fks = backup.execute("PRAGMA foreign_key_check").fetchall()
        if result != "ok" or fks:
            raise MigrationError("Verified backup failed integrity / foreign-key checks")
    finally:
        backup.close()


def migrate(path: Path, backup_dir: Path) -> dict:
    first = check_state(path)
    if first["action"] == "already_applied":
        return {"action": "already_applied", "version": 1, "data_preserved": True}
    path = path.resolve()
    conn = sqlite3.connect(path, isolation_level=None, timeout=30)
    backup_path = backup_dir.resolve() / (
        f"{path.stem}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-"
        f"{uuid.uuid4().hex[:12]}.sqlite"
    )
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN IMMEDIATE")
        try:
            # Do not silently accept a different DB between the plan and the write.
            if conn.execute("PRAGMA user_version").fetchone()[0] != 0:
                raise MigrationError("Schema version changed during migration")
            if fingerprint(conn) != APPROVED_V0_SCHEMA:
                raise MigrationError("Schema changed between preflight and write")
            before_digest = catalog_digest(conn)
            # Backup under the write reservation, before the first DDL or row mutation.
            source = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
            try:
                safe_snapshot(source, backup_path)
            finally:
                source.close()
            conn.execute(MIGRATION_DDL)
            stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            conn.execute(
                "INSERT INTO schema_migrations(version,migration_id,script_sha256,"
                "pre_schema_sha256,post_schema_sha256,applied_at) VALUES(?,?,?,?,?,?)",
                (1, MIGRATION_ID, MIGRATION_SHA256, APPROVED_V0_SCHEMA, "", stamp)
            )
            after_schema = fingerprint(conn)
            conn.execute(
                "UPDATE schema_migrations SET post_schema_sha256=? WHERE version=1",
                (after_schema,)
            )
            conn.execute("PRAGMA user_version=1")
            if catalog_digest(conn) != before_digest:
                raise MigrationError("Catalog data changed during schema-only migration")
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise MigrationError("Post-migration SQLite integrity_check failed")
            if conn.execute("PRAGMA foreign_key_check").fetchall():
                raise MigrationError("Post-migration foreign_key_check failed")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()

    # Independently re-open after commit, not just the writer's own transaction.
    after = check_state(path)
    if after["action"] != "already_applied":
        raise MigrationError(f"Post-commit verification failed; verified backup: {backup_path}")
    return {
        "action": "applied", "version": 1, "data_preserved": True,
        "backup": str(backup_path),
        "before_schema_sha256": first["before_schema_sha256"],
        "after_schema_sha256": after["after_schema_sha256"],
        "catalog_rows_sha256": before_digest,
    }


def verify_copy(path: Path) -> dict:
    before = check_state(path)
    source = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        initial_digest = catalog_digest(source)
        with tempfile.TemporaryDirectory(prefix="catalog-migration-check-") as tmp:
            target = Path(tmp) / "catalog.sqlite"
            safe_snapshot(source, target)
            applied = migrate(target, Path(tmp) / "backups")
            repeat = migrate(target, Path(tmp) / "backups")
            target_conn = sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True)
            try:
                after_digest = catalog_digest(target_conn)
            finally:
                target_conn.close()
            if initial_digest != after_digest:
                raise MigrationError("Catalog digest changed in upgrade-copy verification")
            if repeat["action"] != "already_applied":
                raise MigrationError("Second migration run was not idempotent")
    finally:
        source.close()
    if check_state(path) != before:
        raise MigrationError("Source database schema changed during copy verification")
    return {
        "action": "verified_on_copy", "source_version": before["version"],
        "upgraded_version": 1, "data_preserved": True,
        "source_unmodified": True, "catalog_rows_sha256": initial_digest,
        "upgraded_schema_sha256": applied.get("after_schema_sha256",
                                            before.get("after_schema_sha256")),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--backup-dir", type=Path)
    commands = parser.add_mutually_exclusive_group()
    commands.add_argument("--apply", action="store_true", help="Backup, migrate and verify")
    commands.add_argument("--verify-copy", action="store_true",
                          help="Prove upgrade on a temporary copy without touching source")
    args = parser.parse_args(argv)
    try:
        if args.verify_copy:
            output = verify_copy(args.db)
        elif args.apply:
            output = migrate(args.db, args.backup_dir or args.db.parent / "backups")
        else:
            output = check_state(args.db)
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except (MigrationError, sqlite3.Error, OSError) as exc:
        print(json.dumps({"error": str(exc), "applied": False}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
