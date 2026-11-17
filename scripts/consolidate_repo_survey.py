#!/usr/bin/env python3
"""Consolidate per-entry isolation reports into one survey of many repositories.

Takes a manifest of {key, entry, mode} plus a directory of per-entry reports
produced by scripts/browser_batch_probe.py, classifies each non-pass by root
cause, and writes one versioned file grouped by repository.

The classification exists because "the artifact failed" is not actionable:
"it needs a CDN", "it ships analytics", "the required sandbox gives it an opaque
origin so its own ES module fails CORS", and "it never reacted to input" call for
completely different decisions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ANALYTICS_HOSTS = ("gc.zgo.at", "google-analytics.com", "googletagmanager.com",
                   "plausible.io", "umami", "matomo", "posthog.com", "sentry.io")
CDN_HINTS = ("cdnjs.cloudflare.com", "cdn.jsdelivr.net", "unpkg.com",
             "esm.sh", "skypack.dev", "jsdelivr.net")


def classify(report: dict) -> str:
    if report["status"] in ("BROWSER_LOAD_CHECKED", "INPUT_RESPONSIVE"):
        return "PASS"
    if report["status"] == "NO_OBSERVABLE_RESPONSE":
        return "NO_OBSERVABLE_RESPONSE"
    if report["status"] == "TIMEOUT_ABORTED":
        return "PAGE_BLOCKED_DRIVER"
    errors = " ".join(str(e) for e in report.get("console_errors", []))
    blocked = " ".join(report.get("blocked_requests", []))
    if "origin 'null'" in errors and "blocked by CORS policy" in errors:
        return "SANDBOX_OPAQUE_ORIGIN_BREAKS_OWN_SCRIPT"
    if "Permissions policy violation" in errors:
        return "OPTIONAL_DEVICE_SENSOR_DENIED"
    if any(host in blocked for host in ANALYTICS_HOSTS):
        return "THIRD_PARTY_ANALYTICS_BLOCKED"
    if any(host in blocked for host in CDN_HINTS):
        return "EXTERNAL_CDN_REQUIRED"
    if "Locator.wait_for" in errors or "driver error" in errors:
        return "DRIVER_FLAKE_OR_TIMEOUT"
    if report.get("blocked_requests"):
        return "EXTERNAL_DEPENDENCY_BLOCKED"
    return "OTHER"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--reports", type=Path, action="append", required=True,
                    help="directory of per-entry reports; later directories win")
    ap.add_argument("--overrides", type=Path,
                    help="JSON mapping entry -> report path for retests that supersede a flake")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--isolation", default="{}")
    args = ap.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    by_entry = {}
    for directory in args.reports:
        for path in sorted(directory.glob("*.json")):
            if path.name == "summary.json":
                continue
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            by_entry[report["entry"]] = report
    if args.overrides and args.overrides.is_file():
        for entry, path in json.loads(args.overrides.read_text(encoding="utf-8")).items():
            candidate = Path(path)
            if candidate.is_file():
                by_entry[entry] = json.loads(candidate.read_text(encoding="utf-8"))

    entries, untested = [], []
    for item in manifest:
        report = by_entry.get(item["entry"])
        if report is None:
            untested.append({"key": item["key"], "entry": item["entry"], "mode": item["mode"]})
            continue
        entries.append({
            "key": item["key"], "repo": item.get("repo"), "mode": item["mode"],
            "entry": item["entry"], "status": report["status"],
            "failure_class": classify(report),
            "gameplay_verified": bool(report.get("gameplay_verified")),
            "render_changed_while_idle": bool(report.get("idle_output_changed")),
            "input_changed_pixels": bool(report.get("input_changed_pixels")),
            "input_changed_dom": bool(report.get("input_changed_dom")),
            "console_errors": report.get("console_errors", []),
            "blocked_functional_requests": report.get("blocked_requests", []),
            "stubbed_cosmetic_requests": report.get("stubbed_cosmetic_requests", []),
            "iframe_isolation": report.get("iframe_isolation"),
            "fingerprints": report.get("fingerprints"),
        })

    by_repo = {}
    for row in entries:
        by_repo.setdefault(row["repo"] or "unknown", []).append(row)
    classes, statuses = {}, {}
    for row in entries:
        classes[row["failure_class"]] = classes.get(row["failure_class"], 0) + 1
        statuses[row["status"]] = statuses.get(row["status"], 0) + 1

    payload = {
        "schema_version": 1,
        "captured_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "isolation": json.loads(args.isolation),
        "evidence_scope": (
            "Produced inside a disposable container with --network none, a read-only rootfs, a "
            "read-only artifact mount, dropped capabilities and a non-root user. INPUT_RESPONSIVE "
            "means rendered output changed after synthetic pointer/keyboard input; it does not "
            "prove correctness, completeness or authorship. A blocked request means the artifact "
            "needs the network, which is a dependency finding, not necessarily a defect."
        ),
        "counts": {
            "manifest_entries": len(manifest),
            "measured": len(entries),
            "untested": len(untested),
            "gameplay_verified": sum(1 for r in entries if r["gameplay_verified"]),
            "by_status": statuses,
            "by_failure_class": classes,
        },
        "untested": untested,
        "entries": entries,
        "by_repository": by_repo,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    args.out.write_text(body, encoding="utf-8")
    print(json.dumps({"out": str(args.out), "sha256": hashlib.sha256(body.encode()).hexdigest(),
                      **payload["counts"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
