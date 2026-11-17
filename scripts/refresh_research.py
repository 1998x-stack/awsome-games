#!/usr/bin/env python3
"""Update evidence metadata only, never clone or run third-party code.

Dry-run by default; explicit --write creates data/research/current/{sources,entities}.json.
Original v1 snapshots are immutable. Importer uses current files when available.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import shutil
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path
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
    m=re.search(r"/status/([0-9]+)",str(url or ""))
    return m.group(1) if m else None

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
    records=[dict(x) for x in old_records]
    known={str(x["post_id"]):x for x in records}
    count=0
    for x in new_source_rows:
        ident=x.get("post_id")
        if not ident or ident in known:continue
        d={"post_id":ident,"post_url":x.get("post_url"),"title":x.get("title") or "",
           "aliases":x.get("title_zh") or None,"creator":x.get("author") or None,
           "category":x.get("category") or None,"sources":x.get("source"),
           "source_count":1,"source_ids":str(x.get("source"))+":"+str(x.get("source_id")),
           "play_url_count":0,"play_urls":[],"repository_url_count":0,"repository_urls":[],
           "work_id":None,"candidate_work_ids":None,"match_status":"UNRESOLVED",
           "confidence":"none","match_method":"incremental source post - no independent work verification",
           "kind_signal":"not reviewed","model_claim":"not checked","prompt_evidence":"not checked",
           "date":None,"likes_snapshot":None,"views_snapshot":None,"note":"Incrementally discovered; not verified as game",
           "entity_id":"ENT-POST-"+ident,"entity_resolution_status":"POST_ONLY_UNRESOLVED",
           "candidate_group_id":None,"resolution_key":"post:"+ident}
        play=x.get("play_url")
        if play and isinstance(play,str) and play.startswith("https://") and "github.com/" not in play:
            d.update(play_url_count=1,play_urls=[play],entity_resolution_status="PROVISIONAL_PLAYABLE_POST",resolution_key="play:"+play)
        repo=x.get("repo_url")
        if repo and isinstance(repo,str) and repo.startswith("https://github.com/"):
            d.update(repository_url_count=1,repository_urls=[repo])
        records.append(d);known[ident]=d;count+=1
    return records,count

def prepare(base=BASE,current=CURRENT,fetch=fetch_json,allow_shrink=False):
    previous=json.loads(((current/"sources.json") if (current/"sources.json").is_file() else base/"sources.json").read_text())
    old=json.loads(((current/"entities.json") if (current/"entities.json").is_file() else base/"entities.json").read_text())
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
    """Stage and validate both files, then replace them with rollback on failure."""
    target.mkdir(parents=True,exist_ok=True)
    names=("sources.json","entities.json")
    with tempfile.TemporaryDirectory(prefix=".research-txn-",dir=target) as tmp:
        stage=Path(tmp)
        for name,obj in zip(names,(sources,entities)):
            write_json(stage/name,obj)
            json.loads((stage/name).read_text(encoding="utf-8"))
        for name in names:
            original=target/name
            if original.is_file():shutil.copy2(original,stage/("backup-"+name))
        replaced=[]
        try:
            for name in names:
                os.replace(stage/name,target/name)
                replaced.append(name)
        except BaseException:
            for name in reversed(replaced):
                original=target/name
                backup=stage/("backup-"+name)
                if backup.exists():os.replace(backup,original)
                else:original.unlink(missing_ok=True)
            raise

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
