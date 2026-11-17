#!/usr/bin/env python3
"""Apply cited manual adjudications; no upstream API calls and no game execution.

The JSON config is review source-of-truth in Git. Imported snapshot facts remain
separate. Repeated imports are idempotent and edits are logged in SQLite.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from db import ROOT, DB_PATH

DEFAULT = ROOT / "config" / "research_reviews.json"
ALLOWED_STATUS = {"APPROVED", "DRAFT", "REJECTED"}
PRIMARY_EVIDENCE_KINDS = {"PINNED_SOURCE_REPOSITORY", "ORIGINAL_AUTHOR_POST"}
# This only proves the URL is tied to the indexed entity, not that an author's
# contested model claim is objectively true. Human review remains necessary.
WORK_FIELDS = {"entry_path","entry_status","prompt_status","human_contribution",
               "human_status","model_evidence","external_dependencies","reviewer_note"}
POST_FIELDS = {"work_id","entity_id","confidence","reviewer_note"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS research_review_history (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 entity_type TEXT NOT NULL,
 entity_key TEXT NOT NULL,
 review_json TEXT NOT NULL,
 evidence_url TEXT NOT NULL,
 applied_at TEXT NOT NULL
);
"""


def safe_evidence_url(value):
    if not value:return ""
    if not isinstance(value,str):raise ValueError("Evidence URL must be a string")
    try:
        p=urlsplit(value)
        if p.scheme!="https" or not p.hostname or p.username or p.password or any(ord(x)<32 for x in value):
            raise ValueError("Invalid review evidence URL")
    except ValueError as exc:
        raise ValueError("Invalid review evidence URL") from exc
    return value


def assert_primary_source_binding(conn, kind, item, evidence):
    """Reject unrelated HTTPS pages as the basis for APPROVED field overrides.

    Pinned GitHub blob URLs are source-code evidence, not automatically model
    authorship evidence. Original X posts use the *exact* indexed status path.
    """
    if item["review_status"] != "APPROVED":
        return
    url = urlsplit(evidence)
    hostname = (url.hostname or "").lower()
    path = url.path.rstrip("/")
    source_kind = item["primary_evidence_kind"]
    if source_kind == "ORIGINAL_AUTHOR_POST":
        if kind == "post":
            original = conn.execute("SELECT post_url FROM research_posts WHERE post_key=?",
                                    (item["post_key"],)).fetchone()
            original = original[0] if original else ""
            p = urlsplit(original)
            if (hostname in ("x.com", "twitter.com") and
                (p.hostname or "").lower() in ("x.com", "twitter.com") and
                p.path.rstrip("/") == path and
                re.search(r"/status/[0-9]+$",path)):
                return
        else:
            linked = conn.execute("SELECT post_url FROM research_posts WHERE work_id=?",
                                  (item["work_id"],)).fetchall()
            if hostname in ("x.com","twitter.com") and any(
                urlsplit(x[0] or "").path.rstrip("/") == path and
                re.search(r"/status/[0-9]+$",path) for x in linked):
                return
    if source_kind == "PINNED_SOURCE_REPOSITORY" and hostname == "github.com":
        if kind == "work":
            row = conn.execute("SELECT repository_full_name FROM research_works WHERE work_id=?",
                               (item["work_id"],)).fetchone()
            repo = (row[0] if row else "") or ""
            # Exact repo identity + immutable 40-hex commit and a file path.
            pattern = r"/" + re.escape(repo) + r"/blob/[0-9a-fA-F]{40}/[^/].+"
            if repo and re.fullmatch(pattern,path,re.I):
                return
        else:
            row = conn.execute("SELECT repo_urls FROM research_posts WHERE post_key=?",
                               (item["post_key"],)).fetchone()
            try:
                repos = json.loads(row[0] or "[]") if row else []
            except (TypeError,ValueError):
                repos = []
            for candidate in repos:
                p = urlsplit(candidate)
                if (p.hostname or "").lower() != "github.com":
                    continue
                repo_path = "/".join(p.path.strip("/").split("/")[:2])
                if re.fullmatch("/"+re.escape(repo_path)+r"/blob/[0-9a-fA-F]{40}/[^/].+",path,re.I):
                    return
    raise ValueError("APPROVED evidence URL is not bound to an original post or pinned source repository")


def safe_entry_path(value):
    if value is None:return None
    if not isinstance(value,str) or not value or value.startswith("/") or "\\" in value:
        raise ValueError("Entry override must be a safe repository-relative path")
    if any(part in ("",".","..") for part in value.split("/")) or not value.lower().endswith((".html",".htm")):
        raise ValueError("Invalid entry path override")
    return value


def validate_manifest(raw):
    if not isinstance(raw,dict) or raw.get("schema_version")!=1:
        raise ValueError("Unsupported review manifest")
    works=raw.get("works",[])
    posts=raw.get("posts",[])
    if not isinstance(works,list) or not isinstance(posts,list):
        raise ValueError("Review manifest works/posts must be arrays")
    prepared=[]
    seen=set()
    for kind,group,identity,allowed in (("work",works,"work_id",WORK_FIELDS),
                                         ("post",posts,"post_key",POST_FIELDS)):
        for item in group:
            if not isinstance(item,dict) or not isinstance(item.get(identity),str) or not item[identity]:
                raise ValueError("Review entry must have a stable "+identity)
            status=item.get("review_status")
            if status not in ALLOWED_STATUS:
                raise ValueError("Invalid review_status")
            evidence=safe_evidence_url(item.get("evidence_url"))
            if status=="APPROVED" and not evidence:
                raise ValueError("Approved review requires an HTTPS evidence URL")
            if status=="APPROVED" and (
                    item.get("primary_evidence_kind") not in PRIMARY_EVIDENCE_KINDS
                    or not isinstance(item.get("reviewer"),str) or not item["reviewer"].strip()
                    or not isinstance(item.get("reviewer_note"),str) or not item["reviewer_note"].strip()):
                raise ValueError("APPROVED requires explicit primary_evidence_kind, reviewer and reviewer_note")
            unexpected=set(item)-({identity,"review_status","evidence_url","reviewed_at",
                                   "primary_evidence_kind","reviewer"}|allowed)
            if unexpected:raise ValueError("Unknown fields in review manifest: "+",".join(sorted(unexpected)))
            key=(kind,item[identity])
            if key in seen:raise ValueError("Duplicate review entry: "+str(key))
            seen.add(key)
            if kind=="work" and "entry_path" in item:safe_entry_path(item["entry_path"])
            for field in allowed:
                if field in item and item[field] is not None and (
                    not isinstance(item[field],str) or len(item[field])>3000):
                    raise ValueError("Review field must be bounded text: "+field)
            prepared.append((kind,item,evidence))
    return prepared


def apply_manifest(conn: sqlite3.Connection, manifest: Path = DEFAULT, dry_run=False):
    prepared=validate_manifest(json.loads(manifest.read_text(encoding="utf-8")))
    for kind,item,_ in prepared:
        table="research_works" if kind=="work" else "research_posts"
        column="work_id" if kind=="work" else "post_key"
        if not conn.execute(f"SELECT 1 FROM {table} WHERE {column}=?",(item[column],)).fetchone():
            raise ValueError("Review references an unknown "+kind+": "+item[column])
        if kind=="post" and item.get("work_id") and not conn.execute(
            "SELECT 1 FROM research_works WHERE work_id=?",(item["work_id"],)).fetchone():
            raise ValueError("Review refers to an unknown work_id")
        assert_primary_source_binding(conn,kind,item,item.get("evidence_url",""))
    if dry_run:return {"review_entries":len(prepared),"written":0}
    conn.executescript(SCHEMA)
    changed=0
    with conn:
        for kind,item,evidence in prepared:
            table="research_work_reviews" if kind=="work" else "research_post_reviews"
            key="work_id" if kind=="work" else "post_key"
            fields=WORK_FIELDS if kind=="work" else POST_FIELDS
            existing=conn.execute(f"SELECT * FROM {table} WHERE {key}=?",(item[key],)).fetchone()
            prev=dict(existing) if existing else {}
            desired={field:item.get(field,prev.get(field)) for field in sorted(fields)}
            # reviewer_note has a NOT NULL default in both tables, but supplying
            # SQL NULL bypasses the column default for DRAFT/REJECTED reviews.
            if desired.get("reviewer_note") is None:
                desired["reviewer_note"] = ""
            desired[key]=item[key]
            desired["review_status"]=item["review_status"]
            desired["evidence_url"]=evidence or prev.get("evidence_url") or ""
            # Reviewer/source-kind changes are meaningful provenance edits even
            # when the materialised review row remains otherwise unchanged.
            meta={"reviewer":item.get("reviewer") or "",
                  "primary_evidence_kind":item.get("primary_evidence_kind") or ""}
            last=conn.execute("""SELECT review_json FROM research_review_history
                WHERE entity_type=? AND entity_key=? ORDER BY id DESC LIMIT 1""",
                (kind,item[key])).fetchone()
            previous_meta={}
            if last:
                try: previous_meta=json.loads(last[0]).get("_source_review_meta",{})
                except (ValueError,TypeError): previous_meta={}
            if existing and all(prev.get(k)==v for k,v in desired.items()) and previous_meta==meta:
                continue
            when=datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            desired["reviewed_at"]=item.get("reviewed_at") or when
            columns=list(desired)
            placeholders=",".join("?" for _ in columns)
            updates=",".join(f"{c}=excluded.{c}" for c in columns if c!=key)
            conn.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES({placeholders}) "
                         f"ON CONFLICT({key}) DO UPDATE SET {updates}",
                         tuple(desired[c] for c in columns))
            conn.execute("""INSERT INTO research_review_history
                (entity_type,entity_key,review_json,evidence_url,applied_at)
                VALUES(?,?,?,?,?)""",
                (kind,item[key],json.dumps(dict(desired,_source_review_meta=meta),ensure_ascii=False,sort_keys=True),
                 desired["evidence_url"],when))
            changed+=1
    return {"review_entries":len(prepared),"written":changed}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--file",type=Path,default=DEFAULT)
    p.add_argument("--apply",action="store_true",help="Explicitly update SQLite (default is dry-run)")
    args=p.parse_args()
    if args.apply:
        conn=sqlite3.connect(DB_PATH);conn.row_factory=sqlite3.Row
    else:
        conn=sqlite3.connect("file:"+str(DB_PATH)+"?mode=ro",uri=True)
        conn.row_factory=sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        result=apply_manifest(conn,args.file,dry_run=not args.apply)
    finally:conn.close()
    print(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":
    main()
