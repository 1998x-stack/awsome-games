#!/usr/bin/env python3
"""Read all tracked Git blobs at a fixed commit; NEVER run upstream source code.

This script uses only read-only git plumbing. It does not install dependencies,
invoke npm, build, start a browser, clone, contact upstream, or approve licenses.
Binary/large/sensitive files are inventoried but never executed or interpreted.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import subprocess
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

HEX40=re.compile(r"^[0-9a-fA-F]{40}$")
REPO_NAME=re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9_.-]+$")
TEXT_SUFFIXES={
    ".html",".htm",".js",".mjs",".jsx",".ts",".tsx",".css",".scss",
    ".json",".jsonl",".md",".txt",".py",".sh",".bash",".zsh",".cs",
    ".xml",".yaml",".yml",".toml",".lock",".tsv",".csv",
    ".frag",".vert",".glsl",".wgsl",".svg",".gitignore",".gitattributes",
}
LICENSE_NAMES={"license","license.md","license.txt","copying","copying.md",
               "notice","notice.md","copyright"}
SENSITIVE_NAMES={".env",".npmrc",".pypirc","credentials.json","service-account.json",
                 "id_rsa","id_ed25519"}
SENSITIVE_SUFFIXES={".pem",".p12",".pfx",".key"}
SCANS={
    "fetch_call":rb"\bfetch\s*\(",
    "websocket":rb"\bWebSocket\s*\(",
    "webrtc":rb"\bRTCPeerConnection\b",
    "microphone":rb"\bgetUserMedia\b",
    "xhr":rb"\bXMLHttpRequest\b",
    "send_beacon":rb"\bsendBeacon\b",
    "dynamic_import":rb"\bimport\s*\(",
    "eval":rb"\beval\s*\(",
    "new_function":rb"\bnew\s+Function\s*\(",
    "service_worker":rb"\bserviceWorker\b",
    "local_storage":rb"\blocalStorage\b",
    "iframe":rb"<iframe\b",
    "script_src":rb"<script\b[^>]*\bsrc\s*=",
    "importmap":rb"type\s*=\s*[\x22\x27]importmap",
}
COMPILED={key:re.compile(p,re.I) for key,p in SCANS.items()}
URL_RE=re.compile(rb"https?://[^\s\x22\x27<>\)\]}]+",re.I)
LFS_PREFIX=b"version https://git-lfs.github.com/spec/v1"
DEFAULT_MAX=16*1024*1024


def git(repo:Path,*args:str,timeout=60)->bytes:
    cp=subprocess.run(["git","-C",str(repo),*args],
        stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        timeout=timeout,check=False,env={**os.environ,"GIT_OPTIONAL_LOCKS":"0"})
    if cp.returncode:
        raise RuntimeError("Read-only Git command failed: "+args[0]+"; "+
                           cp.stderr.decode("utf-8","replace")[:800])
    return cp.stdout


def classify_path(path:str,mode:str,size:int,max_file_bytes:int)->str:
    name=Path(path).name.lower()
    suffix=Path(path).suffix.lower()
    if mode=="120000":
        return "SYMLINK_METADATA_ONLY"
    if name in SENSITIVE_NAMES or suffix in SENSITIVE_SUFFIXES or name.startswith(".env"):
        return "SENSITIVE_METADATA_ONLY"
    text=(suffix in TEXT_SUFFIXES or name in LICENSE_NAMES or
          name.startswith(("readme","changelog","license")))
    if not text:
        return "BINARY_OR_UNKNOWN_METADATA_ONLY"
    if size>max_file_bytes:
        return "TOO_LARGE_TEXT_METADATA_ONLY"
    return "TEXT_STATIC_SCAN"


def scan_git_repository(root:Path,repository_full_name:str,commit_sha:str,
                        max_file_bytes:int=DEFAULT_MAX)->dict:
    if not REPO_NAME.fullmatch(repository_full_name):
        raise ValueError("Invalid repository full name")
    if not HEX40.fullmatch(commit_sha):
        raise ValueError("Expected a pinned full 40-digit SHA")
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Source directory missing or symlinked")
    root=root.resolve(strict=True)
    head=git(root,"rev-parse","HEAD").decode("ascii").strip()
    if head.lower()!=commit_sha.lower():
        raise ValueError("Local HEAD is not the reviewed immutable commit")
    raw=git(root,"ls-tree","-r","-z",commit_sha)
    items=[]
    counts=Counter()
    network_hosts=Counter()
    all_hits=Counter()
    dependencies=[]
    total_size=0
    for row in raw.split(b"\x00"):
        if not row:continue
        try:
            prefix,raw_path=row.split(b"\t",1)
            mode,kind,sha=prefix.decode("ascii").split(" ")
        except (ValueError,UnicodeDecodeError) as exc:
            raise ValueError("Unexpected Git tree format") from exc
        path=raw_path.decode("utf-8","replace")
        if kind!="blob":
            counts["UNSUPPORTED_GIT_OBJECT"]+=1
            items.append({"path":path,"type":kind,"status":"UNSUPPORTED_GIT_OBJECT"})
            continue
        if not HEX40.fullmatch(sha):
            raise ValueError("Invalid Git blob SHA")
        size=int(git(root,"cat-file","-s",sha).decode("ascii").strip())
        total_size+=size
        classification=classify_path(path,mode,size,max_file_bytes)
        item={"path":path,"git_blob_sha":sha,"mode":mode,"size_bytes":size,
              "status":classification}
        if classification=="TEXT_STATIC_SCAN":
            data=git(root,"cat-file","blob",sha,timeout=120)
            if len(data)!=size:
                raise RuntimeError("Git blob read length mismatch")
            item["sha256"]=hashlib.sha256(data).hexdigest()
            item["lfs_pointer"]=data.startswith(LFS_PREFIX)
            item["line_count"]=data.count(b"\n")+1
            hits={key:len(rx.findall(data)) for key,rx in COMPILED.items()}
            item["indicators"]={key:n for key,n in hits.items() if n}
            all_hits.update(item["indicators"])
            urls=[]
            for match in URL_RE.finditer(data):
                url=match.group(0).decode("utf-8","replace").rstrip(",;\\")
                try:
                    host=urlsplit(url).hostname
                except ValueError:
                    host=None
                if host and host.lower() not in ("www.w3.org","git-lfs.github.com"):
                    urls.append(host.lower())
            item["url_hosts"]=sorted(set(urls))[:40]
            network_hosts.update(item["url_hosts"])
            if path.endswith("package.json") or path=="package.json":
                try:
                    pkg=json.loads(data)
                    if isinstance(pkg,dict):
                        dependencies.append({"path":path,
                            "dependencies":sorted((pkg.get("dependencies") or {}).keys()),
                            "devDependencies":sorted((pkg.get("devDependencies") or {}).keys()),
                            "build_scripts":sorted((pkg.get("scripts") or {}).keys())})
                except (ValueError,UnicodeDecodeError,TypeError,AttributeError):
                    item["package_manifest_status"]="PARSE_FAILED"
        counts[classification]+=1
        items.append(item)
    return {"schema_version":1,"repository_full_name":repository_full_name,
            "pinned_commit_sha":commit_sha.lower(),"pinned_head_verified":True,
            "source_kind":"LOCAL_PINNED_GIT_OBJECTS_READ_ONLY",
            "warning":"Static scan only; never executed source, tested gameplay, resolved transitive dependencies or approved media/license rights.",
            "audit_status":"ALL_TEXT_FILES_SCANNED" if not counts["TOO_LARGE_TEXT_METADATA_ONLY"] else "PARTIAL_TEXT_SCAN",
            "files_total":len(items),"total_tracked_bytes":total_size,
            "status_counts":dict(sorted(counts.items())),
            "potential_external_hosts":dict(sorted(network_hosts.items())),
            "lexical_indicators":dict(sorted(all_hits.items())),
            "package_manifests":dependencies,
            "files":items}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True,
                   help="Already acquired local repository; this tool never clones or fetches")
    p.add_argument("--repo",required=True,help="owner/name")
    p.add_argument("--commit",required=True,help="Pinned immutable 40-hex commit")
    p.add_argument("--max-file-bytes",type=int,default=DEFAULT_MAX)
    p.add_argument("--output",type=Path,help="Output path for explicit --write")
    p.add_argument("--write",action="store_true")
    args=p.parse_args()
    if args.max_file_bytes<=0 or args.max_file_bytes>64*1024*1024:
        p.error("max-file-bytes must be within (0,64MiB]")
    report=scan_git_repository(args.root,args.repo,args.commit,args.max_file_bytes)
    if args.write:
        if args.output is None:p.error("--write requires an explicit --output")
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"repository":report["repository_full_name"],
        "sha":report["pinned_commit_sha"],"files":report["files_total"],
        "statuses":report["status_counts"],"written":args.write,
        "audit_status":report["audit_status"]},ensure_ascii=False))


if __name__=="__main__":
    main()
