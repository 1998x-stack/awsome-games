#!/usr/bin/env python3
"""Write measured isolation findings into the authoritative catalog (SQLite).

Why this exists
---------------
The catalog is authoritative, but until now the runtime statuses it carried
(`sandbox_incompatible`, `runtime_requires_network`, ...) had no writer: only
`collect_repositories.py`'s RUNTIME_REVIEWED_STATUSES set preserved them. A conclusion
that no script can produce is not auditable, so this is that writer.

Fail-closed by construction
---------------------------
* It only ever writes RESTRICTIVE statuses. Nothing here can make an artifact
  publishable; positive results (`INPUT_RESPONSIVE`) stay in the survey artifact and
  only become publishable through the explicit evidence pipeline plus a human
  publication approval.
* It refuses to run against a survey file that lacks fingerprints, a capture
  timestamp, or the isolation configuration it ran under, so a hand-written "survey"
  cannot move the catalog.
* A new finding may never weaken an existing restrictive one: the row keeps whichever
  conclusion is harder to publish.
* Each written row records the survey file and its sha256, so the claim can be traced
  to the measurement that produced it.

Apply order: run this AFTER collect_repositories.py and BEFORE
mark_unvendored_entries.py, because marking entries as not-vendored rewrites
playable_status for anything that is not shipped in the repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import connect, now
from playability_policy import (RESTRICTIVE_STATUS_PRIORITY,
                                update_project_aggregates)

# Only classes that ARE a conclusion about the artifact, mapped to the status that
# states it. A class not listed here moves nothing: "we could not tell" must never be
# recorded as if it were a finding.
CLASS_TO_STATUS = {
    "SANDBOX_OPAQUE_ORIGIN_BREAKS_OWN_SCRIPT": "sandbox_incompatible",
    "EXTERNAL_CDN_REQUIRED": "runtime_requires_network",
    "THIRD_PARTY_ANALYTICS_BLOCKED": "runtime_third_party_beacon",
    "OPTIONAL_DEVICE_SENSOR_DENIED": "runtime_optional_sensor_denied",
    "INPUT_RESPONSE_NOT_ATTRIBUTABLE": "runtime_input_not_attributable",
    "PAGE_BLOCKED_DRIVER": "runtime_driver_timeout",
    "NO_OBSERVABLE_RESPONSE": "runtime_no_interaction",
}

# An automated PASS may refute the previous restriction, but it is NOT gameplay
# proof or an authorization to re-publish. Keep the mapping nonpublishable until
# a separately reviewed affirmative recovery is approved.
RETRACTED_TO = "runtime_needs_retest"

# Same restriction order as the repository collector / project aggregator.
PRECEDENCE = RESTRICTIVE_STATUS_PRIORITY

def pass_has_evidence(entry: dict) -> bool:
    """Attributable, clean isolated LOAD evidence sufficient for *review only*."""
    return (
        entry.get("status") in ("BROWSER_LOAD_CHECKED", "INPUT_RESPONSIVE")
        and entry.get("iframe_isolation") is True
        and bool(entry.get("fingerprints"))
        and not entry.get("console_errors")
        and not entry.get("blocked_functional_requests")
        and not entry.get("blocked_requests")
    )


def rank(status: str) -> int:
    return PRECEDENCE.index(status) if status in PRECEDENCE else len(PRECEDENCE)


# For these classes the *absence* of a measurement is the evidence, so requiring
# fingerprints would be backwards. They must instead carry the recorded reason.
NO_FINGERPRINT_CLASSES = {"PAGE_BLOCKED_DRIVER"}


def survey_is_trustworthy(data: dict) -> tuple[bool, str]:
    if not data.get("captured_at"):
        return False, "survey has no captured_at timestamp"
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        return False, "survey has no entries"
    # Only entries that actually make a claim need evidence. An entry that failed
    # before it could be measured has no fingerprints and no class, so it moves
    # nothing; demanding evidence from it would block legitimate findings.
    claiming = [e for e in entries if CLASS_TO_STATUS.get(e.get("failure_class") or "")
                or e.get("failure_class") == "PASS"]
    if not claiming:
        return False, "survey states no conclusion for any entry"
    missing, unexplained = [], []
    for e in claiming:
        if e.get("failure_class") == "PASS" and not pass_has_evidence(e):
            return False, f"PASS lacks clean isolated evidence: {e.get('key')}"
        if e.get("fingerprints"):
            continue
        if e.get("failure_class") in NO_FINGERPRINT_CLASSES:
            if not any("hard timeout" in str(err) for err in (e.get("console_errors") or [])):
                unexplained.append(e.get("key"))
            continue
        missing.append(e.get("key"))
    if missing:
        return False, (f"{len(missing)} entries claim a finding but carry no fingerprints, "
                       f"e.g. {missing[:3]}")
    if unexplained:
        return False, (f"{len(unexplained)} entries claim the driver was blocked without recording "
                       f"a hard timeout, e.g. {unexplained[:3]}")
    isolation = data.get("isolation") or {}
    if not (isolation.get("network_policy") or isolation.get("network") or isolation.get("runtime")):
        return False, "survey does not record the isolation configuration it ran under"
    return True, ""


def locate(conn, survey_entry: str):
    """Find the mapping row for a survey entry path like `_repos/<repo_dir>/<entry_rel>`.

    The repository is identified from its recorded clone path rather than by trying to
    reverse the `owner__name` directory name, which is ambiguous when a name itself
    contains `__`.
    """
    parts = survey_entry.split("/")
    if len(parts) < 3 or parts[0] != "_repos":
        return None
    repo_dir, entry_rel = parts[1], "/".join(parts[2:])
    repo = conn.execute(
        "SELECT id FROM repositories WHERE clone_path = ? OR clone_path LIKE ?",
        ("games/_repos/" + repo_dir, "%/" + repo_dir)).fetchone()
    if repo is None:
        return None
    matches = conn.execute(
        "SELECT project_id, playable_status FROM project_repositories "
        "WHERE repository_id=? AND entry_path=?", (repo["id"], entry_rel)).fetchall()
    # Same entry may map to multiple works in a collection. Never choose an
    # arbitrary first project and rewrite only its evidence claim.
    return matches[0] if len(matches) == 1 else None


def plan(conn, data: dict, survey_name: str, digest: str):
    """Decide what the survey justifies, without touching the database."""
    planned, unchanged, weaker, unlocated = [], [], [], []
    for entry in data["entries"]:
        klass = entry.get("failure_class") or ""
        row = locate(conn, entry["entry"])
        if klass == "PASS":
            # Retraction path. Only an entry with recorded fingerprints and a
            # confirmed isolated frame may undo someone else's finding.
            if row is None:
                unlocated.append(entry["key"])
                continue
            if not pass_has_evidence(entry):
                weaker.append((entry["key"], row["playable_status"], "PASS without evidence"))
                continue
            if row["playable_status"] not in PRECEDENCE or row["playable_status"] == RETRACTED_TO:
                unchanged.append(entry["key"])
                continue
            note = (f"{RETRACTED_TO}: retracts a previous restrictive finding without "
                    f"authorizing publication. The {data['captured_at']} survey measured "
                    f"{entry.get('status')} with clean iframe isolation. "
                    f"Evidence: {survey_name} sha256 {digest[:16]}. "
                    "Independent positive gameplay/rights approval is still required.")
            planned.append({"status": RETRACTED_TO, "note": note, "project_id": row["project_id"],
                            "entry": entry["entry"], "retraction": True})
            continue
        status = CLASS_TO_STATUS.get(klass)
        if not status:
            continue  # this class is not a conclusion; it must move nothing
        if row is None:
            unlocated.append(entry["key"])
            continue
        if row["playable_status"] == status:
            unchanged.append(entry["key"])
            continue
        if rank(row["playable_status"]) < rank(status):
            weaker.append((entry["key"], row["playable_status"], status))
            continue
        note = (f"{status}: measured {data['captured_at']} in an isolated container, class "
                f"{entry['failure_class']}. Evidence: {survey_name} sha256 {digest[:16]}. "
                "Reproduce with scripts/consolidate_repo_survey.py then this script.")
        planned.append({"status": status, "note": note, "project_id": row["project_id"],
                        "entry": entry["entry"], "retraction": False})
    return planned, unchanged, weaker, unlocated


def apply_plan(conn, planned) -> set:
    """Write the planned findings and re-derive each touched project aggregate."""
    stamp = now()
    touched = set()
    with conn:
        for item in planned:
            parts = item["entry"].split("/")
            entry_rel = "/".join(parts[2:])
            repo = conn.execute(
                "SELECT id FROM repositories WHERE clone_path = ? OR clone_path LIKE ?",
                ("games/_repos/" + parts[1], "%/" + parts[1])).fetchone()
            conn.execute("UPDATE project_repositories SET playable_status=?, note=? "
                         "WHERE project_id=? AND repository_id=? AND entry_path=?",
                         (item["status"], item["note"], item["project_id"], repo["id"], entry_rel))
            touched.add(item["project_id"])
        update_project_aggregates(conn, touched, stamp)
    return touched


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--survey", type=Path, required=True)
    ap.add_argument("--apply", action="store_true", help="write the findings")
    args = ap.parse_args()

    raw = args.survey.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    data = json.loads(raw.decode("utf-8"))
    ok, why = survey_is_trustworthy(data)
    if not ok:
        raise SystemExit(f"refusing to apply {args.survey}: {why}")

    conn = connect()
    planned, unchanged, weaker, unlocated = plan(conn, data, args.survey.name, digest)
    retractions = sum(1 for p in planned if p.get("retraction"))
    print(json.dumps({"survey": str(args.survey), "sha256": digest,
                      "to_write": len(planned), "of_which_retractions": retractions,
                      "already_same": len(unchanged),
                      "refused_would_weaken": len(weaker), "no_catalog_row": len(unlocated)},
                     ensure_ascii=False, indent=2))
    if weaker:
        print(json.dumps({"weaker_pairs": weaker}, ensure_ascii=False))
    if unlocated:
        print(json.dumps({"unlocated": unlocated}, ensure_ascii=False))
    if not args.apply:
        print("dry run: pass --apply to write the findings")
        conn.close()
        return
    touched = apply_plan(conn, planned)
    conn.close()
    print(json.dumps({"written": len(planned), "projects_touched": len(touched)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
