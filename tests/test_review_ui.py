"""Check review interface safety and website review queue integration."""
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


class ReviewInterfaceTests(unittest.TestCase):
    def test_safe_text_only_rendering(self):
        js=(ROOT/"site/assets/review.js").read_text(encoding="utf-8")
        self.assertIn("textContent",js)
        self.assertNotIn("innerHTML",js)
        self.assertIn("noopener noreferrer",js)
        self.assertIn("review-queue.json",js)

    def test_pages_rebuilds_review_data_from_database(self):
        build=(ROOT/"scripts/build_site.py").read_text(encoding="utf-8")
        self.assertIn("build_queue(conn)",build)
        self.assertIn('artifacts["data/review-queue.json"]',build)
        self.assertIn("preview_unapproved",build)
        self.assertIn('<script src="./assets/review.js" defer>',(ROOT/"site/review.html").read_text(encoding="utf-8"))


if __name__=="__main__":
    unittest.main()
