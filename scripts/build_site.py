#!/usr/bin/env python3
"""Create a permission-gated, sandboxed, size-bounded GitHub Pages export.

The catalog may list public source candidates without redistributing their files.
Publishing source snapshots is opt-in on a repository basis.
"""
from __future__ import annotations
import argparse
import json
import shutil
import sys
from pathlib import Path
from db import ROOT, connect
from build_catalog import export_catalog

APPROVALS = ROOT / 'config' / 'publication_approvals.json'


def publishable_repositories(config_path=None):
    config_path = config_path or APPROVALS
    data=json.loads(config_path.read_text(encoding='utf-8'))
    entries=data.get('approved_repositories',[])
    if not isinstance(entries,list) or any(not isinstance(e,str) for e in entries):
        raise ValueError('approved_repositories must be a list of GitHub owner/repo strings')
    return set(entries)


def build_site(include_unapproved=False, max_site_bytes=850*1024*1024):
    conn=connect()
    data=export_catalog(conn)
    conn.close()
    site=ROOT/'site'
    (site/'data').mkdir(parents=True,exist_ok=True)
    dest=site/'games'
    if dest.exists(): shutil.rmtree(dest)
    dest.mkdir(parents=True,exist_ok=True)
    approvals=publishable_repositories()
    copied=set()
    public_count=0
    for project in data['projects']:
        project['published_game_path']=''
        for repo in project['repositories']:
            name=repo['full_name']
            if not (include_unapproved or name in approvals): continue
            if repo.get('playable_status') not in ('entrypoint_found','smoke_test_passed'): continue
            path=repo.get('game_path') or ''
            if not path.startswith('games/_repos/') or '\\' in path or '..' in Path(path).parts: continue
            src=(ROOT/path).resolve()
            root=(ROOT/'games/_repos').resolve()
            if not src.is_relative_to(root) or not src.is_file(): continue
            base=root/name.replace('/','__')
            if not src.is_relative_to(base.resolve()): continue
            if name not in copied:
                target=dest/'_repos'/name.replace('/','__')
                shutil.copytree(base,target,symlinks=False,ignore=shutil.ignore_patterns('.DS_Store','*.log'))
                copied.add(name)
            if (site/path).is_file():
                project['published_game_path']=path
                public_count+=1
                break
    data['summary']['projects_published_for_play']=public_count
    data['summary']['repositories_published']=len(copied)
    data['publication_policy']='repository_opt_in'
    (site/'data/catalog.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    (site/'data/summary.json').write_text(json.dumps(data['summary'],ensure_ascii=False,indent=2),encoding='utf-8')
    (site/'.nojekyll').write_text('',encoding='utf-8')
    (site/'build-manifest.json').write_text(json.dumps({
        'generated_at':data['generated_at'],'repository_ref':data['repository_ref'],
        'projects':data['summary']['projects'],'repositories':data['summary']['repositories'],
        'projects_with_entrypoints':data['summary']['projects_with_html_entrypoints'],
        'playable_published':public_count,'repository_snapshots_published':sorted(copied),
        'preview_unapproved':include_unapproved,
    },ensure_ascii=False,indent=2),encoding='utf-8')
    total=sum(f.stat().st_size for f in site.rglob('*') if f.is_file())
    if total>max_site_bytes:
        # Never leave a build that could accidentally deploy above the configured limit.
        raise RuntimeError(f'Pages artifact is {total:,} bytes; cap is {max_site_bytes:,} bytes. Reduce approved sources.')
    return {'projects':data['summary']['projects'],'repos':data['summary']['repositories'],
            'published_games':public_count,'published_repos':len(copied),'site_bytes':total}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--preview-unapproved',action='store_true',help='LOCAL TEST ONLY: ignore publication approvals; do not deploy this output')
    ap.add_argument('--max-site-mb',type=int,default=850)
    args=ap.parse_args()
    if args.max_site_mb<1: ap.error('--max-site-mb must be >=1')
    result=build_site(args.preview_unapproved,args.max_site_mb*1024*1024)
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__': main()
