#!/usr/bin/env python3
"""Claude Fable projects research database. Standard library + requests + beautifulsoup4.

Offline mode compiles a cited 72-game seed. Online mode refreshes public community
indices and retains raw provenance. Never executes collected application code.
"""
from __future__ import annotations
import argparse, csv, hashlib, html, json, os, re, shutil, sqlite3, subprocess, sys, time, unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
RAW = DATA / 'raw'
SOURCE_CSV = 'https://raw.githubusercontent.com/ygx2378/awesome-fable-5-2-games/master/data/games.csv'
AWESOME_BASE = 'https://raw.githubusercontent.com/fengyiqicoder/awesome-fable-5.2/main/all/'
CASES_JSON = 'https://raw.githubusercontent.com/apimodels/claude-fable-5-2-prompts/main/data/cases.json'
SANDBASE_JSON = 'https://raw.githubusercontent.com/sandbase-lab/awesome-fable-5-2/main/data/videos.json'
ARCADE_README = 'https://raw.githubusercontent.com/sorrycc/fable-arcade/main/README.md'
AWESOME_FILES = {
    'games.md': 'game', '3d-worlds.md': '3d_world', 'web-and-tools.md': 'web_tool',
    'animation.md': 'animation', 'video-demos.md': 'video_only',
}
CATALOGS = [
    ('awesome-fable-5.2', 'https://github.com/fengyiqicoder/awesome-fable-5.2', 'Live + video index'),
    ('awesome-fable-5-2-games', 'https://github.com/ygx2378/awesome-fable-5-2-games', 'Game source repository index'),
    ('fable-arcade', 'https://github.com/sorrycc/fable-arcade', 'Fable 5.1 one-shot source code'),
    ('claude-fable-5-2-prompts', 'https://github.com/apimodels/claude-fable-5-2-prompts', 'Prompt provenance / 145 cases'),
    ('awesome-fable-5-2', 'https://github.com/sandbase-lab/awesome-fable-5-2', '400 community video records'),
    ('vibegamer', 'https://vibegamer.io/made-with/claude-fable-5-2', 'Playable game aggregator'),
    ('aiarcade', 'https://aiarcade.games/', 'Browser game host and mirrors'),
    ('fablelist', 'https://fablelist.000ooo.ooo/', 'Searchable community directory'),
    ('mia-76-html', 'https://github.com/MiaAI-Lab/Claude-Fable-5.2-HTML-Files', '76 self-contained HTML works + original prompts'),
    ('awesome-vibegamer', 'https://github.com/ummydev/awesome-claude-fable-games', 'Games index and prompts'),
]


def norm(x: str) -> str:
    x = unicodedata.normalize('NFKC', (x or '').casefold())
    return re.sub(r'[^\w]+', '', x, flags=re.U)


def normalize_url(s: str) -> str:
    s=(s or '').strip()
    if not s: return ''
    try:
        q=urlparse(s)
        host=q.netloc.lower().removeprefix('www.')
        path=re.sub(r'/+', '/', q.path).rstrip('/')
        # social URLs: only the original post is identity; omit tracker and fragments
        if host in ('x.com', 'twitter.com'):
            host='x.com'
            # allow status /1234 canonical, no trailing /photo/1 etc
            match=re.search(r'/([^/]+)/status/(\d+)', path)
            if match: path=f'/{match.group(1).casefold()}/status/{match.group(2)}'
        query = '' if host not in ('claude.ai',) else urlencode([(k,v) for k,v in parse_qsl(q.query) if k not in ('ref','utm_source','utm_medium')])
        return urlunparse((q.scheme.lower() or 'https', host, path, '', query, ''))
    except Exception:
        return s


def post_id(url:str)->str:
    m=re.search(r'(?:x\.com|twitter\.com)/[^/]+/status/(\d+)',url or '')
    return m.group(1) if m else ''


def clean(s:str)->str:
    return re.sub(r'\s+',' ',html.unescape(s or '')).strip()


def item(title, category, model, source, **kw):
    return dict(title=clean(title), category=category, model=model, source_url=source,
                repo=kw.get('repo',''), repo_role=kw.get('repo_role',''),
                play_url=kw.get('play_url',''), post_url=kw.get('post_url',''),
                creator=kw.get('creator',''), description=clean(kw.get('description','')),
                tech_stack=clean(kw.get('tech_stack','')), delivery=clean(kw.get('delivery','')),
                prompt_status=kw.get('prompt_status',''), prompt_url=kw.get('prompt_url',''),
                publish_date=kw.get('publish_date',''), evidence_kind=kw.get('evidence_kind','community_index'),
                raw_source=kw.get('raw_source',''), link_kind=kw.get('link_kind',''))


def load_seed():
    items=[]
    src='https://github.com/ygx2378/awesome-fable-5-2-games/blob/master/data/games.csv'
    for line in (ROOT/'data/seeds/games_52.tsv').read_text(encoding='utf8').splitlines():
        if not line.strip(): continue
        title,repo,play,category=line.split('|')
        items.append(item(title,category,'claude-fable-5-2',src,repo=repo,
                          repo_role='community_indexed_repository',play_url=play,evidence_kind='community_index'))
    src='https://github.com/sorrycc/fable-arcade/blob/main/README.md'
    for line in (ROOT/'data/seeds/games_51.tsv').read_text(encoding='utf8').splitlines():
        if not line.strip(): continue
        title,slug,day=line.split('|')
        items.append(item(title,'game','claude-fable-5-1',src,repo='sorrycc/fable-arcade',
                          repo_role='collection_with_original_game_files',
                          play_url=f'https://sorrycc.github.io/fable-arcade/games/{slug}/',
                          publish_date=day,evidence_kind='repository_documentation'))
    # High-profile live-only works. Reconcile with live index on online refresh.
    src='https://github.com/fengyiqicoder/awesome-fable-5.2'
    special=[
      ('Starry Nightrider','https://starrynightrider.com','https://x.com/ebbyamir/status/2120284261089673376','@ebbyamir','game'),
      ('Oil Paint','https://patch.gg/blendi/oil-paint','https://x.com/BlendiByl/status/2120341251178594532','@BlendiByl','game'),
      ('CROSSTOWN','https://nyc.somethingbig.ai/','https://x.com/mattshumer_/status/2120282133503820150','@mattshumer_','game'),
      ('What the Water Keeps','https://what-the-water-keeps.vercel.app/','https://x.com/kevin_t_ngo/status/2119868968307695818','@kevin_t_ngo','game'),
      ('Tennis','https://tennis.sixfingerpunch.com/','https://x.com/photonstorm/status/2120330010112434313','@photonstorm','game'),
    ]
    for t,p,s,c,kind in special:
        items.append(item(t,kind,'claude-fable-5-2',src,play_url=p,post_url=s,creator=c,evidence_kind='community_index'))
    # A 76-work self-contained HTML research collection, each with a published prompt.
    # These are individual works within one GitHub repository, not 76 distinct repos.
    ownerrepo='MiaAI-Lab/Claude-Fable-5.2-HTML-Files'
    for filename in (ROOT/'data/seeds/mia_html_52.txt').read_text(encoding='utf8').splitlines():
        if not filename or not filename.endswith('.html'):continue
        title=re.sub(r'^\d+-','',filename[:-5]).replace('-',' ').title()
        src=f'https://github.com/{ownerrepo}/blob/main/{filename}'
        items.append(item(title,'single_html_visual_study','claude-fable-5-2',src,repo=ownerrepo,
                          repo_role='collection_with_original_html_and_prompt',
                          prompt_status='published',
                          prompt_url=f'https://github.com/{ownerrepo}/blob/main/{filename[:-5]}.txt',
                          delivery='one standalone HTML (CSS and JS embedded)',
                          evidence_kind='repository_documentation'))
    for filename, title in [('shooter.html','Shooter — Time-dev 5.1'),('Soccer.html','Soccer — Time-dev 5.1')]:
        repo='Time-dev-alt/Fable-5.1-Games'
        items.append(item(title,'single_html_game','claude-fable-5-1',
                          f'https://github.com/{repo}/blob/main/{filename}',repo=repo,
                          repo_role='collection_with_html_files',
                          delivery='standalone HTML',evidence_kind='repository_name_and_files'))
    return items

class Fetcher:
    def __init__(self, token:str=''):
        self.session=requests.Session()
        self.session.headers.update({'User-Agent':'Fable-Research-Index/1.0 (+academic metadata research)', 'Accept':'application/json, text/plain, */*'})
        if token: self.session.headers['Authorization']='Bearer '+token
        RAW.mkdir(parents=True, exist_ok=True)
        self.status=[]
    def get(self,url:str,filename:str):
        try:
            res=self.session.get(url,timeout=35)
            res.raise_for_status()
            text=res.text
            (RAW/filename).write_text(text,encoding='utf8')
            self.status.append(dict(url=url,ok=True,bytes=len(text.encode('utf8')),sha256=hashlib.sha256(text.encode()).hexdigest()))
            return text
        except requests.RequestException as e:
            self.status.append(dict(url=url,ok=False,error=str(e)[:500]))
            print('FETCH FAILED:',url,':',str(e)[:180],file=sys.stderr)
            return ''


def from_games_csv(body: str):
    import io
    results=[]
    for row in csv.DictReader(io.StringIO(body)):
        if not row.get('name'): continue
        results.append(item(row['name'], row.get('category') or 'game','claude-fable-5-2',SOURCE_CSV,
                 repo=row.get('repo') or '', repo_role='community_indexed_repository',
                 play_url=row.get('play_url') or row.get('author_demo') or '',
                 tech_stack=row.get('render') or '',delivery=row.get('delivery') or '',
                 publish_date=row.get('snapshot_date') or '',evidence_kind='community_index'))
    return results


def from_awesome(body:str,filename:str):
    doc=BeautifulSoup(body,'html.parser')
    res=[]
    for td in doc.select('td'):
        a=td.select_one('b > a[href]')
        if not a:
            # Some cards use strong tags for the title.
            a=td.select_one('strong > a[href]')
        if not a: continue
        title=clean(a.get_text(' ',strip=True))
        if not title or title in ('Get the prompt','Prompt'): continue
        subs=td.find_all('sub')
        creator=''; post=''; summary=''; prompt=''
        if subs:
            all_links=subs[0].find_all('a',href=True)
            for l in all_links:
                href=l['href']
                if 'x.com/' in href and '/status/' in href: post=href
                elif 'x.com/' in href and not creator: creator=clean(l.get_text(' ',strip=True))
            if len(subs)>1: summary=clean(subs[1].get_text(' ',strip=True))
            for s in subs:
                for l in s.find_all('a',href=True):
                    if '/prompts/' in l['href']: prompt=l['href']
        res.append(item(title,AWESOME_FILES[filename], 'claude-fable-5-2',
                        f'https://github.com/fengyiqicoder/awesome-fable-5.2/blob/main/all/{filename}',
                        play_url=a['href'] if filename!='video-demos.md' else '',
                        post_url=post,creator=creator,description=summary,
                        prompt_url=prompt,prompt_status='linked' if prompt else '',
                        evidence_kind='community_index', link_kind='video_only' if filename=='video-demos.md' else 'live'))
    return res


def from_cases(body:str):
    res=[]
    for c in json.loads(body):
        title=c.get('title') or {}
        if isinstance(title,dict): title=title.get('en') or title.get('zh') or ''
        summary=c.get('summary') or {}
        if isinstance(summary,dict): summary=summary.get('zh') or summary.get('en') or ''
        cat=c.get('category','creative_coding')
        mapping={'games':'game','game':'game','blender':'blender','threejs':'3d_world','motion':'animation','painting':'art','music':'music'}
        res.append(item(title,mapping.get(cat,cat),'claude-fable-5-2',c.get('page') or CASES_JSON,
                 post_url=c.get('post') or '',creator=c.get('creator') or '',
                 description=summary,prompt_status=c.get('promptStatus') or '',
                 prompt_url=c.get('promptSource') or '',publish_date=c.get('posted') or '',
                 evidence_kind='community_index'))
    return res


def from_sandbase(body:str):
    res=[]
    for c in json.loads(body):
        author=c.get('author') or {}
        cat=c.get('category','video_only')
        res.append(item(c.get('title_zh') or c.get('title') or 'Untitled',
                        {'game':'game','animation':'animation','art':'art','scene':'3d_world'}.get(cat,cat),
                        'claude-fable-5-2',SANDBASE_JSON,
                        creator='@'+author.get('handle','').lstrip('@') if author.get('handle') else '',
                        post_url=c.get('postUrl') or '',
                        prompt_status='shared' if c.get('promptShared') else 'not_shared',
                        prompt_url=c.get('labUrl') or '',
                        publish_date=(c.get('createdAt') or '')[:10],
                        evidence_kind='video_community_index',link_kind='video_only'))
    return res


def get_online(f):
    all=[]
    texts=[(SOURCE_CSV,'games.csv',from_games_csv)]
    for name in AWESOME_FILES:
        texts.append((AWESOME_BASE+name,'awesome_'+name,lambda b,n=name:from_awesome(b,n)))
    texts += [(CASES_JSON,'cases.json',from_cases),(SANDBASE_JSON,'videos.json',from_sandbase)]
    for url,file,parser in texts:
        body=f.get(url,file)
        if not body:continue
        try:
            part=parser(body)
            all.extend(part)
            print(f'[{len(part):4}] {url}')
        except Exception as e:
            print('PARSE ERROR:',url,repr(e),file=sys.stderr)
    (DATA/'fetch_log.json').write_text(json.dumps(f.status,ensure_ascii=False,indent=2),encoding='utf8')
    return all


class UF:
    def __init__(self,n):self.p=list(range(n))
    def find(self,i):
        while self.p[i]!=i:
            self.p[i]=self.p[self.p[i]]
            i=self.p[i]
        return i
    def join(self,i,j):
        a,b=self.find(i),self.find(j)
        if a!=b:self.p[b]=a


def dedupe(rows):
    uf=UF(len(rows));seen={};
    for i,r in enumerate(rows):
        keys=[]
        p=post_id(r['post_url'])
        if p: keys.append('post:'+p)
        u=normalize_url(r['play_url'])
        if u and urlparse(u).netloc not in ('github.com',):keys.append('play:'+u)
        cr=norm(r['creator'])
        if cr and norm(r['title']):keys.append('namecreator:'+norm(r['title'])+'@'+cr)
        if r['repo'] and norm(r['title']): keys.append('namerepo:'+norm(r['title'])+'@'+r['repo'].casefold())
        for key in keys:
            if key in seen:uf.join(i,seen[key])
            else:seen[key]=i
    groups=defaultdict(list)
    for i,r in enumerate(rows):groups[uf.find(i)].append(r)
    out=[]
    for grp in groups.values():
        # Richest row is representative, but do not discard any provenance links.
        grp.sort(key=lambda x: (bool(x['repo']),bool(x['play_url']),len(x['description']),x['evidence_kind']=='repository_documentation'),reverse=True)
        base=dict(grp[0])
        values=lambda k: list(dict.fromkeys(v for row in grp for v in [row.get(k,'')] if v))
        source_list=values('source_url')
        posts=values('post_url');plays=values('play_url');repos=values('repo')
        models=values('model')
        descs=values('description')
        all_categories=values('category')
        title=base['title']
        primary=post_id(posts[0]) if posts else ''
        canonical=f'post:{primary}' if primary else ('play:'+normalize_url(plays[0]) if plays else f'name:{norm(title)}:{base["repo"].casefold()}')
        base.update(project_id='fab_'+hashlib.sha1(canonical.encode('utf8')).hexdigest()[:14],
                    title=title, model='; '.join(models),
                    category='; '.join(all_categories),
                    description=max(descs,key=len) if descs else '',
                    repos=repos, plays=plays, posts=posts, sources=source_list,
                    creators=values('creator'), evidence=values('evidence_kind'),
                    prompt_urls=values('prompt_url'),prompt_statuses=values('prompt_status'),
                    source_count=len(source_list), observations=len(grp),
                    source_code_status='indexed_repository' if repos else 'not_found',
                    source_verified='index_only', source_license='unknown')
        out.append(base)
    out.sort(key=lambda x:(x['category'],x['title'].casefold()))
    ids=[x['project_id'] for x in out]
    assert len(ids)==len(set(ids)), 'Hash collision or incomplete project identity; investigate before writing'
    return out


def write_db(rows, observations):
    db=DATA/'fable_projects.sqlite'
    if db.exists():db.unlink()
    conn=sqlite3.connect(db)
    conn.executescript('''
    PRAGMA foreign_keys=ON;
    CREATE TABLE projects(
        id TEXT PRIMARY KEY, title TEXT NOT NULL, model_claim TEXT NOT NULL, category TEXT,
        description TEXT, creator TEXT, code_status TEXT NOT NULL, model_evidence TEXT,
        first_seen TEXT, source_count INTEGER, observations INTEGER, repo_count INTEGER,
        playable_count INTEGER, video_count INTEGER
    );
    CREATE TABLE project_links(
        project_id TEXT NOT NULL REFERENCES projects(id), kind TEXT NOT NULL,
        url TEXT NOT NULL, PRIMARY KEY(project_id,kind,url)
    );
    CREATE TABLE repository_links(
        project_id TEXT NOT NULL REFERENCES projects(id), full_name TEXT NOT NULL,
        repo_url TEXT NOT NULL, repo_role TEXT, license_status TEXT DEFAULT 'unknown',
        PRIMARY KEY(project_id,full_name)
    );
    CREATE TABLE evidence(
        project_id TEXT NOT NULL REFERENCES projects(id),source_url TEXT NOT NULL,
        evidence_kind TEXT, observed_at TEXT NOT NULL, PRIMARY KEY(project_id,source_url)
    );
    CREATE TABLE observations(
        id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT REFERENCES projects(id),
        title TEXT, source_url TEXT, category TEXT, model_claim TEXT, creator TEXT,
        repo TEXT, playable_url TEXT, original_post TEXT, evidence_kind TEXT,
        tech_stack TEXT, delivery TEXT, prompt_status TEXT
    );
    CREATE INDEX idx_projects_cat ON projects(category);
    CREATE INDEX idx_observations_source ON observations(source_url);
    CREATE INDEX idx_observations_post ON observations(original_post);
    CREATE VIEW project_catalog AS
      SELECT p.*, (SELECT group_concat(r.repo_url, ' | ') FROM repository_links r WHERE r.project_id=p.id) AS repositories,
       (SELECT group_concat(l.url, ' | ') FROM project_links l WHERE l.project_id=p.id AND l.kind='play') AS play_urls,
       (SELECT group_concat(l.url, ' | ') FROM project_links l WHERE l.project_id=p.id AND l.kind='post') AS original_posts
      FROM projects p;
    ''')
    ts=datetime.now(timezone.utc).isoformat()
    for p in rows:
        kinds=set(p['evidence'])
        evidence='repository_documentation' if 'repository_documentation' in kinds else ('community_index' if 'community_index' in kinds else 'video_community_index')
        conn.execute('INSERT INTO projects VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(
            p['project_id'],p['title'],p['model'],p['category'],p['description'],
            ' | '.join(p['creators']),p['source_code_status'],evidence,
            p['publish_date'],p['source_count'],p['observations'],len(p['repos']),len(p['plays']),len(p['posts'])))
        for repo in p['repos']:
            if re.match(r'^[\w.-]+/[\w.-]+$',repo):
                role='community_mirror' if repo.lower() in ('realcodebear/saltline-fable-5.2','dongyubin/saltline-game') else 'source_repository_indexed'
                conn.execute('INSERT OR IGNORE INTO repository_links VALUES(?,?,?,?,?)',
                            (p['project_id'],repo,'https://github.com/'+repo,role,'unknown'))
        for kind,key in [('play','plays'),('post','posts'),('prompt','prompt_urls')]:
            for link in p[key]:
                if link.startswith('https://'):
                    conn.execute('INSERT OR IGNORE INTO project_links VALUES(?,?,?)',(p['project_id'],kind,link))
        for src in p['sources']:
            conn.execute('INSERT OR IGNORE INTO evidence VALUES(?,?,?,?)',(p['project_id'],src,evidence,ts))
    # Map observations back to merged items by canonical identity keys, with final fallback on exact title+source.
    project_by_keys={}
    for p in rows:
        for url in p['posts']:
            if post_id(url): project_by_keys['post:'+post_id(url)]=p['project_id']
        for url in p['plays']:
            if url:project_by_keys['play:'+normalize_url(url)]=p['project_id']
        for repo in p['repos']:
            project_by_keys['repo:'+repo.casefold()+'|'+norm(p['title'])]=p['project_id']
        for creator in p['creators']:
            if creator:project_by_keys['creator:'+norm(creator)+'|'+norm(p['title'])]=p['project_id']
    # by source+title is safe when no more stable ID exists
    for p in rows:
        for src in p['sources']:project_by_keys.setdefault('src:'+src+'|'+norm(p['title']),p['project_id'])
    for o in observations:
        keys=[]
        if post_id(o['post_url']):keys.append('post:'+post_id(o['post_url']))
        if o['play_url']:keys.append('play:'+normalize_url(o['play_url']))
        if o['repo']:keys.append('repo:'+o['repo'].casefold()+'|'+norm(o['title']))
        if o['creator']:keys.append('creator:'+norm(o['creator'])+'|'+norm(o['title']))
        keys.append('src:'+o['source_url']+'|'+norm(o['title']))
        pid=next((project_by_keys[k] for k in keys if k in project_by_keys),None)
        conn.execute('INSERT INTO observations(project_id,title,source_url,category,model_claim,creator,repo,playable_url,original_post,evidence_kind,tech_stack,delivery,prompt_status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                     (pid,o['title'],o['source_url'],o['category'],o['model'],o['creator'],o['repo'],o['play_url'],o['post_url'],o['evidence_kind'],o['tech_stack'],o['delivery'],o['prompt_status']))
    conn.commit()
    missing=conn.execute('SELECT COUNT(*) FROM observations WHERE project_id IS NULL').fetchone()[0]
    if missing: print('WARNING: observations missing project mapping:',missing,file=sys.stderr)
    conn.close()
    return db


def export(rows,online):
    cols=['project_id','title','model','category','creator','source_code_status','repo_urls','play_urls','post_urls','source_urls','prompt_urls','source_count','observations','evidence','description']
    with open(DATA/'projects.csv','w',encoding='utf-8-sig',newline='') as f:
        wr=csv.DictWriter(f,fieldnames=cols);wr.writeheader()
        for p in rows:
            wr.writerow(dict(project_id=p['project_id'],title=p['title'],model=p['model'],category=p['category'],
                        creator='; '.join(p['creators']),source_code_status=p['source_code_status'],
                        repo_urls='; '.join('https://github.com/'+z for z in p['repos']),
                        play_urls='; '.join(p['plays']),post_urls='; '.join(p['posts']),
                        source_urls='; '.join(p['sources']),prompt_urls='; '.join(p['prompt_urls']),
                        source_count=p['source_count'],observations=p['observations'],evidence='; '.join(p['evidence']),
                        description=p['description']))
    # JSONL is particularly convenient for ETL / search engines.
    with (DATA/'projects.jsonl').open('w',encoding='utf8') as f:
        for p in rows:
            f.write(json.dumps(p,ensure_ascii=False,sort_keys=True)+'\n')
    repo={}
    for p in rows:
        for r in p['repos']:
            repo.setdefault(r,[]).append(p['title'])
    with (DATA/'repositories.csv').open('w',encoding='utf-8-sig',newline='') as f:
        wr=csv.writer(f);wr.writerow(['repo_full_name','repo_url','projects_count','project_titles','license_status','clone_status'])
        for r,projects in sorted(repo.items(),key=lambda kv:kv[0].lower()):
            wr.writerow([r,'https://github.com/'+r,len(projects),' ; '.join(projects),'unknown','not_cloned'])
    counts=Counter();source_counts=Counter()
    for p in rows:
        for c in p['category'].split('; '):counts[c]+=1
        for src in p['sources']:source_counts[src]+=1
    summary={'generated_at':datetime.now(timezone.utc).isoformat(),'snapshot': 'seed + public indexes' if online else 'offline curated metadata seed',
             'projects_deduplicated':len(rows),'projects_with_repository_links':sum(bool(p['repos']) for p in rows),
             'unique_repository_urls':len(repo),'projects_with_live_links':sum(bool(p['plays']) for p in rows),
             'categories':dict(counts.most_common()),'by_source':dict(source_counts.most_common()),
             'important_limitation':'Public and community attributions only; no individual repo code inspection. Offline environment prevented live HTTP verification or cloning.'}
    (DATA/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    return summary


def clone_repos(rows, limit:int=0):
    target=ROOT/'cloned_repositories'
    repos=sorted(set(r for p in rows for r in p['repos'] if re.match(r'^[\w.-]+/[\w.-]+$',r)))
    if limit:repos=repos[:limit]
    logs=[]
    for repo in repos:
        dest=target/repo
        if dest.exists():
            logs.append({'repository':repo,'status':'already_present'});continue
        dest.parent.mkdir(parents=True,exist_ok=True)
        try:
            subprocess.run(['git','clone','--depth','1','--filter=blob:none','--','https://github.com/'+repo+'.git',str(dest)],check=True,timeout=180,capture_output=True,text=True)
            logs.append({'repository':repo,'status':'cloned'})
        except Exception as exc:
            logs.append({'repository':repo,'status':'error','error':str(exc)[:300]})
    (DATA/'clone_results.json').write_text(json.dumps(logs,ensure_ascii=False,indent=2),encoding='utf8')
    return Counter(z['status'] for z in logs)


def main():
    parser=argparse.ArgumentParser(description='Build reproducible Fable 5.1/5.2 research database')
    parser.add_argument('--online',action='store_true',help='Collect up-to-date online public records; requires internet')
    parser.add_argument('--clone-repos',action='store_true',help='Actually clone public GitHub repos; opt-in because repos can be large')
    parser.add_argument('--clone-limit',type=int,default=0,help='For validation: clone only first N repos')
    opt=parser.parse_args()
    DATA.mkdir(parents=True,exist_ok=True)
    observations=load_seed()
    if opt.online:
        observations += get_online(Fetcher(os.getenv('GITHUB_TOKEN','')))
    projects=dedupe(observations)
    write_db(projects,observations)
    summary=export(projects,opt.online)
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    if opt.clone_repos:
        print('Clone results:',dict(clone_repos(projects,opt.clone_limit)))

if __name__=='__main__':main()
