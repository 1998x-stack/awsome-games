#!/usr/bin/env python3
"""Import the reviewed seed snapshot into SQLite and export machine-readable catalog files."""
from __future__ import annotations
import argparse, csv, json, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path
from db import ROOT, DB_PATH, connect, seed_database, now
from research_pipeline import ingest as ingest_research, project_links


def backup_database(path: Path = DB_PATH):
    """Copy the authoritative SQLite to a verified snapshot before destroying it.

    `--fresh` drops locally collected clone metadata and any curated rows that
    are not reproducible from the checked-in seeds. Never do that without a
    recoverable, integrity-checked copy of the current database.
    """
    if not path.exists():
        return None
    backup_dir = path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"{path.stem}-{stamp}{path.suffix}"
    source = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    destination = sqlite3.connect(target)
    try:
        # sqlite backup API is WAL-safe; a plain file copy is not.
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    probe = sqlite3.connect(target)
    try:
        if probe.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Fresh-database backup failed integrity check; refusing to recreate")
    finally:
        probe.close()
    return target


def export_catalog(conn):
    projects=[]
    known_research=project_links(conn) if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='research_project_links'").fetchone() else {}
    rows=conn.execute("SELECT * FROM projects ORDER BY title COLLATE NOCASE").fetchall()
    for p in rows:
        cats=conn.execute("""SELECT c.id,c.name,c.group_name,pc.is_primary,pc.raw_label FROM project_categories pc JOIN categories c ON c.id=pc.category_id WHERE pc.project_id=? ORDER BY pc.is_primary DESC,c.name""",(p['id'],)).fetchall()
        repos=conn.execute("""SELECT r.full_name,r.html_url,r.clone_status,r.license_spdx,r.license_name,r.commit_sha,
          pr.relation_type,pr.entry_path,pr.game_path,pr.entry_confidence,pr.playable_status,pr.is_primary
          FROM project_repositories pr JOIN repositories r ON r.id=pr.repository_id WHERE pr.project_id=? ORDER BY pr.is_primary DESC,r.full_name""",(p['id'],)).fetchall()
        links=conn.execute("SELECT link_type,url,label FROM links WHERE project_id=? ORDER BY link_type,url",(p['id'],)).fetchall()
        prompts=conn.execute("SELECT status,prompt_url FROM prompts WHERE project_id=?",(p['id'],)).fetchall()
        evidence=conn.execute("""SELECT es.name,es.url,pe.evidence_type,pe.confidence,pe.note FROM project_evidence pe JOIN evidence_sources es ON es.id=pe.evidence_source_id WHERE pe.project_id=?""",(p['id'],)).fetchall()
        demos=[x['url'] for x in links if x['link_type']=='demo']
        author_posts=[x['url'] for x in links if x['link_type']=='author_post']
        local_repo=next((x for x in repos if x['game_path'] and x['playable_status'] in ('local_playable','entrypoint_found')),None)
        projects.append({
          'id':p['id'],'slug':p['slug'],'title':p['title'],'original_title':p['original_title'],
          'description':p['description'],'content_type':p['content_type'],'model_claim':p['model_claim'],
          'model_version':p['model_version'],'model_confidence':p['model_confidence'],'creator':p['creator'],
          'published_at':p['published_at'],'prompt_status':p['prompt_status'],'source_status':p['source_status'],
          'playable_status':p['playable_status'],'featured':bool(p['featured']),
          'categories':[{'id':c['id'],'name':c['name'],'group':c['group_name'],'primary':bool(c['is_primary']),'raw_label':c['raw_label']} for c in cats],
          'repositories':[dict(x) for x in repos], 'links':[dict(x) for x in links],
          'demos':demos,'author_posts':author_posts,'prompts':[dict(x) for x in prompts],
          'evidence':[dict(x) for x in evidence],
          'local_game_path':local_repo['game_path'] if local_repo else '',
          'local_entry_path':local_repo['entry_path'] if local_repo else '',
          'research_work_ids':known_research.get(p['id'],[])
        })
    cats=[dict(x) for x in conn.execute("SELECT * FROM categories ORDER BY group_name,name")]
    repo_rows=[dict(x) for x in conn.execute("SELECT * FROM repositories ORDER BY full_name")]
    summary={
      'generated_at':now(),'projects':len(projects),'repositories':len(repo_rows),
      'projects_with_repository':sum(bool(x['repositories']) for x in projects),
      'projects_with_demo':sum(bool(x['demos']) for x in projects),
      'projects_with_html_entrypoints':sum(bool(x['local_game_path']) for x in projects),
      'projects_smoke_test_passed':sum(x['playable_status']=='smoke_test_passed' for x in projects),
      'by_model':{},'by_category':{},'by_source_status':{}
    }
    for p in projects:
        summary['by_model'][p['model_version']]=summary['by_model'].get(p['model_version'],0)+1
        summary['by_source_status'][p['source_status']]=summary['by_source_status'].get(p['source_status'],0)+1
        for c in p['categories']:
            summary['by_category'][c['name']]=summary['by_category'].get(c['name'],0)+1
    
    import os, subprocess
    revision=os.getenv('GITHUB_SHA','')
    if not revision:
        try: revision=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,text=True,capture_output=True,check=True).stdout.strip()
        except Exception: revision='main'
    data={'generated_at':summary['generated_at'],'repository_ref':revision,'summary':summary,'categories':cats,'projects':projects}
    (ROOT/'data/catalog.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    (ROOT/'data/summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    with (ROOT/'data/projects.csv').open('w',encoding='utf-8-sig',newline='') as f:
        cols=['id','slug','title','model_version','content_type','categories','creator','source_status','playable_status','repositories','demos']
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
        for p in projects:
            w.writerow({'id':p['id'],'slug':p['slug'],'title':p['title'],'model_version':p['model_version'],
              'content_type':p['content_type'],'categories':'; '.join(c['name'] for c in p['categories']),
              'creator':p['creator'],'source_status':p['source_status'],'playable_status':p['playable_status'],
              'repositories':'; '.join(r['html_url'] for r in p['repositories']),'demos':'; '.join(p['demos'])})
    with (ROOT/'data/repositories.csv').open('w',encoding='utf-8-sig',newline='') as f:
        cols=['full_name','html_url','repo_role','clone_status','default_branch','license_spdx','commit_sha','clone_path','project_count']
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
        for r in repo_rows:
            n=conn.execute('SELECT COUNT(*) FROM project_repositories WHERE repository_id=?',(r['id'],)).fetchone()[0]
            w.writerow({**{k:r[k] for k in cols if k in r},'project_count':n})
    return data


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--seed',type=Path,default=ROOT/'data/seeds/legacy_projects.jsonl')
    ap.add_argument('--check',action='store_true')
    ap.add_argument('--fresh',action='store_true',help='Recreate the SQLite database from seed; removes local clone metadata')
    args=ap.parse_args()
    if args.fresh and DB_PATH.exists():
        backup = backup_database(DB_PATH)
        print(json.dumps({"fresh_backup": str(backup)}, ensure_ascii=False))
        DB_PATH.unlink()
        for ext in ('-wal','-shm'):
            Path(str(DB_PATH)+ext).unlink(missing_ok=True)
    conn=connect()
    imported=seed_database(conn,args.seed)
    research_stats=ingest_research(conn)
    if args.check:
        result=conn.execute('PRAGMA integrity_check').fetchone()[0]
        fk=conn.execute('PRAGMA foreign_key_check').fetchall()
        print(json.dumps({'integrity_check':result,'foreign_key_errors':len(fk),'projects':conn.execute('SELECT COUNT(*) FROM projects').fetchone()[0]},ensure_ascii=False,indent=2))
        if result!='ok' or fk: sys.exit(1)
    data=export_catalog(conn)
    conn.close()
    print(json.dumps({'seed_rows_processed':imported,'research':research_stats,**data['summary']},ensure_ascii=False,indent=2))

if __name__=='__main__': main()
