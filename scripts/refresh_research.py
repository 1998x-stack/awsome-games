#!/usr/bin/env python3
"""Update evidence metadata only, never clone or run third-party code.

Dry-run by default; --write stages a versioned pair and atomically updates current/active.json.
Original v1 snapshots are immutable. Importer uses current files when available.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"data/research/v1"
CURRENT=ROOT/"data/research/current"
SOURCES=(
    ("FableList","https://raw.githubusercontent.com/fengyiqicoder/awesome-fable-5.2/main/data/works.json"),
    ("VibeGamer","https://raw.githubusercontent.com/ummydev/awesome-claude-fable-games/main/data/games.json"),
    ("DramaSo","https://raw.githubusercontent.com/mofa-si/awesome-fable-5-2-videos/main/data/collection.json"),
    ("Sandbase","https://raw.githubusercontent.com/sandbase-lab/awesome-fable-5-2/main/data/videos.json"),
)

def post_id(url):
    """Only X/Twitter status URLs are eligible to become post entity IDs."""
    try:
        p=urlsplit(str(url or ""))
        if p.scheme not in ("https","http") or p.hostname not in (
            "x.com","www.x.com","twitter.com","www.twitter.com"):
            return None
        m=re.search(r"^/[^/]+/status/([0-9]+)(?:/|$)",p.path)
        return m.group(1) if m else None
    except (TypeError,ValueError):
        return None

def normalize(source,x,index,source_url):
    post={"FableList":"post","VibeGamer":"post_url","DramaSo":"sourceUrl","Sandbase":"postUrl"}[source]
    author=x.get("maker_handle") or x.get("maker") if source=="VibeGamer" else x.get("author") or ""
    if isinstance(author,dict):author=author.get("handle") or author.get("name") or ""
    p=x.get(post) or None
    title=x.get("name") if source=="VibeGamer" else x.get("title")
    category=x.get("section") if source=="FableList" else (" / ".join(x.get("tags",[])) if source=="VibeGamer" else x.get("category"))
    play=x.get("url") if source=="FableList" else x.get("play_url") if source=="VibeGamer" else None
    repo=x.get("open_source_url") if source=="VibeGamer" else None
    return {"source":source,"source_id":str(x.get("slug") if source=="VibeGamer" else x.get("id",index)),
            "post_id":post_id(p),"post_url":p,"title":title or "",
            "title_zh":x.get("title_zh") or x.get("titleZh") or "",
            "category":category or "","author":str(author or ""),
            "play_url":play,"repo_url":repo,
            "source_url":source_url.replace("raw.githubusercontent.com/","github.com/").replace("/main/","/blob/main/",1)}

def fetch_json(url,max_bytes=8*1024*1024):
    if not url.startswith("https://raw.githubusercontent.com/"):
        raise ValueError("Source URL must be pinned to approved GitHub raw domain")
    req=Request(url,headers={"User-Agent":"awsome-games-research/1.0","Accept":"application/json"})
    with urlopen(req,timeout=25) as resp:
        raw=resp.read(max_bytes+1)
        if len(raw)>max_bytes:raise ValueError("Source exceeds size cap")
    return json.loads(raw)

def merge_entities(old_records,new_source_rows):
    """Union exact X post IDs; enrich provenance without overwriting reviewed claims."""
    records=[dict(x) for x in old_records]
    known={str(x["post_id"]):x for x in records if x.get("post_id")}
    added=0
    for x in new_source_rows:
        ident=x.get("post_id")
        if not ident:continue
        if ident not in known:
            d={"post_id":ident,"post_url":x.get("post_url"),"title":x.get("title") or "",
               "aliases":x.get("title_zh") or None,"creator":x.get("author") or None,
               "category":x.get("category") or None,"sources":"",
               "source_count":0,"source_ids":"",
               "play_url_count":0,"play_urls":[],"repository_url_count":0,"repository_urls":[],
               "work_id":None,"candidate_work_ids":None,"match_status":"UNRESOLVED",
               "confidence":"none","match_method":"incremental source post - no independent work verification",
               "kind_signal":"not reviewed","model_claim":"not checked","prompt_evidence":"not checked",
               "date":None,"likes_snapshot":None,"views_snapshot":None,
               "note":"Incrementally discovered, not verified as a game",
               "entity_id":"ENT-POST-"+ident,"entity_resolution_status":"POST_ONLY_UNRESOLVED",
               "candidate_group_id":None,"resolution_key":"post:"+ident}
            records.append(d);known[ident]=d;added+=1
        d=known[ident]
        # Merge only observation-level facts. Never rewrite work_id, model claim,
        # entity key, manually classified type or adjudicated confidence.
        prior_sources=set(q for q in re.split(r"\s*\+\s*|\n+",d.get("sources") or "") if q)
        new_source=x.get("source") or ""
        if new_source:prior_sources.add(new_source)
        d["sources"]=" + ".join(sorted(prior_sources))
        source_ids=set(q.strip() for q in re.split(r"\s*/\s*|\n+",d.get("source_ids") or "") if q.strip())
        ref=str(x.get("source") or "")+":"+str(x.get("source_id") or "")
        if ref!=":":source_ids.add(ref)
        d["source_ids"]=" / ".join(sorted(source_ids))
        d["source_count"]=max(int(d.get("source_count") or 0),len(source_ids))
        play=x.get("play_url")
        if isinstance(play,str) and play.startswith("https://") and "github.com/" not in play:
            urls=list(d.get("play_urls") or [])
            if play not in urls:urls.append(play)
            d["play_urls"]=urls
            d["play_url_count"]=len(urls)
            if d["entity_resolution_status"]=="POST_ONLY_UNRESOLVED":
                d["entity_resolution_status"]="PROVISIONAL_PLAYABLE_POST"
                d["resolution_key"]="play:"+play
        repo=x.get("repo_url")
        if isinstance(repo,str) and repo.startswith("https://github.com/"):
            repos=list(d.get("repository_urls") or [])
            if repo not in repos:repos.append(repo)
            d["repository_urls"]=repos
            d["repository_url_count"]=len(repos)
    return records,added

def _json_bytes(obj):
    return (json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode("utf-8")


def _digest_pair(sources,entities):
    return hashlib.sha256(_json_bytes(sources)+b"\n"+_json_bytes(entities)).hexdigest()


def load_current_pair(base=BASE,current=CURRENT):
    """Read a consistent, versioned source/entity pair via one atomic manifest."""
    pointer=current/"active.json"
    if pointer.exists():
        manifest=json.loads(pointer.read_text(encoding="utf-8"))
        relative=manifest.get("snapshot_dir")
        digest=manifest.get("sha256")
        if not isinstance(relative,str) or not re.fullmatch(r"snapshots/[0-9a-f]{64}",relative):
            raise ValueError("Invalid current research snapshot manifest path")
        if digest!=relative.rsplit("/",1)[-1]:
            raise ValueError("Snapshot manifest hash and directory disagree")
        folder=current/relative
        if folder.is_symlink() or not folder.is_dir():
            raise ValueError("Referenced research snapshot directory is missing or unsafe")
        sources=json.loads((folder/"sources.json").read_text(encoding="utf-8"))
        entities=json.loads((folder/"entities.json").read_text(encoding="utf-8"))
        if _digest_pair(sources,entities)!=digest:
            raise ValueError("Research source/entity snapshot checksum mismatch")
    else:
        existing=(current/"sources.json").exists(),(current/"entities.json").exists()
        if any(existing) and not all(existing):
            raise ValueError("Partial legacy research current snapshot: fail closed")
        folder=current if all(existing) else base
        sources=json.loads((folder/"sources.json").read_text(encoding="utf-8"))
        entities=json.loads((folder/"entities.json").read_text(encoding="utf-8"))
    if sources.get("schema_version")!=1 or entities.get("schema_version")!=1:
        raise ValueError("Unsupported research snapshot schema")
    if not isinstance(sources.get("records"),list) or not isinstance(entities.get("records"),list):
        raise ValueError("Invalid research record arrays")
    if sources.get("captured_at") and entities.get("captured_at") and sources["captured_at"]!=entities["captured_at"]:
        raise ValueError("Source/entity snapshot dates disagree")
    return sources,entities


def prepare(base=BASE,current=CURRENT,fetch=fetch_json,allow_shrink=False):
    previous,old=load_current_pair(base,current)
    prior=Counter(x["source"] for x in previous["records"])
    recs=[];info=[]
    for source,url in SOURCES:
        payload=fetch(url)
        entries=payload.get("entries") if source=="DramaSo" else payload
        if not isinstance(entries,list) or not entries:raise ValueError("Empty or invalid upstream JSON: "+source)
        unique=set()
        for i,x in enumerate(entries):
            r=normalize(source,x,i,url)
            k=r["source_id"]
            if not k or k in unique:raise ValueError("Duplicate or missing source ID: "+source+":"+str(k))
            unique.add(k);recs.append(r)
        if len(entries)<prior[source] and not allow_shrink:
            raise ValueError("Source shrank; require explicit --allow-shrink: "+source)
        info.append({"source":source,"url":url,"records":len(entries)})
    new_rows,new_count=merge_entities(old["records"],recs)
    captured=date.today().isoformat()
    new_source={"schema_version":1,"captured_at":captured,"snapshot_date":captured,
                "sources":info,"description":"Fact metadata only; snapshots do not verify model authorship.", "records":recs}
    new_entities={"schema_version":1,"captured_at":captured,"previous_sheet_snapshot":old.get("previous_sheet_snapshot","2026-11-16"),
                  "status":"provisional original posts, not certified distinct games",
                  "source_records_captured":len(recs),"records":new_rows}
    return new_source,new_entities,new_count

def write_json(target,content):
    target.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix=".research-stage-",dir=target.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            json.dump(content,f,ensure_ascii=False,separators=(",",":"))
            f.write("\n");f.flush();os.fsync(f.fileno())
        os.replace(temp,target)
    finally:
        if os.path.exists(temp):os.unlink(temp)

def publish_pair(sources,entities,target=CURRENT):
    """Write an immutable pair then atomically switch its active pointer.

    Readers see either the old complete version or the new complete version,
    never a mixed source/entity pair, including during process interruption.
    """
    if sources.get("captured_at")!=entities.get("captured_at"):
        raise ValueError("Cannot publish source/entity snapshots with different dates")
    digest=_digest_pair(sources,entities)
    snapshots=target/"snapshots"
    snapshots.mkdir(parents=True,exist_ok=True)
    name=snapshots/digest
    if not name.exists():
        with tempfile.TemporaryDirectory(prefix=".build-",dir=snapshots) as tmp:
            folder=Path(tmp)
            (folder/"sources.json").write_bytes(_json_bytes(sources))
            (folder/"entities.json").write_bytes(_json_bytes(entities))
            if _digest_pair(json.loads((folder/"sources.json").read_text()),
                            json.loads((folder/"entities.json").read_text()))!=digest:
                raise RuntimeError("Failed staged snapshot integrity")
            os.replace(folder,name)
    elif name.is_symlink() or not name.is_dir():
        raise RuntimeError("Snapshot content-addressed path is unsafe")
    # Active manifest is a single atomic replace, not two successive replacements.
    manifest={"schema_version":1,"snapshot_dir":"snapshots/"+digest,
              "sha256":digest,"captured_at":sources.get("captured_at")}
    write_json(target/"active.json",manifest)
    return name


def main():
    p=argparse.ArgumentParser(description=__doc__)
    g=p.add_mutually_exclusive_group()
    g.add_argument("--dry-run",action="store_true",help="Default: report only")
    g.add_argument("--write",action="store_true",help="Write to data/research/current/")
    p.add_argument("--allow-shrink",action="store_true",help="Accept deliberate source removal after manual review")
    args=p.parse_args()
    sources,entities,new=prepare(allow_shrink=args.allow_shrink)
    if args.write:
        publish_pair(sources,entities,CURRENT)
    print(json.dumps({"source_records":len(sources["records"]),"original_post_candidates":len(entities["records"]),
                      "new_x_post_ids":new,"written":args.write},ensure_ascii=False))

if __name__=="__main__":main()
