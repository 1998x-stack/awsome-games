#!/usr/bin/env python3
"""Run structural and path-safety checks without executing any game code."""
import json, sys
from pathlib import Path
from db import ROOT, connect

def main():
    conn=connect(); problems=[]
    integrity=conn.execute('PRAGMA integrity_check').fetchone()[0]
    if integrity!='ok': problems.append('SQLite integrity_check failed: '+str(integrity))
    fk=conn.execute('PRAGMA foreign_key_check').fetchall()
    if fk: problems.append(f'{len(fk)} foreign-key violations')
    projects=conn.execute('SELECT COUNT(*) FROM projects').fetchone()[0]
    repos=conn.execute('SELECT COUNT(*) FROM repositories').fetchone()[0]
    mappings=conn.execute('SELECT COUNT(*) FROM project_repositories').fetchone()[0]
    if projects==0: problems.append('No projects found')
    for row in conn.execute("SELECT p.id,p.title,pr.entry_path,pr.game_path FROM project_repositories pr JOIN projects p ON p.id=pr.project_id WHERE pr.playable_status='entrypoint_found'"):
        if not row['game_path']: problems.append(f"{row['title']}: entrypoint_found but game_path is empty")
        elif not (ROOT/row['game_path']).is_file(): problems.append(f"{row['title']}: missing game file {row['game_path']}")
    for row in conn.execute('SELECT full_name FROM repositories'):
        if row['full_name'].count('/')!=1: problems.append('Invalid repository full_name: '+row['full_name'])
    catalog=ROOT/'data/catalog.json'
    if catalog.exists():
        data=json.loads(catalog.read_text(encoding='utf-8'))
        if len(data.get('projects',[]))!=projects: problems.append('catalog.json project count does not match SQLite')
    else: problems.append('data/catalog.json is missing; run build_catalog.py')
    # Ensure generated game snapshot does not contain obvious secret filenames.
    game_root=ROOT/'games/_repos'
    if game_root.exists():
        for p in game_root.rglob('*'):
            if p.is_file() and (p.name.lower().startswith('.env') or p.suffix.lower() in ('.pem','.key','.p12','.pfx')):
                problems.append('Sensitive-looking file copied into game snapshot: '+str(p.relative_to(ROOT)))
    print(json.dumps({'sqlite_integrity':integrity,'projects':projects,'repositories':repos,'project_repository_mappings':mappings,'problems':problems},ensure_ascii=False,indent=2))
    conn.close()
    if problems: sys.exit(1)

if __name__=='__main__': main()
