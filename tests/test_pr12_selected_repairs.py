"""Independent red tests for minimal, externally-supported repairs from PR #12.

Provenance for the entrypoint correction: upstream README pinned to
447d0b5a7947fed9f2916c151c5aaf41522a96b1 identifies Aquila with rome/
and Dawnward with the repository-root index.html; both files exist in its Git tree.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import db
import export_seed
from research_pipeline import REVIEWED_ENTRIES


class EvidenceSupportedPR12SubsetTests(unittest.TestCase):
    def test_aquila_and_dawnward_are_not_swapped(self):
        repo = "gavinlorio/fable-5.2-random-game"
        self.assertEqual(REVIEWED_ENTRIES[(repo, "aquila")], "rome/index.html")
        self.assertEqual(REVIEWED_ENTRIES[(repo, "dawnward")], "index.html")

    def test_two_real_evidence_types_on_one_url_survive_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            seed = base / "seed.jsonl"
            url = "https://github.com/example/actual-source"
            row = {
                "project_id": "fab_multiple_evidence",
                "title": "Provenance fixture",
                "sources": [url],
                "evidence_by_source": {url: [
                    {"evidence_type": "repository_documentation", "confidence": "medium"},
                    {"evidence_type": "author_original_statement", "confidence": "high"},
                    {"evidence_type": "sqlite_snapshot_reconstruction", "confidence": "low"},
                ]},
            }
            seed.write_text(json.dumps(row) + "\n", encoding="utf-8")
            before = db.connect(base / "before.sqlite")
            try:
                db.seed_database(before, seed)
                original = sorted(
                    tuple(r) for r in before.execute(
                        "SELECT evidence_type,confidence FROM project_evidence"
                    )
                )
                self.assertEqual(original, [
                    ("author_original_statement", "high"),
                    ("repository_documentation", "medium"),
                ])
            finally:
                before.close()
            reconstructed = base / "exported.jsonl"
            export_seed.export_seed(base / "before.sqlite", reconstructed)
            exported = json.loads(reconstructed.read_text(encoding="utf-8"))
            self.assertEqual(len(exported["evidence_by_source"][url]), 2)
            after = db.connect(base / "after.sqlite")
            try:
                db.seed_database(after, reconstructed)
                actual = sorted(
                    tuple(r) for r in after.execute(
                        "SELECT evidence_type,confidence FROM project_evidence"
                    )
                )
                self.assertEqual(actual, original)
                db.seed_database(after, reconstructed)
                self.assertEqual(after.execute(
                    "SELECT COUNT(*) FROM project_evidence"
                ).fetchone()[0], 2)
            finally:
                after.close()

    def test_category_only_change_updates_timestamp_exactly_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            path = base / "seed.jsonl"
            row = {"project_id": "fab_category_test", "title": "Test",
                   "category": "puzzle", "model": "unknown", "sources": []}
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            conn = db.connect(base / "catalog.sqlite")
            try:
                with patch.object(db, "now", return_value="2026-01-01T00:00:00+00:00"):
                    db.seed_database(conn, path)
                first = conn.execute(
                    "SELECT updated_at,content_type FROM projects WHERE id=?",
                    ("fab_category_test",)
                ).fetchone()
                self.assertEqual(first["content_type"], "game")
                row["category"] = "racing"
                path.write_text(json.dumps(row) + "\n", encoding="utf-8")
                with patch.object(db, "now", return_value="2026-02-02T00:00:00+00:00"):
                    db.seed_database(conn, path)
                second = conn.execute(
                    "SELECT updated_at,content_type FROM projects WHERE id=?",
                    ("fab_category_test",)
                ).fetchone()
                self.assertEqual(second["content_type"], first["content_type"])
                self.assertEqual(second["updated_at"], "2026-02-02T00:00:00+00:00")
                with patch.object(db, "now", return_value="2026-03-03T00:00:00+00:00"):
                    db.seed_database(conn, path)
                self.assertEqual(conn.execute(
                    "SELECT updated_at FROM projects WHERE id=?",
                    ("fab_category_test",)
                ).fetchone()[0], second["updated_at"])
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
