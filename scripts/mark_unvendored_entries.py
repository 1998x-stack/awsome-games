#!/usr/bin/env python3
"""Separate "the collector found an entrypoint" from "the file ships in this repo".

Third-party snapshots under games/_repos are ignored unless the repository is
approved for publication, so after a local collection most `entrypoint_found`
rows point at files that are not in the repository. `check_catalog.py` requires
vendored files for `entrypoint_found`, which is correct: otherwise a fresh clone
would claim entrypoints it cannot serve.

Run this before committing a refreshed catalog so the committed database only
asserts what the checkout can actually satisfy. Uses git itself to decide, so it
cannot drift from .gitignore.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import ROOT, connect, now

VENDORED_STATUS = "entrypoint_found"
DETECTED_STATUS = "entrypoint_detected_not_vendored"


def ignored_paths(paths: list[str]) -> set[str]:
    """Ask git which of these paths are excluded from the repository."""
    if not paths:
        return set()
    proc = subprocess.run(["git", "check-ignore", "--stdin"], cwd=ROOT, input="\n".join(paths),
                          capture_output=True, text=True)
    # exit 1 simply means "none of them are ignored"
    if proc.returncode not in (0, 1):
        raise RuntimeError(f"git check-ignore failed: {proc.stderr.strip()}")
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write the reclassification")
    args = ap.parse_args()
    conn = connect()
    rows = [dict(r) for r in conn.execute(
        "SELECT project_id, repository_id, game_path FROM project_repositories "
        "WHERE playable_status=? AND game_path<>''", (VENDORED_STATUS,))]
    ignored = ignored_paths([r["game_path"] for r in rows])
    missing = {r["game_path"] for r in rows if not (ROOT / r["game_path"]).is_file()}
    summary = {"vendored_ok": len(rows) - len(ignored) - len(missing),
               "ignored": len(ignored), "absent": len(missing), "total": len(rows)}
    print(json.dumps(summary, ensure_ascii=False))
    if not args.apply:
        return
    stamp = now()
    with conn:
        for path in sorted(ignored | missing):
            note = (f"{DETECTED_STATUS}: the collector located this entrypoint in a local snapshot, "
                    "but the artifact is not vendored in this repository (see .gitignore and "
                    "config/publication_approvals.json), so it cannot be served from a fresh clone. "
                    "Re-run scripts/collect_repositories.py to materialise it locally.")
            conn.execute("UPDATE project_repositories SET playable_status=?, note=? WHERE game_path=?",
                         (DETECTED_STATUS, note, path))
            conn.execute("UPDATE projects SET playable_status=?, updated_at=? WHERE id="
                         "(SELECT project_id FROM project_repositories WHERE game_path=?)",
                         (DETECTED_STATUS, stamp, path))
    print(json.dumps({"reclassified": len(ignored | missing)}, ensure_ascii=False))
    conn.close()


if __name__ == "__main__":
    main()
