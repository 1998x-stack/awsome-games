#!/usr/bin/env python3
"""Clone indexed public repositories, inventory web assets and map game entrypoints.

This script never runs npm, shell scripts, build commands, downloaded binaries, or game code.
It copies the tracked source tree (minus VCS/dependency/cache/secrets) into games/_repos/.
"""
from __future__ import annotations
import argparse, hashlib, html.parser, json, mimetypes, os, re, shutil, subprocess, sys, tempfile, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import requests
from db import ROOT, connect, create_run, finish_run, log_error, now

CACHE = ROOT / '.cache' / 'repos'
DEST = ROOT / 'games' / '_repos'
OVERRIDES = json.loads((ROOT/'config/project_overrides.json').read_text(encoding='utf-8')).get('projects', {})
REPO_OVERRIDES = json.loads((ROOT/'config/repository_overrides.json').read_text(encoding='utf-8')).get('repositories', {})
SKIP_DIRS = {'.git','node_modules','.next','.nuxt','.turbo','.cache','.venv','venv','__pycache__','.pytest_cache','.mypy_cache','.ruff_cache','coverage','playwright-report','test-results'}
SECRET_NAMES = {'.env','.env.local','.env.production','.npmrc','.pypirc','id_rsa','id_ed25519','credentials.json','service-account.json'}
SECRET_SUFFIXES = {'.pem','.key','.p12','.pfx'}


def run(cmd, cwd=None, timeout=600, check=True):
    p = subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if check and p.returncode:
        raise RuntimeError(f"command failed ({p.returncode}): {' '.join(cmd)}\n{p.stderr[-1500:]}")
    return p


def api_metadata(full_name, session):
    url = f'https://api.github.com/repos/{full_name}'
    r = session.get(url, timeout=25)
    if r.status_code == 404: raise RuntimeError('GitHub repository not found or inaccessible (404)')
    if r.status_code in (403,429):
        return {'_warning':f'GitHub API rate limit/permission error ({r.status_code}); continuing with git clone and without API metadata'}
    r.raise_for_status(); j = r.json()
    license_data = j.get('license') or {}
    return {
      'default_branch': j.get('default_branch') or 'main', 'description': j.get('description') or '',
      'stars': j.get('stargazers_count'), 'forks': j.get('forks_count'), 'size': j.get('size'),
      'license_spdx': license_data.get('spdx_id') or 'NOASSERTION', 'license_name': license_data.get('name') or '',
      'is_fork': bool(j.get('fork')), 'archived': bool(j.get('archived')),
    }


def safe_rel_path(value):
    """Allow only unambiguous POSIX relative paths from a tracked Git index."""
    if not value or '\x00' in value or '\\' in value or re.match(r'^[A-Za-z]:', value):
        return None
    path = Path(value)
    if path.is_absolute() or any(part in ('..', '.', '') for part in value.split('/')):
        return None
    normal = path.as_posix()
    if normal in ('.', '') or normal.startswith('./') or '/./' in value:
        return None
    return normal


def should_skip(path: str, size: int, max_file_bytes: int):
    p = Path(path); parts = {x.lower() for x in p.parts}; name = p.name.lower()
    if parts & SKIP_DIRS: return True, 'excluded_directory'
    if name in SECRET_NAMES or name.startswith('.env.') or name.endswith(('.pem','.key','.p12','.pfx')): return True, 'sensitive_file'
    if name in ('.ds_store','thumbs.db') or name.endswith('.log'): return True, 'noise'
    if size > max_file_bytes: return True, 'file_too_large'
    return False, ''


def tracked_files(repo_dir: Path):
    p = run(['git','ls-files','-z'], cwd=repo_dir)
    return [x for x in p.stdout.split('\0') if x]


def repo_dir_name(full_name):
    return full_name.replace('/', '__').replace('\\','_')


def clone_one(full_name, force=False):
    cache = CACHE / repo_dir_name(full_name)
    CACHE.mkdir(parents=True, exist_ok=True)
    if force and cache.exists(): shutil.rmtree(cache)
    if (cache/'.git').exists():
        run(['git','fetch','--depth','1','origin'],cwd=cache,timeout=600)
        run(['git','reset','--hard','FETCH_HEAD'],cwd=cache,timeout=600)
    else:
        if cache.exists(): shutil.rmtree(cache)
        run(['git','clone','--depth','1','--filter=blob:none','--no-tags','--',f'https://github.com/{full_name}.git',str(cache)],timeout=900)
    sha = run(['git','rev-parse','HEAD'],cwd=cache).stdout.strip()
    branch = run(['git','branch','--show-current'],cwd=cache,check=False).stdout.strip()
    return cache, sha, branch


def copy_tracked_tree(full_name, repo_dir, max_file_bytes, max_total_bytes):
    """Stage tracked files and publish atomically; never follow source symlinks."""
    DEST.mkdir(parents=True,exist_ok=True)
    name = repo_dir_name(full_name)
    dest = DEST / name
    stage = Path(tempfile.mkdtemp(prefix=f'.partial-{name}-', dir=DEST))
    backup = DEST / f'.backup-{name}'
    files=[]; total=0; skipped={}
    root=repo_dir.resolve()
    try:
        for rel in tracked_files(repo_dir):
            safe = safe_rel_path(rel)
            if not safe:
                skipped['unsafe_path']=skipped.get('unsafe_path',0)+1; continue
            src = repo_dir / safe
            try:
                if not src.is_file() or src.is_symlink() or not src.resolve().is_relative_to(root):
                    skipped['unsafe_source']=skipped.get('unsafe_source',0)+1; continue
                size = src.stat().st_size
            except OSError:
                skipped['unreadable']=skipped.get('unreadable',0)+1; continue
            skip, reason = should_skip(safe,size,max_file_bytes)
            if skip:
                skipped[reason]=skipped.get(reason,0)+1; continue
            if total+size > max_total_bytes:
                skipped['repository_size_cap']=skipped.get('repository_size_cap',0)+1; continue
            target=stage/safe
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(src,target,follow_symlinks=False)
            total+=size
            with target.open('rb') as handle:
                digest=hashlib.file_digest(handle, 'sha256').hexdigest()
            files.append({'path':safe,'size':size,'sha256':digest,'extension':target.suffix.lower(),
                          'mime':mimetypes.guess_type(target.name)[0] or ''})
        if not files:
            raise RuntimeError('no safe tracked files copied; preserving previous snapshot')
        # Do not destroy the previous complete snapshot unless staging succeeded.
        if backup.exists():
            if not dest.exists(): backup.rename(dest)
            else: shutil.rmtree(backup)
        if dest.exists(): dest.rename(backup)
        try:
            stage.rename(dest)
        except Exception:
            if backup.exists(): backup.rename(dest)
            raise
        if backup.exists(): shutil.rmtree(backup)
        return dest,files,total,skipped
    finally:
        if stage.exists(): shutil.rmtree(stage)


class _AssetReferences(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.urls=[]
    def handle_starttag(self,tag,attrs):
        d=dict(attrs)
        if tag in ('script','img','audio','video','source','iframe') and d.get('src'):
            self.urls.append(d['src'])
        if tag=='link' and d.get('href'):
            self.urls.append(d['href'])


def missing_static_assets(repo_dir:Path, html_path:str):
    """Best-effort report for static relative resources; does not run third-party code."""
    path=repo_dir/html_path
    parser=_AssetReferences()
    try: parser.feed(path.read_text(encoding='utf-8',errors='replace'))
    except OSError: return ['unreadable_entrypoint']
    from urllib.parse import unquote,urlsplit
    missing=[]
    for ref in parser.urls:
        if not ref or ref.startswith(('#','//')): continue
        url=urlsplit(ref)
        if url.scheme or url.netloc: continue
        if ref.startswith('/'):
            missing.append('root-relative:'+ref[:120]); continue
        raw=unquote(url.path)
        # ../assets/image.png is valid when it stays inside the collected repo.
        if not raw or '\\' in raw or '\x00' in raw or re.match(r'^[A-Za-z]:',raw):
            missing.append('unsafe:'+ref[:120]); continue
        target=(path.parent/raw).resolve()
        if not target.is_relative_to(repo_dir.resolve()) or not target.is_file():
            missing.append(ref[:120])
    return list(dict.fromkeys(missing))


def tokens(text):
    text=(text or '').lower()
    return [x for x in re.split(r'[^a-z0-9]+',text) if len(x)>=3]


def choose_entry(project, html_paths, project_count):
    override = OVERRIDES.get(project['id']) or OVERRIDES.get(project['slug']) or {}
    explicit = override.get('entry_path') or project['entry_path']
    if explicit:
        # Never repair ../ or ./ by stripping characters; reject ambiguous paths.
        explicit = safe_rel_path(explicit)
        if explicit is None: return '', 'unsafe_explicit_entry'
        if explicit in html_paths: return explicit,'explicit_override' if override.get('entry_path') else 'source_link'
        return '', 'missing_explicit_entry'
    if not html_paths: return '', 'no_html_entrypoint'
    title_tokens = set(tokens(project['title']) + tokens(project['slug']))
    scored=[]
    for path in html_paths:
        low=path.lower(); base=Path(path).name.lower()
        score=0
        if base=='index.html': score+=24
        if '/' not in path: score+=20
        if any(x in low for x in ('/docs/','/test/','/tests/','/example/','/examples/','storybook')): score-=35
        if any(x in low for x in ('/games/','/game/','/public/')): score+=5
        path_tokens=set(tokens(path))
        overlap=title_tokens & path_tokens
        score += 18*len(overlap)
        scored.append((score,path))
    scored.sort(reverse=True)
    if project_count == 1 and len(scored)==1: return scored[0][1],'unique_html'
    if project_count > 1:
        # In a collection repository, a generic root index is not enough to identify a specific work.
        specific=[]
        for score,path in scored:
            overlap=title_tokens & set(tokens(path))
            if overlap: specific.append((len(overlap),score,path))
        specific.sort(reverse=True)
        if specific and (len(specific)==1 or specific[0][:2] > specific[1][:2]):
            return specific[0][2],'title_path_match'
        return '', 'ambiguous_html_entrypoints'
    if scored and scored[0][0]>=18 and (len(scored)==1 or scored[0][0]>scored[1][0]):
        return scored[0][1],'title_path_match'
    return '', 'ambiguous_html_entrypoints'


def process_repo(conn, run_id, repo_row, session, force, skip_api, max_file_bytes, max_total_bytes):
    full=repo_row['full_name']
    try:
        meta = {} if skip_api else api_metadata(full,session)
        cache,sha,branch = clone_one(full,force=force)
        dest,files,total,skipped = copy_tracked_tree(full,cache,max_file_bytes,max_total_bytes)
        updates={
          'clone_status':'cloned','clone_path':str(dest.relative_to(ROOT)).replace('\\','/'),
          'commit_sha':sha,'cloned_at':now(),'last_checked_at':now(),'error_message':'',
        }
        if meta and not meta.get('_warning'): updates.update({'default_branch':meta['default_branch'],'description':meta['description'],'stars':meta['stars'],'forks':meta['forks'],'repo_size_kb':meta['size'],'license_spdx':meta['license_spdx'],'license_name':meta['license_name'],'is_fork':int(meta['is_fork']),'archived':int(meta['archived'])})
        if meta.get('_warning'): updates['error_message']=meta['_warning']
        sql=','.join(f'{k}=?' for k in updates)
        conn.execute(f'UPDATE repositories SET {sql} WHERE id=?',(*updates.values(),repo_row['id']))
        conn.execute('DELETE FROM repository_files WHERE repository_id=?',(repo_row['id'],))
        for f in files:
            conn.execute('INSERT INTO repository_files(repository_id,relative_path,extension,mime_type,size_bytes,sha256,is_html_entry,copied) VALUES(?,?,?,?,?,?,?,1)',
              (repo_row['id'],f['path'],f['extension'],f['mime'],f['size'],f['sha256'],int(f['extension'] in ('.html','.htm'))))
        mappings=conn.execute('''SELECT pr.project_id,pr.entry_path,p.slug,p.title,p.id FROM project_repositories pr JOIN projects p ON p.id=pr.project_id WHERE pr.repository_id=?''',(repo_row['id'],)).fetchall()
        html_paths=[f['path'] for f in files if f['extension'] in ('.html','.htm')]
        selected=[]; mapping_count=len(mappings)
        for m in mappings:
            project={'id':m['project_id'],'slug':m['slug'],'title':m['title'],'entry_path':m['entry_path']}
            entry,confidence=choose_entry(project,html_paths,mapping_count)
            missing=missing_static_assets(dest,entry) if entry else []
            if entry and not missing:
                game_path=(Path('games')/'_repos'/repo_dir_name(full)/entry).as_posix()
                status='entrypoint_found'
                selected.append((m['project_id'],entry,game_path,confidence,status, ''))
            else:
                status='missing_assets' if missing else 'requires_build' if any(x in [f['path'] for f in files] for x in ('package.json','vite.config.js','vite.config.ts')) else 'needs_review'
                selected.append((m['project_id'],entry if missing else '', '',confidence,status, json.dumps(missing,ensure_ascii=False)[:2000] if missing else ''))
        for pid,entry,game_path,confidence,status,note in selected:
            conn.execute('UPDATE project_repositories SET entry_path=?,game_path=?,entry_confidence=?,playable_status=?,note=? WHERE project_id=? AND repository_id=?',
                         (entry,game_path,confidence,status,note,pid,repo_row['id']))
        # Aggregate across all linked repositories: a failed mirror must not hide a
        # separately imported and usable original source.
        for m in mappings:
            pid=m['project_id']
            statuses=[x[0] for x in conn.execute('SELECT playable_status FROM project_repositories WHERE project_id=?',(pid,))]
            best=('smoke_test_passed' if 'smoke_test_passed' in statuses else
                  'entrypoint_found' if 'entrypoint_found' in statuses else
                  'missing_assets' if 'missing_assets' in statuses else
                  'requires_build' if 'requires_build' in statuses else 'needs_review')
            conn.execute('UPDATE projects SET source_status=?,playable_status=?,updated_at=? WHERE id=?',('cloned',best,now(),pid))
        conn.commit()
        return {'repo':full,'status':'cloned','commit':sha,'files':len(files),'html_files':len(html_paths),'bytes':total,'selected_entrypoints':sum(1 for x in selected if x[4]=='entrypoint_found'),'skipped':skipped}
    except Exception as exc:
        conn.execute("UPDATE repositories SET clone_status='error',last_checked_at=?,error_message=? WHERE id=?",(now(),str(exc)[:3000],repo_row['id']))
        log_error(conn,run_id,full,'','clone_or_inventory',exc)
        conn.commit()
        return {'repo':full,'status':'error','error':str(exc)[:500]}


def main():
    ap=argparse.ArgumentParser(description='Clone indexed GitHub repos and map local game entrypoints')
    ap.add_argument('--repo',action='append',help='Only clone a specific owner/name; repeatable')
    ap.add_argument('--limit',type=int,default=0,help='Limit repositories for a smoke test')
    ap.add_argument('--force',action='store_true',help='Delete cached clones and clone again')
    ap.add_argument('--dry-run',action='store_true',help='List the repositories without cloning')
    ap.add_argument('--skip-api',action='store_true',help='Skip GitHub REST metadata calls; still uses git')
    ap.add_argument('--max-file-mb',type=int,default=80)
    ap.add_argument('--max-total-mb',type=int,default=800)
    args=ap.parse_args()
    conn=connect(); run_id=create_run(conn,'clone_repositories')
    if args.repo:
        rows=[]
        for name in args.repo:
            row=conn.execute('SELECT * FROM repositories WHERE lower(full_name)=lower(?)',(name,)).fetchone()
            if not row: print('NOT IN CATALOG:',name,file=sys.stderr)
            else: rows.append(row)
    else:
        rows=conn.execute('SELECT * FROM repositories ORDER BY CASE repo_role WHEN "collection" THEN 0 ELSE 1 END,full_name').fetchall()
    if args.limit < 0 or args.max_file_mb <= 0 or args.max_total_mb <= 0: ap.error('limits must be positive')
    if args.limit: rows=rows[:args.limit]
    print(f'Repositories selected: {len(rows)}')
    if args.dry_run:
        for r in rows: print(r['full_name'],r['repo_role'],r['clone_status'])
        finish_run(conn,run_id,'dry_run',repositories_seen=len(rows),notes='No network or filesystem changes made')
        return
    session=requests.Session(); session.headers.update({'User-Agent':'1998x-stack-awsome-games/1.0','Accept':'application/vnd.github+json'})
    if os.getenv('GITHUB_TOKEN'): session.headers['Authorization']='Bearer '+os.environ['GITHUB_TOKEN']
    results=[]
    for i,row in enumerate(rows,1):
        print(f'[{i}/{len(rows)}] {row["full_name"]}',flush=True)
        result=process_repo(conn,run_id,row,session,args.force,args.skip_api,args.max_file_mb*1024*1024,args.max_total_mb*1024*1024)
        results.append(result); print(json.dumps(result,ensure_ascii=False))
        time.sleep(0.25)
    cloned=sum(x['status']=='cloned' for x in results)
    playable=conn.execute("SELECT COUNT(DISTINCT project_id) FROM project_repositories WHERE playable_status='entrypoint_found'").fetchone()[0]
    errors=sum(x['status']=='error' for x in results)
    finish_run(conn,run_id,'partial' if errors else 'success',repositories_seen=len(rows),repositories_cloned=cloned,games_playable=playable,notes=f'{errors} repository errors; copied tracked source files only; no build scripts executed')
    conn.close()
    (ROOT/'data/collection_report.json').write_text(json.dumps({'generated_at':now(),'results':results,'repositories_selected':len(rows),'cloned':cloned,'errors':errors,'projects_with_entrypoint':playable},ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'\nFinished: {cloned}/{len(rows)} cloned; {playable} projects have HTML entrypoints; {errors} errors.')

if __name__=='__main__': main()
