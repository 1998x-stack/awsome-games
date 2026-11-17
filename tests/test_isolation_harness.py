"""The isolation harness is the M3 safety boundary; keep its guarantees pinned.

These are contract tests over the container recipe and wrapper script. If someone
weakens the flags, adds a mutable mount or loses the read-only staged root, this
fails instead of silently shipping a weaker claim.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "scripts/isolation/Dockerfile.smoke"
WRAPPER = ROOT / "scripts/isolation/run_isolated_smoke.sh"


class IsolationHarnessContractTests(unittest.TestCase):
    def setUp(self):
        self.dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        self.wrapper = WRAPPER.read_text(encoding="utf-8")

    def test_container_flags_deny_network_privilege_and_writable_root(self):
        for flag in ("--network none", "--read-only", "--cap-drop ALL",
                     "--security-opt no-new-privileges", "--pids-limit",
                     "--memory", "--cpus", "--user 65534:65534"):
            self.assertIn(flag, self.wrapper, flag)

    def test_staged_artifact_is_mounted_read_only(self):
        self.assertIn('"$ROOT_ABS:/staged:ro"', self.wrapper)
        # Reports go to a named volume: macOS bind mounts ignore the container uid.
        self.assertIn('"$VOLUME:/reports"', self.wrapper)
        self.assertIn("docker volume create", self.wrapper)

    def test_wrapper_rejects_path_escapes_and_verifies_the_mount(self):
        self.assertIn("*..*", self.wrapper)
        self.assertIn("container cannot see", self.wrapper)

    def test_browser_is_pinned_and_installed_at_build_time(self):
        self.assertRegex(self.dockerfile, r"ARG PLAYWRIGHT_VERSION=[\d.]+")
        self.assertIn('pip install "playwright==${PLAYWRIGHT_VERSION}"', self.dockerfile)
        self.assertIn("playwright install --with-deps chromium", self.dockerfile)

    def test_no_credentials_or_repo_sources_are_baked_into_the_image(self):
        for leaked in (".env", "GITHUB_TOKEN", "id_rsa", "credentials.json", "data/catalog.sqlite"):
            self.assertNotIn(leaked, self.dockerfile, leaked)

    def test_docs_require_os_level_isolation(self):
        doc = (ROOT / "docs/BROWSER_SMOKE.md").read_text(encoding="utf-8")
        self.assertIn("--network none", doc)
        self.assertIn("run_isolated_smoke.sh", doc)
        # The doc must state that third-party games remain unverified.
        self.assertRegex(doc, r"第三方游戏仍.*NOT_TESTED")


if __name__ == "__main__":
    unittest.main()


class GameplayHarnessContractTests(unittest.TestCase):
    """The interaction probe and the dependency policy are safety-relevant contracts."""

    def test_wrapper_supports_both_modes(self):
        w = WRAPPER.read_text(encoding="utf-8")
        self.assertIn("--mode", w)
        self.assertIn("browser_gameplay_probe.py", w)
        self.assertIn("browser_smoke.py", w)

    def test_image_contains_the_interaction_probe(self):
        d = DOCKERFILE.read_text(encoding="utf-8")
        self.assertIn("browser_gameplay_probe.py", d)

    def test_cosmetic_dependencies_are_stubbed_not_allowed_through(self):
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        from browser_smoke import is_cosmetic_request
        self.assertTrue(is_cosmetic_request("https://fonts.googleapis.com/css2?family=Anton"))
        self.assertTrue(is_cosmetic_request("https://fonts.gstatic.com/s/anton/v1/x.woff2"))
        self.assertTrue(is_cosmetic_request("https://example.com/favicon.ico"))
        for functional in ("https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js",
                           "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js",
                           "https://example.com/api/state", "wss://example.com/socket"):
            self.assertFalse(is_cosmetic_request(functional), functional)

    def test_gameplay_probe_refuses_to_pass_without_an_input_driven_change(self):
        src = (ROOT / "scripts/browser_gameplay_probe.py").read_text(encoding="utf-8")
        self.assertIn('"INPUT_RESPONSIVE"', src)
        self.assertIn('"NO_OBSERVABLE_RESPONSE"', src)
        self.assertIn("input_changed_pixels", src)
        self.assertIn("gameplay_verified", src)
        agg = (ROOT / "scripts/build_runtime_evidence.py").read_text(encoding="utf-8")
        self.assertIn("verification_rejected", agg)
        self.assertIn("record[\"gameplay_verified\"] = not record_problems", agg)
