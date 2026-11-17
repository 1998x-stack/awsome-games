"""Hermetic headless-browser end-to-end check for cross-page evidence navigation.

Skipped when Playwright or a Chromium build is unavailable, so the default CI
matrix is unaffected. When it does run it proves the Review Queue -> Evidence Lab
link is a real, clickable anchor rather than a dead <span>, which is exactly the
regression that static tests alone cannot catch.
"""
import functools
import json
import re
import shutil
import socket
import tempfile
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - environment dependent
    sync_playwright = None
    PLAYWRIGHT_IMPORT_ERROR = exc

REVIEW_QUEUE = {
    "schema_version": 1,
    "warning": "fixture only",
    "stats": {
        "post_review_queue": 2,
        "work_review_queue": 1,
        "repository_review_queue": 1,
        "research_only_repository_candidates": 1,
        "alias_candidates": 1,
    },
    "repositories": [{
        "full_name": "fixture-owner/fixture-repo",
        "display_title": "Fixture Title",
        "queue_kind": "BROWSER_CANDIDATE_UNREVIEWED",
        "next_action": "fixture action",
        "tech": "HTML fixture",
        "review_status": "NEEDS_CODE_AND_RIGHTS_REVIEW",
    }],
    "posts": [{
        "post_key": "1234567890",
        "title": "Fixture post",
        "match_status": "UNRESOLVED",
        "entity_status": "PROVISIONAL",
        "creator": "fixture",
        "review_status": "UNREVIEWED",
        "next_action": "fixture action",
        "post_url": "https://example.invalid/status/1234567890",
    }, {
        "post_key": "0987654321",
        "title": "Hostile post",
        "match_status": "UNRESOLVED",
        "entity_status": "PROVISIONAL",
        "creator": "fixture",
        "review_status": "UNREVIEWED",
        "next_action": "fixture action",
        "post_url": "javascript:alert(1)",
    }],
    "works": [{
        "work_id": "FW-001",
        "title": "Fixture work",
        "repository_full_name": "fixture-owner/fixture-repo",
        "entry_status": "UNVERIFIED",
        "review_status": "UNREVIEWED",
        "next_action": "fixture action",
    }],
    "alias_candidates": [{
        "work_id": "FW-001",
        "catalog_title": "Fixture catalog",
        "source_title": "Fixture source",
        "repository_full_name": "fixture-owner/fixture-repo",
        "status": "CANDIDATE",
        "evidence_url": "https://example.invalid/evidence",
        "note": "fixture note",
    }],
}

RESEARCH = {
    "schema_version": 1,
    "captured_at": "fixture",
    "warning": "fixture only",
    "stats": {"source_records": 1, "posts": 1, "works": 1, "repositories": 1, "claims": 1},
    "works": [{
        "work_id": "FW-001", "title": "Fixture work", "entry_path": "", "entry_status": "UNVERIFIED",
        "prompt_status": "NOT_VERIFIED", "model_evidence": "COMMUNITY_CLAIM",
        "execution_verified": False, "review_status": "UNREVIEWED",
        "source_url": "https://example.invalid/evidence",
    }],
    "posts": [],
    "repositories": [{
        "full_name": "fixture-owner/fixture-repo",
        "display_title": "Fixture Title",
        "relation": "PRIMARY_LINK_SOURCE",
        "model_evidence": "MODEL_UNVERIFIED",
        "browser_hint": "yes",
        "tech": "HTML fixture",
        "license_state": "NOASSERTION",
        "review_level": "TREE_ONLY",
        "browser_status": "NOT_TESTED",
    }],
    "claims": [],
}


class _Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        return


@unittest.skipIf(sync_playwright is None, f"Playwright unavailable: {PLAYWRIGHT_IMPORT_ERROR}")
class SiteCrossNavigationE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        shutil.copytree(ROOT / "site", cls.root / "site", ignore=shutil.ignore_patterns("data", "games"))
        data = cls.root / "site" / "data"
        data.mkdir(parents=True, exist_ok=True)
        (data / "review-queue.json").write_text(json.dumps(REVIEW_QUEUE), encoding="utf-8")
        (data / "research.json").write_text(json.dumps(RESEARCH), encoding="utf-8")
        (data / "catalog.json").write_text(
            json.dumps({"summary": {}, "projects": []}), encoding="utf-8")
        handler = functools.partial(_Handler, directory=str(cls.root / "site"))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(headless=True)
        except Exception as exc:  # pragma: no cover - environment dependent
            cls.playwright.stop()
            cls.server.shutdown()
            cls.server.server_close()
            raise unittest.SkipTest(f"Chromium unavailable: {exc}")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.tmp.cleanup()

    def page_url(self, path):
        return f"http://127.0.0.1:{self.port}/{path}"

    def test_review_queue_links_into_evidence_lab(self):
        context = self.browser.new_context(permissions=[], service_workers="block")
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        try:
            page.goto(self.page_url("review.html"), wait_until="networkidle")
            footer = page.locator("#queue-results .lab-card-foot").first
            anchors = footer.locator("a")
            self.assertEqual(anchors.count(), 2, footer.inner_html())
            href = anchors.nth(1).get_attribute("href")
            self.assertRegex(href, r"^\./research\.html\?kind=repositories&id=")
            # Follow the link the way a user would and confirm the deep link opens.
            page.goto(self.page_url(href.lstrip("./")), wait_until="networkidle")
            self.assertTrue(page.locator("#lab-detail").evaluate("d => d.open"))
            self.assertEqual(errors, [])
        finally:
            context.close()

    def test_all_surfaces_load_without_page_errors(self):
        context = self.browser.new_context(permissions=[], service_workers="block")
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        try:
            for name in ("index.html", "research.html", "review.html"):
                page.goto(self.page_url(name), wait_until="networkidle")
                self.assertNotIn("加载失败", page.locator("body").inner_text(), name)
            self.assertEqual(errors, [])
        finally:
            context.close()

    def test_untrusted_post_url_is_not_rendered_as_anchor(self):
        """Behavioural check on the shipped resolver: hostile post_url degrades to text."""
        context = self.browser.new_context(permissions=[], service_workers="block")
        page = context.new_page()
        try:
            page.goto(self.page_url("review.html"), wait_until="networkidle")
            page.click('[data-queue="posts"]')
            cards = page.locator("#queue-results .lab-card")
            safe_footer = cards.nth(0).locator(".lab-card-foot")
            hostile_footer = cards.nth(1).locator(".lab-card-foot")
            self.assertEqual(safe_footer.locator("a").count(), 2, safe_footer.inner_html())
            # The hostile entry keeps only the internal Evidence Lab anchor.
            self.assertEqual(hostile_footer.locator("a").count(), 1, hostile_footer.inner_html())
            self.assertEqual(
                hostile_footer.locator("span").first.text_content(), "原始证据 ↗")
        finally:
            context.close()


if __name__ == "__main__":
    unittest.main()
