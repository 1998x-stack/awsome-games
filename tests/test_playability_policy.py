"""Expected failures proving inconsistent status aggregation and unsafe retraction.

These tests were committed before the fix; CI failure is intentional evidence.
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from db import connect, now
import apply_survey_to_catalog as applier
import mark_unvendored_entries as marker


class CrossWriterStatusPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "catalog.sqlite"
        self.conn = connect(self.db_path)
        stamp = now()
        self.conn.execute(
            "INSERT INTO projects(id,slug,title,created_at,updated_at) "
            "VALUES('p','p','Status policy fixture',?,?)", (stamp, stamp)
        )
        self.mapping_ids = {}
        for name, status in (
            ("a", "sandbox_incompatible"),
            ("b", "entrypoint_found"),
            ("c", "entrypoint_found"),
        ):
            directory = "example__" + name
            path = f"games/_repos/{directory}/index.html"
            self.conn.execute(
                "INSERT INTO repositories(full_name,owner,name,html_url,clone_url,"
                "clone_status,clone_path,commit_sha) VALUES(?,?,?,?,?,?,?,?)",
                (f"example/{name}", "example", name, f"https://github.com/example/{name}",
                 f"https://github.com/example/{name}.git", "cloned",
                 f"games/_repos/{directory}", "a" * 40)
            )
            rid = self.conn.execute(
                "SELECT id FROM repositories WHERE full_name=?", (f"example/{name}",)
            ).fetchone()[0]
            self.mapping_ids[name] = rid
            self.conn.execute(
                "INSERT INTO project_repositories("
                "project_id,repository_id,entry_path,game_path,playable_status)"
                " VALUES('p',?,'index.html',?,?)", (rid, path, status)
            )
            full = self.root / path
            full.parent.mkdir(parents=True)
            full.write_text("<!doctype html><title>example</title>")
        self.conn.commit()
        self.addCleanup(self.conn.close)

    def _project_status(self):
        return self.conn.execute("SELECT playable_status FROM projects WHERE id='p'").fetchone()[0]

    def _survey(self, kind, status):
        return {
            "captured_at": "2026-11-18T04:00:00+00:00",
            "isolation": {"network_policy": "none"},
            "entries": [{
                "key": "a", "entry": "_repos/example__a/index.html",
                "mode": "gameplay", "failure_class": kind, "status": status,
                "fingerprints": {"initial_pixels": "abcdef123"},
                "iframe_isolation": True, "console_errors": [],
                "blocked_functional_requests": [],
            }],
        }

    def test_survey_must_not_hide_another_usable_source(self):
        # Current collector uses positive-first; survey uses restrictive-first.
        survey = self._survey("NO_OBSERVABLE_RESPONSE", "NO_OBSERVABLE_RESPONSE")
        # Start A with a non-reviewed status to allow the new negative finding.
        self.conn.execute(
            "UPDATE project_repositories SET playable_status='needs_review' "
            "WHERE repository_id=?", (self.mapping_ids["a"],)
        )
        self.conn.commit()
        planned, _, _, _ = applier.plan(self.conn, survey, "survey.json", "a" * 64)
        self.assertEqual(len(planned), 1)
        applier.apply_plan(self.conn, planned)
        self.assertEqual(self._project_status(), "entrypoint_found")
        self.assertEqual(self.conn.execute(
            "SELECT playable_status FROM project_repositories WHERE repository_id=?",
            (self.mapping_ids["a"],)
        ).fetchone()[0], "runtime_no_interaction")

    def test_mark_unvendored_must_not_hide_another_usable_source(self):
        # If one mapped repository is unvendored, a second usable mapping still exists.
        removed_path = "games/_repos/example__b/index.html"
        with patch.object(marker, "connect", return_value=self.conn), \
             patch.object(marker, "ROOT", self.root), \
             patch.object(marker, "ignored_paths", return_value={removed_path}), \
             patch.object(sys, "argv", ["mark_unvendored_entries.py", "--apply"]):
            marker.main()
        # marker currently closes conn; read separately.
        conn = sqlite3.connect(self.db_path)
        try:
            self.assertEqual(conn.execute(
                "SELECT playable_status FROM projects WHERE id='p'"
            ).fetchone()[0], "entrypoint_found")
            self.assertEqual(conn.execute(
                "SELECT playable_status FROM project_repositories "
                "WHERE repository_id=?", (self.mapping_ids["b"],)
            ).fetchone()[0], "entrypoint_detected_not_vendored")
        finally:
            conn.close()

    def test_pass_retraction_never_directly_creates_publishable_status(self):
        survey = self._survey("PASS", "BROWSER_LOAD_CHECKED")
        planned, _, _, _ = applier.plan(self.conn, survey, "survey.json", "b" * 64)
        self.assertEqual(len(planned), 1)
        self.assertEqual(planned[0]["status"], "runtime_needs_retest")
        applier.apply_plan(self.conn, planned)
        self.assertEqual(self.conn.execute(
            "SELECT playable_status FROM project_repositories WHERE repository_id=?",
            (self.mapping_ids["a"],)
        ).fetchone()[0], "runtime_needs_retest")

    def test_inconsistent_pass_with_console_error_cannot_retract(self):
        survey = self._survey("PASS", "BROWSER_LOAD_CHECKED")
        survey["entries"][0]["console_errors"] = ["Uncaught SecurityError"]
        planned, _, refused, _ = applier.plan(self.conn, survey, "survey.json", "b" * 64)
        self.assertEqual(planned, [])
        self.assertEqual(len(refused), 1)

    def test_pass_only_evidence_is_accepted_for_review_not_for_publishing(self):
        survey = self._survey("PASS", "BROWSER_LOAD_CHECKED")
        accepted, reason = applier.survey_is_trustworthy(survey)
        self.assertTrue(accepted, reason)


if __name__ == "__main__":
    unittest.main()
