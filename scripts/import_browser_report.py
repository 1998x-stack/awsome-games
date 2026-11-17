#!/usr/bin/env python3
"""Import evidence from an *already isolated* local browser smoke test.

Does not run third-party code. Dry-run by default; --write is required to record results.
A passing HTML load is never gameplay verification or redistribution authorization.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

STATUSES = {"BROWSER_LOAD_CHECKED", "INCOMPLETE_OR_FAILED"}
HEX40 = re.compile(r"^[0-9a-f]{40}$", re.I)
HEX64 = re.compile(r"^[0-9a-f]{64}$", re.I)


def staged_entry(root: Path, entry: str) -> Path:
    if not isinstance(entry,str) or not entry or "\\" in entry:
        raise ValueError("Unsafe entry path")
    rel=Path(entry)
    if rel.is_absolute() or any(p in ("..",".") for p in rel.parts) or rel.suffix.lower() not in (".html",".htm"):
        raise ValueError("Unsafe entry path")
    root=root.resolve(strict=True)
    path=root/rel
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError("Missing/unsafe staged entry")
    return path


def require_pinned_audit(work_id: str, repo_name: str, commit_sha: str,
                         entry_path: str, entry_data: bytes, audit_path: Path | None) -> dict:
    """Tie staged bytes to a reviewed Git-tree/blob identity, not a 40-hex claim.

    Git SHA-1 blob hashing is retained only for identity compatibility with
    pinned GitHub object IDs; SHA-256 remains the internal content fingerprint.
    """
    path = audit_path or ROOT / "data" / "research" / "audits" / (work_id + ".json")
    if path.is_symlink() or not path.is_file():
        raise ValueError("Pinned repository entry audit required for browser evidence import")
    audit = json.loads(path.read_text(encoding="utf-8"))
    expected = {"work_id":work_id, "repo":repo_name, "repository_commit_sha":commit_sha.lower(),
                "entry_path":entry_path}
    if any(str(audit.get(k,"")).lower()!=str(v).lower() for k,v in expected.items()):
        raise ValueError("Pinned audit does not match repository, work, commit or entry")
    actual_blob = hashlib.sha1(b"blob " + str(len(entry_data)).encode("ascii") + b"\\x00" + entry_data).hexdigest()
    if audit.get("entry_git_blob_sha","").lower()!=actual_blob:
        raise ValueError("Staged HTML Git blob does not match pinned source audit")
    if audit.get("source_file_full_text_read") is not True:
        raise ValueError("Pinned audit did not inspect the complete entry source")
    return audit


def validate_report(report: dict, entry: str) -> None:
    if not isinstance(report,dict) or report.get("status") not in STATUSES:
        raise ValueError("Invalid browser smoke report status")
    if report.get("entry") != entry:
        raise ValueError("Report entry does not match the staged file")
    if report.get("gameplay_verified") is not False:
        raise ValueError("Smoke reports cannot certify gameplay")
    if report["status"] == "BROWSER_LOAD_CHECKED":
        if not report.get("iframe_isolation") or not report.get("frame_body_loaded"):
            raise ValueError("Browser pass requires loaded body and isolated iframe")
        for key in ("console_errors","blocked_requests","blocked_websockets","failed_requests","http_errors"):
            if report.get(key):
                raise ValueError("Browser pass cannot have errors or blocked resources")
    if not isinstance(report.get("tested_at"),str) or not report["tested_at"]:
        raise ValueError("Missing test timestamp")
    try:
        when=datetime.fromisoformat(report["tested_at"].replace("Z","+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid test timestamp") from exc
    if when.tzinfo is None:
        raise ValueError("Test timestamp needs timezone offset")


def prepare_evidence(conn: sqlite3.Connection, *, work_id: str, commit_sha: str,
                     root: Path, report: dict, browser_version: str, environment: str,
                     screenshot: Path | None = None,
                     audit_manifest: Path | None = None) -> dict:
    work=conn.execute("SELECT work_id,repository_full_name,entry_path FROM research_works WHERE work_id=?",
                      (work_id,)).fetchone()
    if not work:
        raise ValueError("Unknown research work")
    entry=work["entry_path"]
    if not entry:
        raise ValueError("Source entry has not been reviewed")
    if not HEX40.fullmatch(commit_sha):
        raise ValueError("Expected a 40-character immutable Git commit SHA")
    if not browser_version.strip() or not environment.strip():
        raise ValueError("Browser and environment details are required")
    file=staged_entry(root,entry)
    validate_report(report,entry)
    data=file.read_bytes()
    require_pinned_audit(work_id,work["repository_full_name"],commit_sha,entry,data,audit_manifest)
    entry_sha=hashlib.sha256(data).hexdigest()
    screenshot_hash=None
    if report["status"]=="BROWSER_LOAD_CHECKED" and screenshot is None:
        raise ValueError("Screenshot required for passing browser load evidence")
    if screenshot is not None:
        if screenshot.is_symlink() or not screenshot.is_file():
            raise ValueError("Invalid screenshot evidence file")
        screenshot_hash=hashlib.sha256(screenshot.read_bytes()).hexdigest()
    payload={
        "work_id":work_id,"repository_full_name":work["repository_full_name"],
        "repo_commit_sha":commit_sha.lower(),"entry_path":entry,"entry_sha256":entry_sha,
        "report_status":report["status"],"tested_at":report["tested_at"],
        "browser_name":"Chromium","browser_version":browser_version,
        "environment":environment,"report_json":json.dumps(report,ensure_ascii=False,sort_keys=True),
        "screenshot_sha256":screenshot_hash,
    }
    canonical=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
    payload["evidence_id"]=hashlib.sha256(canonical).hexdigest()
    payload["imported_at"]=datetime.now(timezone.utc).isoformat()
    return payload


def save_evidence(conn: sqlite3.Connection, evidence: dict) -> None:
    cols=("evidence_id","work_id","repository_full_name","repo_commit_sha",
          "entry_path","entry_sha256","report_status","tested_at","browser_name",
          "browser_version","environment","report_json","screenshot_sha256","imported_at")
    with conn:
        conn.execute("INSERT OR IGNORE INTO research_runtime_evidence (" + ",".join(cols) +
                     ") VALUES (" + ",".join("?" for _ in cols) + ")",
                     tuple(evidence[c] for c in cols))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-id",required=True)
    parser.add_argument("--repo-commit",required=True)
    parser.add_argument("--root",required=True,type=Path,help="Trusted isolated source staging directory")
    parser.add_argument("--report",required=True,type=Path,help="JSON from scripts/browser_smoke.py")
    parser.add_argument("--browser-version",required=True)
    parser.add_argument("--environment",required=True,help="Container/VM name and OS; do not include secrets")
    parser.add_argument("--screenshot",type=Path)
    parser.add_argument("--audit",type=Path,help="Pinned static entry audit; default: data/research/audits/<work-id>.json")
    parser.add_argument("--write",action="store_true",help="Explicitly persist verified metadata")
    args=parser.parse_args()
    from db import connect
    from research_pipeline import ingest
    conn=connect()
    ingest(conn)
    report=json.loads(args.report.read_text(encoding="utf-8"))
    evidence=prepare_evidence(conn,work_id=args.work_id,commit_sha=args.repo_commit,
        root=args.root,report=report,browser_version=args.browser_version,
        environment=args.environment,screenshot=args.screenshot,
        audit_manifest=args.audit)
    if args.write:
        save_evidence(conn,evidence)
    print(json.dumps({"evidence_id":evidence["evidence_id"],"work_id":args.work_id,
          "entry_sha256":evidence["entry_sha256"],"report_status":evidence["report_status"],
          "written":args.write,"gameplay_verified":False},ensure_ascii=False))
    conn.close()


if __name__=="__main__":
    main()
