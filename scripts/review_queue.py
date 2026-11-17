#!/usr/bin/env python3
"""Produce conservative, auditable review queues from the current SQLite research layer.

Discovery is not approval: these records are not claims of authorship, licensing or gameplay.
"""
from __future__ import annotations
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALIASES = ROOT / "config" / "work_aliases.json"


def classify_candidate(repo: dict) -> tuple[str, str]:
    """A routing hint, never a conclusive audit of the linked project."""
    relation = str(repo.get("relation") or "").upper()
    tech = str(repo.get("tech") or "").lower()
    browser = str(repo.get("browser_hint") or "").lower()
    if "PULL_REQUEST" in relation:
        return "PR_OR_COMPONENT", "Review parent repository and PR; not an independent game."
    if "TOOL_NOT_WORK_SOURCE" in relation or "RELATED_DIFFERENT_WORK" in relation:
        return "RELATED_TOOL_OR_DIFFERENT_WORK", "Do not promote this URL to an original game."
    if "MIRROR" in relation:
        return "MIRROR_NEEDS_ATTRIBUTION", "Find original author and check redistribution permission."
    if browser == "no" or any(t in tech for t in ("unity", "godot", "windows native", "snes rom", "python/non-browser", "rust native")):
        return "NON_BROWSER_REVIEW", "Determine delivery format; never run native code in the collector."
    if "multi_model" in relation or "mixed" in relation.lower():
        return "MIXED_MODEL_REVIEW", "Separate contributions of different generators."
    return "BROWSER_CANDIDATE_UNREVIEWED", "Verify source entry, assets, license and generated model evidence."


def aliases(conn: sqlite3.Connection, path: Path = ALIASES) -> list[dict]:
    """Alias evidence is a candidate crosswalk; it does not silently edit main tables."""
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("aliases"), list):
        raise ValueError("Invalid work aliases manifest")
    result = []
    for alias in data["aliases"]:
        work_id, project_id = alias["work_id"], alias["project_id"]
        match = conn.execute(
            """SELECT lower(w.repository_full_name) = lower(r.full_name)
               FROM research_works w JOIN projects p ON p.id=?
               JOIN project_repositories pr ON pr.project_id=p.id
               JOIN repositories r ON r.id=pr.repository_id
               WHERE w.work_id=? AND lower(r.full_name)=lower(?) LIMIT 1""",
            (project_id, work_id, alias["repository_full_name"]),
        ).fetchone()
        if not match or match[0] != 1:
            raise ValueError("Alias repository or entity mismatch: " + work_id)
        if alias.get("status") != "CANDIDATE":
            raise ValueError("Only review candidates are accepted; explicit approvals belong in review history")
        result.append(dict(alias))
    return result


def build_queue(conn: sqlite3.Connection, alias_path: Path = ALIASES) -> dict:
    """Read-only. Queries reviewed states, without auto-promoting provisional entities."""
    conn.row_factory = sqlite3.Row
    legacy_repos = {r[0].casefold() for r in conn.execute("SELECT full_name FROM repositories")}
    rows = conn.execute(
        """SELECT r.full_name,r.display_title,r.source_channel,r.relation,r.tech,
           r.browser_hint,r.license_state,r.model_evidence,r.review_level,r.browser_status,
           r.readme_url,r.evidence_url FROM research_repositories r ORDER BY lower(r.full_name)"""
    ).fetchall()
    repositories = []
    for row in rows:
        repo = dict(row)
        route, action = classify_candidate(repo)
        repo["queue_kind"] = route
        repo["next_action"] = action
        repo["already_in_legacy_collector"] = repo["full_name"].casefold() in legacy_repos
        repo["review_status"] = "NEEDS_CODE_AND_RIGHTS_REVIEW"
        repositories.append(repo)
    posts = []
    for row in conn.execute(
        """SELECT p.post_key,p.entity_id,p.title,p.post_url,p.creator,p.work_id,
           p.match_status,p.entity_status,p.confidence,p.kind_signal,p.sources,p.model_claim,
           coalesce(v.review_status,'UNREVIEWED') AS review_status,
           v.evidence_url AS review_evidence_url
           FROM research_posts p LEFT JOIN research_post_reviews v ON v.post_key=p.post_key
           ORDER BY CASE WHEN p.match_status='UNRESOLVED' THEN 0 ELSE 1 END,p.post_key"""
    ):
        post = dict(row)
        if post["review_status"] != "APPROVED":
            post["next_action"] = "LINK_TO_WORK_OR_MARK_NON_GAME_WITH_DIRECT_EVIDENCE"
            posts.append(post)
    works = []
    for row in conn.execute(
        """SELECT w.work_id,w.title,w.repository_full_name,w.entry_path,w.entry_status,
           w.prompt_status,w.model_evidence,w.build_method,w.artifact_kind,
           coalesce(v.review_status,'UNREVIEWED') AS review_status
           FROM research_works w LEFT JOIN research_work_reviews v ON v.work_id=w.work_id
           ORDER BY w.work_id"""
    ):
        work = dict(row)
        if work["review_status"] != "APPROVED":
            work["next_action"] = "VERIFY_ENTRY_BUILD_PROMPT_MODEL_RIGHTS"
            works.append(work)
    alias_candidates = aliases(conn, alias_path)
    return {
        "schema_version": 1,
        "warning": "Queue entries are unverified leads. They do not authorize cloning, execution or republishing.",
        "stats": {
            "post_review_queue": len(posts),
            "work_review_queue": len(works),
            "repository_review_queue": len(repositories),
            "research_only_repository_candidates": sum(not r["already_in_legacy_collector"] for r in repositories),
            "alias_candidates": len(alias_candidates),
        },
        "posts": posts,
        "works": works,
        "repositories": repositories,
        "alias_candidates": alias_candidates,
    }


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    from db import connect
    from research_pipeline import ingest
    conn = connect()
    ingest(conn)
    print(json.dumps(build_queue(conn), ensure_ascii=False, indent=2))
    conn.close()
