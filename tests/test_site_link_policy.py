"""Cross-page navigation and URL-safety policy for the three site surfaces.

These are source-level checks so they run in CI without a browser. The real
headless-browser proof lives in test_site_e2e.py and is skipped when Playwright
is unavailable.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS_FILES = ("app.js", "research.js", "review.js")


class SiteLinkPolicyTests(unittest.TestCase):
    def source(self, name):
        return (ROOT / "site/assets" / name).read_text(encoding="utf-8")

    def test_every_surface_rejects_embedded_credentials_and_bad_schemes(self):
        for name in JS_FILES:
            js = self.source(name)
            self.assertIn("document.baseURI", js, name)
            self.assertIn("username", js, name)
            self.assertIn("password", js, name)
            # Only http/https may survive the protocol allow-list.
            self.assertRegex(js, r"['\"](?:http|https):['\"]", name)

    def test_review_cross_links_stay_relative_for_project_pages_subpaths(self):
        """GitHub project Pages serve at /<repo>/, so root-absolute links would 404."""
        js = self.source("review.js")
        self.assertNotIn("return url.pathname+url.search", js)
        self.assertIn("location.pathname.replace", js)
        self.assertIn("'./'+", js)
        # The Evidence Lab deep link must still be constructed for every queue kind.
        for kind in ("repositories", "posts", "works"):
            self.assertIn(f"'./research.html?kind={kind}", js)

    def test_internal_links_do_not_force_a_new_tab(self):
        """A same-origin audit-trail hop must stay in the current tab."""
        for name in ("review.js", "research.js"):
            js = self.source(name)
            self.assertRegex(
                js, r"external=new URL\(href,document\.baseURI\)\.origin!==location\.origin", name)
            self.assertRegex(js, r"if\(external\)\{a\.target='_blank'", name)
            # No unconditional new-tab assignment may remain.
            self.assertNotRegex(js, r";a\.target='_blank';", name)

    def test_no_hardcoded_research_counts_in_static_markup(self):
        """Counts must come from the built projection, never from frozen prose."""
        for name in ("index.html", "research.html", "review.html"):
            html = (ROOT / "site" / name).read_text(encoding="utf-8")
            body = html.split("</head>", 1)[1]
            stale = re.findall(r"(\d{2,})\s*(?:个|条)\s*(?:仓库|作品|原帖|记录|来源)", body)
            self.assertEqual(stale, [], f"{name} hardcodes research counts: {stale}")


if __name__ == "__main__":
    unittest.main()
