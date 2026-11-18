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
        self.assertIn("input_attribution", src)
        self.assertIn("NO_OBSERVABLE_RESPONSE", src)
        self.assertIn("input_changed_pixels", src)
        self.assertIn("gameplay_verified", src)
        # The probe may never raise the gameplay claim itself, and its verdict
        # vocabulary has to carry the not-attributable outcome.
        self.assertNotIn('result["gameplay_verified"] = True', src)
        self.assertIn("NOT_ATTRIBUTABLE", src)
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


class SurveyHonestyTests(unittest.TestCase):
    """The survey artifact must never turn input responsiveness into a gameplay claim.

    `gameplay_verified` is a fail-closed claim owned by build_runtime_evidence.py.
    A probe that merely observed a pixel or DOM change after synthetic input must
    not be able to raise it, and a legacy report that already overclaims must not
    leak its claim into the aggregated artifact.
    """

    def _run(self, tmp, reports):
        import json
        import subprocess
        import sys
        d = Path(tmp)
        (d / "reports").mkdir()
        # A report is attributed to an entry by its `entry` path, so the fixture
        # must carry the same value the manifest uses.
        for name, report in reports.items():
            (d / "reports" / f"{name}.json").write_text(
                json.dumps({"entry": f"{name}.html", **report}), encoding="utf-8")
        (d / "manifest.json").write_text(json.dumps(
            [{"key": k, "entry": f"{k}.html", "mode": "gameplay"} for k in reports]),
            encoding="utf-8")
        out = d / "survey.json"
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts/consolidate_repo_survey.py"),
             "--manifest", str(d / "manifest.json"), "--reports", str(d / "reports"),
             "--out", str(out)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
        return json.loads(out.read_text(encoding="utf-8"))

    def test_input_responsive_never_becomes_a_gameplay_claim(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            data = self._run(tmp, {
                # A report that overclaims, as the older probe format did.
                "responds": {"status": "INPUT_RESPONSIVE", "gameplay_verified": True,
                             "console_errors": [], "blocked_requests": []},
                "loads": {"status": "BROWSER_LOAD_CHECKED", "gameplay_verified": False,
                          "console_errors": [], "blocked_requests": []}})
        self.assertEqual(data["counts"]["input_responsive"], 1)
        self.assertEqual(data["counts"]["gameplay_verified"], 0)
        self.assertFalse(any(e["gameplay_verified"] for e in data["entries"]))
        self.assertIn("gameplay_verified is always 0", data["evidence_scope"])
        self.assertTrue(next(e for e in data["entries"] if e["key"] == "responds")["input_responsive"])

    def test_entry_without_a_report_is_untested_not_counted_as_a_pass(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "reports").mkdir()
            (d / "reports" / "measured.json").write_text(json.dumps(
                {"entry": "measured.html", "status": "BROWSER_LOAD_CHECKED",
                 "console_errors": [], "blocked_requests": []}), encoding="utf-8")
            (d / "manifest.json").write_text(json.dumps([
                {"key": "measured", "entry": "measured.html", "mode": "load"},
                {"key": "never-ran", "entry": "never-ran.html", "mode": "load"}]),
                encoding="utf-8")
            out = d / "survey.json"
            import subprocess
            import sys
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts/consolidate_repo_survey.py"),
                 "--manifest", str(d / "manifest.json"), "--reports", str(d / "reports"),
                 "--out", str(out)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
            data = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(data["counts"]["measured"], 1)
        self.assertEqual(data["counts"]["untested"], 1)
        self.assertNotIn("never-ran", [e["key"] for e in data["entries"]])
        self.assertEqual([u["key"] for u in data["untested"]], ["never-ran"])


class InputAttributionTests(unittest.TestCase):
    """A difference after input only counts when the same channel was stable before.

    This rule exists because 10 of 11 entries that the first survey called
    input-responsive were already changing during the idle baseline, and 7 of them had
    a byte-identical DOM from load to finish. Reporting those as input response
    inflated the headline number from 4 to 11.
    """

    def _attrib(self, **kw):
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        from input_attribution import input_attribution
        return input_attribution(kw)

    def test_pixels_changed_on_a_stable_page_are_attributable(self):
        self.assertEqual(self._attrib(input_changed_pixels=True), "INPUT_RESPONSIVE")

    def test_pixels_changed_while_the_page_repaints_are_not_attributable(self):
        self.assertEqual(
            self._attrib(input_changed_pixels=True, idle_output_changed=True),
            "INPUT_RESPONSE_NOT_ATTRIBUTABLE")

    def test_dom_changed_on_a_stable_dom_is_attributable_even_if_pixels_animate(self):
        # The canvas repaints every frame, but the DOM census is identical from load to
        # the end of the idle window, so the DOM difference can only come from input.
        self.assertEqual(
            self._attrib(input_changed_dom=True, idle_output_changed=True), "INPUT_RESPONSIVE")

    def test_dom_changed_while_the_dom_is_also_animating_is_not_attributable(self):
        self.assertEqual(
            self._attrib(input_changed_dom=True, idle_dom_changed=True),
            "INPUT_RESPONSE_NOT_ATTRIBUTABLE")

    def test_a_page_that_animates_but_ignores_input_is_not_a_pass(self):
        self.assertEqual(self._attrib(idle_output_changed=True), "INPUT_RESPONSE_NOT_ATTRIBUTABLE")

    def test_nothing_moved_is_no_observable_response(self):
        self.assertEqual(self._attrib(), "NO_OBSERVABLE_RESPONSE")

    def test_re_derivation_never_upgrades_a_failure_or_a_load_only_result(self):
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        from consolidate_repo_survey import effective_status
        # A load-only entry never runs an input phase, so its status must not be re-derived.
        self.assertEqual(effective_status({"status": "BROWSER_LOAD_CHECKED"}, "load"),
                         "BROWSER_LOAD_CHECKED")
        # A hard failure stays a hard failure even if raw flags look like a response.
        self.assertEqual(effective_status(
            {"status": "INCOMPLETE_OR_FAILED", "input_changed_pixels": True}, "gameplay"),
            "INCOMPLETE_OR_FAILED")
        self.assertEqual(effective_status({"status": "TIMEOUT_ABORTED"}, "gameplay"),
                         "TIMEOUT_ABORTED")

    def test_re_derivation_downgrades_a_legacy_false_positive(self):
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        from consolidate_repo_survey import effective_status
        legacy = {"status": "INPUT_RESPONSIVE", "input_changed_pixels": True,
                  "input_changed_dom": False, "idle_output_changed": True}
        self.assertEqual(effective_status(legacy, "gameplay"), "INPUT_RESPONSE_NOT_ATTRIBUTABLE")
        self.assertEqual(effective_status(
            {"status": "INPUT_RESPONSIVE", "input_changed_dom": True, "idle_dom_changed": False},
            "gameplay"), "INPUT_RESPONSIVE")

    def test_both_probes_and_the_aggregator_use_this_one_rule(self):
        for name in ("browser_gameplay_probe.py", "browser_batch_probe.py",
                     "consolidate_repo_survey.py"):
            src = (ROOT / "scripts" / name).read_text(encoding="utf-8")
            self.assertIn("input_attribution", src, name)


class ClassificationCoverageTests(unittest.TestCase):
    """Root causes found in real survey data, pinned so they stay classified.

    Each of these was added after a real entry landed in the wrong bucket, which
    matters because 'the artifact failed' is not actionable while 'it needs a CDN' and
    'our container ran out of memory' call for completely different decisions.
    """

    def _classify(self, **kw):
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        from consolidate_repo_survey import classify
        report = {"status": "INCOMPLETE_OR_FAILED", "console_errors": [], "blocked_requests": [],
                  "blocked_websockets": [], "failed_requests": [], "http_errors": [],
                  "iframe_isolation": True, "frame_body_loaded": True}
        report.update(kw)
        return classify(report)

    def test_a_same_origin_only_api_denied_by_the_sandbox_is_sandbox_incompatibility(self):
        # circular-tic-tac-toe: the page reads navigator.serviceWorker, and the required
        # sandbox gives it an opaque origin. Same root cause as localStorage.
        self.assertEqual(
            self._classify(console_errors=["Failed to read the 'serviceWorker' property from "
                                           "'Navigator': Service worker is disabled because the "
                                           "context is sandboxed and lacks the 'allow-same-origin' flag."]),
            "SANDBOX_OPAQUE_ORIGIN_BREAKS_OWN_SCRIPT")

    def test_a_crashed_renderer_is_an_environment_limit_not_a_page_defect(self):
        self.assertEqual(
            self._classify(console_errors=["driver error: TargetClosedError: Page.wait_for_timeout: Page crashed"]),
            "RENDERER_CRASHED_ENVIRONMENT_LIMIT")
        self.assertEqual(
            self._classify(console_errors=["driver error: Error: Locator.bounding_box: Target crashed"]),
            "RENDERER_CRASHED_ENVIRONMENT_LIMIT")

    def test_a_locator_timeout_stays_a_driver_problem(self):
        self.assertEqual(
            self._classify(console_errors=["driver error: TimeoutError: Locator.wait_for: Timeout 30000ms exceeded."]),
            "DRIVER_FLAKE_OR_TIMEOUT")

    def test_a_blocking_page_is_its_own_class(self):
        self.assertEqual(self._classify(status="TIMEOUT_ABORTED"), "PAGE_BLOCKED_DRIVER")

    def test_neither_a_crash_nor_a_driver_timeout_produces_a_catalog_status(self):
        # They are statements about our environment, not conclusions about the artifact,
        # so they must not be written to the authoritative catalog.
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        import apply_survey_to_catalog as applier
        for cls in ("RENDERER_CRASHED_ENVIRONMENT_LIMIT", "DRIVER_FLAKE_OR_TIMEOUT", "OTHER", "PASS"):
            self.assertNotIn(cls, applier.CLASS_TO_STATUS, cls)
