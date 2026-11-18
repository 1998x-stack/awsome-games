"""Regression tests for the read-only database auditor."""
from __future__ import annotations

import hashlib
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from audit_database import CORE_TABLES, RESEARCH_TABLES, inspect_database


class DatabaseAuditTests(unittest.TestCase):
    def _fixture(self, path: Path, *, research: bool = True):
        conn = sqlite3.connect(path)
        for table in CORE_TABLES + (RESEARCH_TABLES if research else ()):
            # Minimal fixture. Actual project DDL is checked by CI.
            if table == "projects":
                sql = "id TEXT PRIMARY KEY, slug TEXT, title TEXT, playable_status TEXT"
            elif table == "repositories":
                sql = "id INTEGER PRIMARY KEY, full_name TEXT, clone_status TEXT, commit_sha TEXT"
            elif table == "project_repositories":
                sql = ("project_id TEXT, repository_id INTEGER, entry_path TEXT, "
                       "game_path TEXT, playable_status TEXT")
            elif table == "project_evidence":
                sql = "project_id TEXT, evidence_source_id INTEGER, evidence_type TEXT"
            elif table == "research_works":
                sql = "work_id TEXT, repository_full_name TEXT, entry_path TEXT"
            elif table == "research_runtime_evidence":
                sql = ("evidence_id TEXT, work_id TEXT, repo_commit_sha TEXT, "
                       "entry_sha256 TEXT, report_status TEXT")
            else:
                sql = "id INTEGER PRIMARY KEY"
            conn.execute(f'CREATE TABLE "{table}" ({sql})')
        conn.commit()
        conn.close()

    def test_full_profile_is_read_only_and_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalog.sqlite"
            self._fixture(path)
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            first = inspect_database(path)
            second = inspect_database(path)
            self.assertEqual(first["problems"], [])
            self.assertEqual(first["schema_sha256"], second["schema_sha256"])
            self.assertEqual(first["tables"], second["tables"])
            self.assertEqual(before, hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertFalse(Path(str(path) + "-wal").exists())
            self.assertEqual(first["object_counts"]["table"], 25)

    def test_missing_database_is_not_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "not-created.sqlite"
            report = inspect_database(path)
            self.assertFalse(path.exists())
            self.assertFalse(report["database_exists"])
            self.assertIn("Database does not exist", report["problems"][0])

    def test_missing_research_tables_only_fail_full_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalog.sqlite"
            self._fixture(path, research=False)
            self.assertEqual(inspect_database(path, "core")["problems"], [])
            full = inspect_database(path, "full")
            self.assertIn("Missing required table: research_works", full["problems"])

    def test_detects_missing_essential_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalog.sqlite"
            self._fixture(path)
            conn = sqlite3.connect(path)
            conn.execute("ALTER TABLE projects DROP COLUMN playable_status")
            conn.close()
            report = inspect_database(path)
            self.assertIn("Missing required column: projects.playable_status", report["problems"])

    def test_detects_entrypoint_without_game_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalog.sqlite"
            self._fixture(path)
            conn = sqlite3.connect(path)
            conn.execute("INSERT INTO project_repositories VALUES ('x', 1, 'index.html', '', 'entrypoint_found')")
            conn.commit()
            conn.close()
            report = inspect_database(path)
            self.assertEqual(report["entrypoint_found_without_game_path"], 1)
            self.assertTrue(any("without game_path" in e for e in report["problems"]))

    def test_rejects_corrupt_database_and_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalog.sqlite"
            path.write_bytes(b"not a sqlite database")
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "audit_database.py"),
                 "--db", str(path)], capture_output=True, text=True
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("Database inspection failed", result.stdout)


if __name__ == "__main__":
    unittest.main()
