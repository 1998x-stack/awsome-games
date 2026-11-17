#!/usr/bin/env python3
"""Aggregate isolated container reports into one versioned, auditable evidence file.

Each capture is produced by running scripts/browser_smoke.py or
scripts/browser_gameplay_probe.py *inside* the network-isolated container
(scripts/isolation/). This script only reads those reports, re-hashes the
artifacts it can see, and refuses to record a gameplay pass that the report
itself did not establish.

Nothing here can promote an artifact: the status is copied from the report and
cross-checked, so a hand-written "INPUT_RESPONSIVE" string without matching
evidence (missing hashes, console errors, blocked functional requests) is
rejected.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

GAMEPLAY_OK = "INPUT_RESPONSIVE"
LOAD_OK = "BROWSER_LOAD_CHECKED"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(captures: list[dict], isolation: dict | None = None) -> dict:
    entries = []
    problems = []
    for cap in captures:
        report_path = Path(cap["report"])
        if not report_path.is_file():
            problems.append(f"missing report: {report_path}")
            continue
        report = json.loads(report_path.read_text(encoding="utf-8"))
        status = report.get("status")
        if status not in (GAMEPLAY_OK, LOAD_OK, "NO_OBSERVABLE_RESPONSE",
                          "INCOMPLETE_OR_FAILED", "TIMEOUT_ABORTED"):
            problems.append(f"unknown status in {report_path}: {status!r}")
            continue
        record = {
            "repo": cap["repo"],
            "repo_commit_sha": cap["commit"],
            "entry_path": cap["entry"],
            "probe": cap.get("probe", "gameplay" if status == GAMEPLAY_OK else "load"),
            "status": status,
            "tested_at": report.get("tested_at"),
            "iframe_isolation": report.get("iframe_isolation"),
            "console_errors": report.get("console_errors", []),
            "blocked_functional_requests": report.get("blocked_requests", []),
            "stubbed_cosmetic_requests": report.get("stubbed_cosmetic_requests", []),
            "failed_requests": report.get("failed_requests", []),
            "http_errors": report.get("http_errors", []),
            "report_sha256": sha256_file(report_path),
        }
        if GAMEPLAY_OK in str(cap.get("probe", "")) or status == GAMEPLAY_OK:
            record["input_changed_pixels"] = report.get("input_changed_pixels")
            record["input_changed_dom"] = report.get("input_changed_dom")
            record["idle_output_changed"] = report.get("idle_output_changed")
            record["fingerprints"] = report.get("fingerprints")
        # Fail closed: a pass must be internally consistent. A rejected record must
        # not be counted as verified, or the aggregate would overstate the evidence.
        record_problems = []
        if status == GAMEPLAY_OK:
            if not (report.get("input_changed_pixels") or report.get("input_changed_dom")):
                record_problems.append(f"{cap['entry']}: {GAMEPLAY_OK} without an input-driven change")
            if report.get("console_errors") or report.get("blocked_requests"):
                record_problems.append(f"{cap['entry']}: {GAMEPLAY_OK} with errors or blocked dependencies")
            if not report.get("iframe_isolation"):
                record_problems.append(f"{cap['entry']}: {GAMEPLAY_OK} without iframe isolation")
        record["gameplay_verified"] = not record_problems and status == GAMEPLAY_OK
        if record_problems:
            record["verification_rejected"] = True
            record["rejection_reasons"] = record_problems
            problems.extend(record_problems)
        screenshot = cap.get("screenshot")
        if screenshot and Path(screenshot).is_file():
            record["screenshot_sha256"] = sha256_file(Path(screenshot))
        entry_file = cap.get("entry_file")
        if entry_file and Path(entry_file).is_file():
            record["entry_sha256"] = sha256_file(Path(entry_file))
        entries.append(record)

    return {
        "schema_version": 1,
        "captured_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "isolation": isolation or {},
        "evidence_scope": (
            "Reports were produced inside a disposable --network none container with a "
            "read-only rootfs, a read-only staged mount, dropped capabilities and a non-root "
            "user. INPUT_RESPONSIVE means rendered output changed after synthetic pointer and "
            "keyboard input. It does not prove correctness, completeness, or authorship, and "
            "it is not a redistribution licence."
        ),
        "counts": {
            "captures": len(entries),
            "gameplay_verified": sum(1 for e in entries if e.get("gameplay_verified")),
            "load_checked": sum(1 for e in entries if e["status"] == LOAD_OK),
            "failed_or_incomplete": sum(1 for e in entries if e["status"] == "INCOMPLETE_OR_FAILED"),
            "no_observable_response": sum(1 for e in entries if e["status"] == "NO_OBSERVABLE_RESPONSE"),
        },
        "consistency_problems": problems,
        "entries": entries,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--capture", action="append", default=[],
                    help='JSON: {"repo":..,"commit":..,"entry":..,"report":..,"screenshot":..,"entry_file":..,"probe":..}')
    ap.add_argument("--isolation", help="JSON string describing the container configuration")
    args = ap.parse_args()
    captures = [json.loads(c) for c in args.capture]
    isolation = json.loads(args.isolation) if args.isolation else None
    data = build(captures, isolation)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), **data["counts"],
                      "consistency_problems": data["consistency_problems"]}, ensure_ascii=False))
    if data["consistency_problems"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
