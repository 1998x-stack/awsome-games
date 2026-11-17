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


class BatchProbeContractTests(unittest.TestCase):
    """One hanging third-party page must never stall or fake the whole run."""

    def src(self):
        return (ROOT / "scripts/browser_batch_probe.py").read_text(encoding="utf-8")

    def test_each_entry_runs_in_a_killable_process_group(self):
        src = self.src()
        self.assertIn("start_new_session=True", src)
        self.assertIn("os.killpg", src)
        self.assertIn("SIGKILL", src)

    def test_timeouts_and_driver_errors_are_recorded_not_dropped(self):
        src = self.src()
        self.assertIn("TIMEOUT_ABORTED", src)
        self.assertIn("def timeout_result", src)
        # A missing report file must never be silently treated as a pass.
        self.assertNotIn('status = "BROWSER_LOAD_CHECKED"', src.split("def timeout_result")[1][:200])

    def test_single_mode_writes_the_report_the_parent_reads(self):
        src = self.src()
        single = src.split("if args.single:")[1].split("if not args.manifest")[0]
        self.assertIn("write_text", single, "the child must persist its report, not only print it")

    def test_isolation_is_installed_before_navigation(self):
        src = self.src()
        install = src.index("install_network_policy(ctx, result, port)")
        navigate = src.index('page.goto(f"{base}{HOST_PATH}')
        self.assertLess(install, navigate, "policy must be installed before any request")

    def test_aggregator_accepts_a_timeout_status(self):
        agg = (ROOT / "scripts/build_runtime_evidence.py").read_text(encoding="utf-8")
        self.assertIn("TIMEOUT_ABORTED", agg)
        self.assertIn('record["gameplay_verified"] = not record_problems', agg)


class SurveyClassificationTests(unittest.TestCase):
    """A failure must be classified, because each class needs a different decision."""

    def classify(self, report):
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        from consolidate_repo_survey import classify
        return classify(report)

    def base(self, **kw):
        report = {"status": "INCOMPLETE_OR_FAILED", "console_errors": [],
                  "blocked_requests": [], "blocked_websockets": [], "failed_requests": [],
                  "http_errors": [], "iframe_isolation": True, "frame_body_loaded": True,
                  "gameplay_verified": False}
        report.update(kw)
        return report

    def test_passes_and_input_responsive_are_not_failures(self):
        self.assertEqual(self.classify(self.base(status="BROWSER_LOAD_CHECKED")), "PASS")
        self.assertEqual(self.classify(self.base(status="INPUT_RESPONSIVE")), "PASS")

    def test_opaque_origin_cors_is_sandbox_incompatibility(self):
        report = self.base(console_errors=[
            "Access to script at 'http://127.0.0.1:1/x.js' from origin 'null' has been blocked "
            "by CORS policy: No 'Access-Control-Allow-Origin' header is present"])
        self.assertEqual(self.classify(report), "SANDBOX_OPAQUE_ORIGIN_BREAKS_OWN_SCRIPT")

    def test_external_cdn_is_a_dependency_not_a_defect(self):
        report = self.base(blocked_requests=["https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"])
        self.assertEqual(self.classify(report), "EXTERNAL_CDN_REQUIRED")

    def test_analytics_and_sensor_classes(self):
        self.assertEqual(
            self.classify(self.base(blocked_requests=["http://gc.zgo.at/count.js"])),
            "THIRD_PARTY_ANALYTICS_BLOCKED")
        self.assertEqual(
            self.classify(self.base(console_errors=["Permissions policy violation: accelerometer is not allowed"])),
            "OPTIONAL_DEVICE_SENSOR_DENIED")

    def test_driver_flake_is_not_reported_as_a_product_finding(self):
        report = self.base(console_errors=['driver error: TimeoutError: Locator.wait_for: Timeout 30000ms exceeded'])
        self.assertEqual(self.classify(report), "DRIVER_FLAKE_OR_TIMEOUT")

    def test_runtime_statuses_survive_recollection(self):
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        import collect_repositories as collector
        for status in ("sandbox_incompatible", "runtime_requires_network",
                       "runtime_third_party_beacon", "runtime_optional_sensor_denied",
                       "runtime_no_interaction", "runtime_driver_timeout", "runtime_needs_retest"):
            self.assertIn(status, collector.RUNTIME_REVIEWED_STATUSES, status)
