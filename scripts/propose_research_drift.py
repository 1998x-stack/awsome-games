#!/usr/bin/env python3
"""Prepare a source-metadata-only, review-required PR summary.

The proposal does NOT modify data/research/current, reviewed entities, legacy
catalogue, game code, release approvals or any Git branch. GitHub Actions may
open a DRAFT PR containing only the summary after comparing verified snapshots.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from db import ROOT
from refresh_research import prepare, load_current_pair, _json_bytes

DEFAULT_OUTPUT=ROOT/"data/research/proposals/latest.json"
SCALAR_FIELDS=("source","source_id","post_id","post_url","title",
               "category","author","play_url","repo_url","source_url","title_zh")


def make_index(records: list[dict]) -> dict[str,dict]:
    index={}
    for rec in records:
        if not isinstance(rec,dict):
            raise ValueError("Invalid upstream metadata row")
        src=rec.get("source")
        ident=rec.get("source_id")
        key=str(src if src is not None else "")+":"+str(ident if ident is not None else "")
        if key in index or key.startswith(":") or key.endswith(":"):
            raise ValueError("Duplicate or missing metadata source ID: "+key)
        index[key]={field:rec.get(field) for field in SCALAR_FIELDS}
    return index


def source_digest(index: dict) -> str:
    return hashlib.sha256(_json_bytes({k:index[k] for k in sorted(index)})).hexdigest()


def summarize(previous: dict, candidate: dict, added_x_posts: int) -> dict:
    old=make_index(previous["records"])
    new=make_index(candidate["records"])
    old_keys=set(old)
    new_keys=set(new)
    modified=sorted(k for k in old_keys & new_keys if old[k]!=new[k])
    added=sorted(new_keys-old_keys)
    removed=sorted(old_keys-new_keys)
    changed=bool(added or removed or modified)
    prev_count=Counter(x["source"] for x in previous["records"])
    next_count=Counter(x["source"] for x in candidate["records"])
    return {
        "schema_version":1,
        "state":"REVIEW_REQUIRED" if changed else "NO_SOURCE_RECORD_DRIFT",
        "scope":"SOURCE_METADATA_ONLY",
        "warning":"This PR contains unverified index observations only; no model attribution, publication or gameplay approval.",
        "baseline_source_sha256":source_digest(old),
        "candidate_source_sha256":source_digest(new),
        "source_counts":[{"source":k,"before":prev_count[k],"after":next_count[k]}
                         for k in sorted(set(prev_count)|set(next_count))],
        "record_changes":{"added":len(added),"removed":len(removed),
                          "modified":len(modified),"added_original_post_ids":added_x_posts},
        "examples":{"added_source_ids":added[:100],"removed_source_ids":removed[:100],
                    "modified_source_ids":modified[:100]},
        "truncated_example_ids":{"added":max(0,len(added)-100),
                                 "removed":max(0,len(removed)-100),
                                 "modified":max(0,len(modified)-100)},
        "review_requirements":[
            "Verify direct upstream source, license and IDs before accepting changes",
            "Inspect source removals and collisions; do not silently drop evidence",
            "Do not promote upstream labels to APPROVED without cited human review",
            "If accepted, explicitly stage snapshots with refresh_research.py --write in a separate reviewed change"
        ],
    }


def generate(output: Path=DEFAULT_OUTPUT, *, fetch=None,allow_shrink=False) -> dict:
    from refresh_research import fetch_json
    previous,_=load_current_pair()
    candidate,entities,added=prepare(fetch=fetch or fetch_json,allow_shrink=allow_shrink)
    summary=summarize(previous,candidate,added)
    if summary["state"]=="REVIEW_REQUIRED":
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\\n",encoding="utf-8")
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=DEFAULT_OUTPUT)
    args=parser.parse_args()
    summary=generate(args.output)
    print(json.dumps({"state":summary["state"],
            "record_changes":summary["record_changes"],
            "candidate_source_sha256":summary["candidate_source_sha256"],
            "proposal_path":str(args.output) if summary["state"]=="REVIEW_REQUIRED" else None},
          ensure_ascii=False))


if __name__=="__main__":main()
