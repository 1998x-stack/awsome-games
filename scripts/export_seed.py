#!/usr/bin/env python3
"""Rebuild a stable-ID catalog seed from the committed SQLite snapshot.

This is a recovery export, not a verbatim copy of the original community data.
"""
import argparse
import json
import sqlite3
from pathlib import Path
from db import ROOT


def export_seed(database: Path, destination: Path) -> int:
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    result = []
    for p in conn.execute('SELECT * FROM projects ORDER BY id').fetchall():
        project_id = p['id']
        categories = conn.execute('SELECT raw_label FROM project_categories WHERE project_id=? ORDER BY is_primary DESC, category_id', (project_id,)).fetchall()
        repositories = conn.execute("""SELECT r.full_name, pr.relation_type FROM project_repositories pr
              JOIN repositories r ON r.id=pr.repository_id WHERE pr.project_id=?
              ORDER BY pr.is_primary DESC, r.full_name""", (project_id,)).fetchall()
        links = conn.execute('SELECT link_type,url FROM links WHERE project_id=? ORDER BY link_type,url', (project_id,)).fetchall()
        evidence = conn.execute("""SELECT e.url FROM project_evidence pe JOIN evidence_sources e
              ON pe.evidence_source_id=e.id WHERE pe.project_id=? ORDER BY e.url""", (project_id,)).fetchall()
        prompts = conn.execute("SELECT prompt_url FROM prompts WHERE project_id=? AND prompt_url<>'' ORDER BY prompt_url", (project_id,)).fetchall()
        srcs = [x['url'] for x in evidence]
        plays = [x['url'] for x in links if x['link_type']=='demo']
        posts = [x['url'] for x in links if x['link_type']=='author_post']
        result.append({
            'project_id': project_id, 'title': p['title'], 'description': p['description'] or '',
            'model': p['model_claim'], 'category': ';'.join(x['raw_label'] for x in categories if x['raw_label']),
            'creator': p['creator'] or '', 'publish_date': p['published_at'] or '',
            'repos': [x['full_name'] for x in repositories],
            'repo_role': repositories[0]['relation_type'] if repositories else '',
            'plays': plays, 'posts': posts, 'sources': srcs,
            'prompt_urls': [x['prompt_url'] for x in prompts],
            'prompt_status': p['prompt_status'] or '',
            'evidence': ['sqlite_snapshot_reconstruction'],
            '_reconstruction_origin': 'data/catalog.sqlite',
        })
    conn.close()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(''.join(json.dumps(x, ensure_ascii=False, sort_keys=True) + '\n' for x in result), encoding='utf-8')
    return len(result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', type=Path, default=ROOT/'data/catalog.sqlite')
    parser.add_argument('--output', type=Path, default=ROOT/'data/seeds/legacy_projects.jsonl')
    args = parser.parse_args()
    count = export_seed(args.database, args.output)
    print(f'Exported {count} snapshot records to {args.output}')
