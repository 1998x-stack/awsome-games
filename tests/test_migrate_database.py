"""Evidence-based migration tests on a WAL-safe copy of the actual catalog."""
from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from audit_database import DEFAULT_DB
from migrate_database import (
    APPROVED_V0_SCHEMA, MIGRATION_SHA256, MigrationError,
    catalog_digest, check_state, migrate, safe_snapshot, verify_copy,
)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "working.sqlite"
        self.backups = Path(self.tmp.name) / "backups"
        source = sqlite3.connect(DEFAULT_DB.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            safe_snapshot(source, self.path)
        finally:
            source.close()

    def test_baseline_is_a_genuinely_observed_schema(self):
        report = check_state(self.path)
        self.assertEqual(report["before_schema_sha256"], APPROVED_V0_SCHEMA)
        self.assertEqual(report["version"], 0)
        self.assertFalse(self.backups.exists())

    def test_migration_creates_verified_backup_and_preserves_every_existing_row(self):
        conn = sqlite3.connect(self.path)
        try:
            original = catalog_digest(conn)
        finally:
            conn.close()
        result = migrate(self.path, self.backups)
        self.assertEqual(result["action"], "applied")
        self.assertTrue(result["data_preserved"])
        self.assertTrue(Path(result["backup"]).exists())
        self.assertEqual(check_state(self.path)["version"], 1)
        old_backup = sqlite3.connect(Path(result["backup"]).resolve().as_uri() + "?mode=ro", uri=True)
        new_db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            self.assertEqual(catalog_digest(old_backup), original)
            self.assertEqual(catalog_digest(new_db), original)
            self.assertEqual(new_db.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(new_db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            row = new_db.execute("SELECT script_sha256 FROM schema_migrations").fetchone()
            self.assertEqual(row[0], MIGRATION_SHA256)
        finally:
            old_backup.close()
            new_db.close()

    def test_idempotent_reentry_has_no_new_backup(self):
        migrate(self.path, self.backups)
        before = list(self.backups.iterdir())
        self.assertEqual(migrate(self.path, self.backups)["action"], "already_applied")
        self.assertEqual(list(self.backups.iterdir()), before)

    def test_copy_verification_keeps_original_at_v0(self):
        before = check_state(self.path)
        verified = verify_copy(self.path)
        self.assertEqual(verified["action"], "verified_on_copy")
        self.assertTrue(verified["data_preserved"])
        self.assertTrue(verified["source_unmodified"])
        self.assertEqual(check_state(self.path), before)

    def test_fail_closed_on_unknown_schema(self):
        conn = sqlite3.connect(self.path)
        conn.execute("CREATE TABLE unauthorized_new_table (id TEXT)")
        conn.commit()
        conn.close()
        with self.assertRaisesRegex(MigrationError, "Unrecognized version-0 schema"):
            migrate(self.path, self.backups)
        self.assertFalse(self.backups.exists())

    def test_fail_closed_on_future_user_version(self):
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA user_version=99")
        conn.close()
        with self.assertRaisesRegex(MigrationError, "Unknown schema version"):
            migrate(self.path, self.backups)
        self.assertFalse(self.backups.exists())

    def test_fail_closed_on_tampered_migration_ledger(self):
        migrate(self.path, self.backups)
        conn = sqlite3.connect(self.path)
        conn.execute("UPDATE schema_migrations SET script_sha256='fake'")
        conn.commit()
        conn.close()
        with self.assertRaisesRegex(MigrationError, "Migration ledger"):
            check_state(self.path)

    def test_missing_database_is_never_created(self):
        target = Path(self.tmp.name) / "absent.sqlite"
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "migrate_database.py"),
             "--db", str(target), "--apply"], capture_output=True, text=True
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
