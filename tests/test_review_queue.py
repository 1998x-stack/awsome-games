"""Review queues must keep provisional entities separate from editorial approvals."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from db import connect, seed_database, SEED_PATH
from research_pipeline import ingest
from review_queue import build_queue, classify_candidate, aliases


class ReviewQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = connect(Path(cls.tmp.name) / "queue.sqlite")
        seed_database(cls.db, SEED_PATH)
        ingest(cls.db)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls.tmp.cleanup()

    def test_all_candidates_are_queued_without_auto_promotion(self):
        result = build_queue(self.db)
        self.assertEqual(result["stats"]["repository_review_queue"], 83)
        self.assertEqual(result["stats"]["research_only_repository_candidates"], 32)
        self.assertEqual(result["stats"]["work_review_queue"], 64)
        self.assertEqual(result["stats"]["post_review_queue"], 907)
        self.assertGreaterEqual(sum(x["match_status"] == "UNRESOLVED" for x in result["posts"]), 900)
        self.assertTrue(all(x["review_status"] != "APPROVED" for x in result["posts"]))

    def test_alias_requires_same_repo_and_remains_provisional(self):
        result = aliases(self.db)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["work_id"], "F52-W015")
        self.assertEqual(result[0]["status"], "CANDIDATE")
        with tempfile.TemporaryDirectory() as directory:
            f = Path(directory) / "bad.json"
            bad = {"schema_version":1,"aliases":[dict(result[0],repository_full_name="other/other")]}
            f.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(ValueError):
                aliases(self.db, f)

    def test_mirror_is_not_classified_as_original(self):
        route, _ = classify_candidate({"relation":"COMMUNITY_MIRROR","browser_hint":"yes"})
        self.assertEqual(route, "MIRROR_NEEDS_ATTRIBUTION")
        route, _ = classify_candidate({"relation":"PULL_REQUEST_NOT_DIRECT_WORK_REPO"})
        self.assertEqual(route, "PR_OR_COMPONENT")


if __name__ == "__main__":
    unittest.main()
