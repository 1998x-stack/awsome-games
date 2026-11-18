#!/usr/bin/env python3
"""SQLite catalog schema and shared database helpers."""
from __future__ import annotations
import hashlib, json, re, sqlite3, unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "catalog.sqlite"
SEED_PATH = ROOT / "data" / "seeds" / "legacy_projects.jsonl"
CATEGORY_PATH = ROOT / "config" / "categories.json"

# `export_seed.py` reconstructs a seed file from a committed SQLite snapshot. It
# records that fact as a marker, never as a citation: a reconstruction is the
# absence of firsthand evidence, so it must never materialise as a
# `project_evidence` row that would later look like a real source.
SYNTHETIC_EVIDENCE_TYPES = {"sqlite_snapshot_reconstruction"}

SCHEMA = r"""
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  original_title TEXT,
  description TEXT NOT NULL DEFAULT '',
  content_type TEXT NOT NULL DEFAULT 'game',
  model_claim TEXT NOT NULL DEFAULT 'unknown',
  model_version TEXT NOT NULL DEFAULT 'unknown',
  model_confidence TEXT NOT NULL DEFAULT 'community_claim',
  creator TEXT NOT NULL DEFAULT '',
  published_at TEXT,
  prompt_status TEXT NOT NULL DEFAULT 'unknown',
  source_status TEXT NOT NULL DEFAULT 'not_checked',
  playable_status TEXT NOT NULL DEFAULT 'not_checked',
  language TEXT NOT NULL DEFAULT 'unknown',
  featured INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS categories (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  group_name TEXT NOT NULL,
  content_type TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS project_categories (
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  category_id TEXT NOT NULL REFERENCES categories(id),
  is_primary INTEGER NOT NULL DEFAULT 0,
  raw_label TEXT NOT NULL DEFAULT '',
  PRIMARY KEY(project_id, category_id)
);
CREATE TABLE IF NOT EXISTS repositories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  full_name TEXT NOT NULL UNIQUE,
  owner TEXT NOT NULL,
  name TEXT NOT NULL,
  html_url TEXT NOT NULL,
  clone_url TEXT NOT NULL,
  default_branch TEXT NOT NULL DEFAULT 'main',
  description TEXT NOT NULL DEFAULT '',
  stars INTEGER,
  forks INTEGER,
  repo_size_kb INTEGER,
  license_spdx TEXT NOT NULL DEFAULT 'NOASSERTION',
  license_name TEXT NOT NULL DEFAULT '',
  is_fork INTEGER NOT NULL DEFAULT 0,
  archived INTEGER NOT NULL DEFAULT 0,
  repo_role TEXT NOT NULL DEFAULT 'indexed_source',
  clone_status TEXT NOT NULL DEFAULT 'pending',
  clone_path TEXT NOT NULL DEFAULT '',
  commit_sha TEXT NOT NULL DEFAULT '',
  cloned_at TEXT,
  last_checked_at TEXT,
  error_message TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS project_repositories (
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  relation_type TEXT NOT NULL DEFAULT 'indexed_source',
  is_primary INTEGER NOT NULL DEFAULT 0,
  entry_path TEXT NOT NULL DEFAULT '',
  game_path TEXT NOT NULL DEFAULT '',
  entry_confidence TEXT NOT NULL DEFAULT 'unresolved',
  playable_status TEXT NOT NULL DEFAULT 'not_checked',
  note TEXT NOT NULL DEFAULT '',
  PRIMARY KEY(project_id, repository_id)
);
CREATE TABLE IF NOT EXISTS links (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  link_type TEXT NOT NULL,
  url TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT '',
  UNIQUE(project_id, link_type, url)
);
CREATE TABLE IF NOT EXISTS prompts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'unknown',
  prompt_url TEXT NOT NULL DEFAULT '',
  prompt_text TEXT NOT NULL DEFAULT '',
  UNIQUE(project_id, prompt_url)
);
CREATE TABLE IF NOT EXISTS evidence_sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  source_type TEXT NOT NULL DEFAULT 'community_index',
  url TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS project_evidence (
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  evidence_source_id INTEGER NOT NULL REFERENCES evidence_sources(id) ON DELETE CASCADE,
  evidence_type TEXT NOT NULL DEFAULT 'community_index',
  confidence TEXT NOT NULL DEFAULT 'low',
  note TEXT NOT NULL DEFAULT '',
  observed_at TEXT NOT NULL,
  PRIMARY KEY(project_id, evidence_source_id, evidence_type)
);
CREATE TABLE IF NOT EXISTS repository_files (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  relative_path TEXT NOT NULL,
  extension TEXT NOT NULL DEFAULT '',
  mime_type TEXT NOT NULL DEFAULT '',
  size_bytes INTEGER NOT NULL DEFAULT 0,
  sha256 TEXT NOT NULL DEFAULT '',
  is_html_entry INTEGER NOT NULL DEFAULT 0,
  copied INTEGER NOT NULL DEFAULT 0,
  UNIQUE(repository_id, relative_path)
);
CREATE TABLE IF NOT EXISTS aliases (
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  alias TEXT NOT NULL,
  alias_type TEXT NOT NULL DEFAULT 'alternate_title',
  PRIMARY KEY(project_id, alias)
);
CREATE TABLE IF NOT EXISTS ingest_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  operation TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'running',
  repositories_seen INTEGER NOT NULL DEFAULT 0,
  repositories_cloned INTEGER NOT NULL DEFAULT 0,
  games_playable INTEGER NOT NULL DEFAULT 0,
  notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS ingest_errors (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER REFERENCES ingest_runs(id) ON DELETE SET NULL,
  repository_full_name TEXT NOT NULL DEFAULT '',
  project_id TEXT NOT NULL DEFAULT '',
  stage TEXT NOT NULL,
  error TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_projects_model ON projects(model_version);
CREATE INDEX IF NOT EXISTS idx_projects_content_type ON projects(content_type);
CREATE INDEX IF NOT EXISTS idx_project_categories_category ON project_categories(category_id);
CREATE INDEX IF NOT EXISTS idx_project_repositories_repo ON project_repositories(repository_id);
CREATE INDEX IF NOT EXISTS idx_project_repositories_playable ON project_repositories(playable_status);
CREATE INDEX IF NOT EXISTS idx_links_type ON links(link_type);
CREATE VIEW IF NOT EXISTS catalog_view AS
 SELECT p.id, p.slug, p.title, p.description, p.content_type, p.model_claim, p.model_version,
        p.model_confidence, p.creator, p.source_status, p.playable_status,
        GROUP_CONCAT(DISTINCT c.name) AS categories,
        GROUP_CONCAT(DISTINCT r.full_name) AS repositories
 FROM projects p
 LEFT JOIN project_categories pc ON pc.project_id=p.id
 LEFT JOIN categories c ON c.id=pc.category_id
 LEFT JOIN project_repositories pr ON pr.project_id=p.id
 LEFT JOIN repositories r ON r.id=pr.repository_id
 GROUP BY p.id;
"""


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def slugify(value: str, fallback: str = "") -> str:
    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or fallback or "project"


def category_catalog():
    return json.loads(CATEGORY_PATH.read_text(encoding="utf-8"))


def classify(raw_label: str, content_hint: str = ""):
    raw = (raw_label or "").strip().lower().replace("-", "_")
    hint = (content_hint or "").lower()
    direct = {
      "single_html_visual_study":"visual_experiment", "single_html_game":"arcade",
      "video_only":"video_demo", "3d_world":"3d_world", "web_tool":"web_tool",
      "interactive_art":"interactive_art", "data_visualization":"data_visualization",
      "animation":"animation", "art":"generative_art", "music":"music_audio",
      "blender":"visual_experiment", "game":"other_game", "games":"other_game",
      "creative_coding":"other_creative", "other":"other_creative"
    }
    if raw in direct: return direct[raw]
    rules = [
      ("fps", ["fps", "first person", "射击"]),
      ("strategy", ["rts", "strategy", "策略", "即时战略", "战棋", "任务规划", "棋盘"]),
      ("racing", ["竞速", "赛车", "驾驶", "racing", "kart"]),
      ("platformer", ["平台跳跃", "platformer", "platform", "跑酷"]),
      ("horror", ["恐怖", "惊悚", "horror"]),
      ("3d_world", ["3d 世界", "3d_world", "沉浸体验"]),
      ("exploration", ["探索", "冒险", "exploration"]),
      ("sandbox", ["开放世界", "沙盒", "sandbox", "open world"]),
      ("simulation", ["建造", "模拟", "经营", "simulation", "自然灾害"]),
      ("rpg", ["仙侠", "角色扮演", "rpg"]),
      ("puzzle", ["三消", "解谜", "谜题", "puzzle", "辨识"]),
      ("sports", ["体育", "网球", "足球", "竞技", "sports"]),
      ("arcade", ["休闲", "派对", "arcade"]),
      ("music_audio", ["听音", "音乐", "audio"]),
      ("narrative", ["叙事", "剧情", "narrative"]),
      ("action", ["动作", "action"]),
      ("survival", ["生存", "survival"]),
      ("fighting", ["格斗", "fighting"]),
      ("web_tool", ["web tool", "工具"]),
      ("animation", ["animation", "动画", "motion"]),
      ("generative_art", ["painting", "绘画", "art", "油画"]),
    ]
    for category, needles in rules:
        if any(n in raw for n in needles): return category
    if hint in ("video_demo", "video_only"): return "video_demo"
    return "other_game" if not raw or raw == "game" else "other_creative"


def model_version(claim: str) -> str:
    value = (claim or "").lower()
    if "5-1" in value or "5.1" in value: return "5.1"
    if "5-2" in value or "5.2" in value: return "5.2"
    return "unknown"


def parse_repo(full_name: str):
    bits = (full_name or "").strip().strip("/").split("/")
    if len(bits) != 2 or not all(bits): return None
    owner, name = bits
    if not re.fullmatch(r'[A-Za-z0-9-]{1,39}', owner) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', name) or name in ('.','..'):
        return None
    return {"full_name": f"{owner}/{name}", "owner": owner, "name": name,
            "html_url": f"https://github.com/{owner}/{name}",
            "clone_url": f"https://github.com/{owner}/{name}.git"}


def infer_relation(repo: str, repo_role: str = "") -> str:
    low = (repo or "").lower()
    role = (repo_role or "").lower()
    if "mirror" in role or "saltline-fable" in low: return "third_party_mirror"
    if "collection" in role or low in ("sorrycc/fable-arcade", "miaai-lab/claude-fable-5.2-html-files", "time-dev-alt/fable-5.1-games"):
        return "collection"
    if "index" in role: return "community_indexed_source"
    return "unverified_source_candidate"


def infer_entry_path(project: dict, repo: str) -> str:
    # A source URL pointing to a concrete file in this repository is the strongest seed.
    for source in project.get("sources", []) + [project.get("source_url", "")]:
        match = re.search(r"github\.com/([^/]+/[^/]+)/blob/[^/]+/(.+)$", source or "")
        if match and match.group(1).lower() == repo.lower():
            path = match.group(2).split("?", 1)[0]
            if path.lower().endswith((".html", ".htm")):
                return path
    # The Fable Arcade collection exposes each game in a stable subdirectory.
    for url in project.get("plays", []) + [project.get("play_url", "")]:
        if "sorrycc.github.io/fable-arcade/games/" in (url or ""):
            tail = url.split("/games/", 1)[1].strip("/")
            if tail: return f"games/{tail}/index.html"
    return ""


def build_curated_seed_rows():
    """Reconstruct the 155-record first snapshot from compact, human-auditable TSV seeds."""
    rows=[]
    source52='https://github.com/ygx2378/awesome-fable-5-2-games/blob/master/data/games.csv'
    for line in (ROOT/'data/seeds/games_52.tsv').read_text(encoding='utf-8').splitlines():
        if not line.strip(): continue
        title,repo,play,category=line.split('|',3)
        rows.append({'title':title,'category':category,'model':'claude-fable-5-2','repo':repo,
          'repos':[repo] if repo else [],'repo_role':'community_indexed_repository','play_url':play,
          'plays':[play] if play else [],'source_url':source52,'sources':[source52],
          'evidence':['community_index'],'creators':[],'prompt_urls':[],'prompt_statuses':[]})
    source51='https://github.com/sorrycc/fable-arcade/blob/main/README.md'
    for line in (ROOT/'data/seeds/games_51.tsv').read_text(encoding='utf-8').splitlines():
        if not line.strip(): continue
        title,slug,published=line.split('|',2)
        play=f'https://sorrycc.github.io/fable-arcade/games/{slug}/'
        rows.append({'title':title,'category':'game','model':'claude-fable-5-1','repo':'sorrycc/fable-arcade',
          'repos':['sorrycc/fable-arcade'],'repo_role':'collection_with_original_game_files','play_url':play,
          'plays':[play],'source_url':source51,'sources':[source51],'publish_date':published,
          'evidence':['repository_documentation'],'creators':[],'prompt_urls':[],'prompt_statuses':[]})
    special=[
      ('Starry Nightrider','https://starrynightrider.com','https://x.com/ebbyamir/status/2120284261089673376','@ebbyamir'),
      ('Oil Paint','https://patch.gg/blendi/oil-paint','https://x.com/BlendiByl/status/2120341251178594532','@BlendiByl'),
      ('CROSSTOWN','https://nyc.somethingbig.ai/','https://x.com/mattshumer_/status/2120282133503820150','@mattshumer_'),
      ('What the Water Keeps','https://what-the-water-keeps.vercel.app/','https://x.com/kevin_t_ngo/status/2119868968307695818','@kevin_t_ngo'),
      ('Tennis','https://tennis.sixfingerpunch.com/','https://x.com/photonstorm/status/2120330010112434313','@photonstorm')]
    source_special='https://github.com/fengyiqicoder/awesome-fable-5.2'
    ownerrepo='MiaAI-Lab/Claude-Fable-5.2-HTML-Files'
    for filename in (ROOT/'data/seeds/mia_html_52.txt').read_text(encoding='utf-8').splitlines():
        if not filename or not filename.endswith('.html'): continue
        title=re.sub(r'^\d+-','',filename[:-5]).replace('-',' ').title()
        src=f'https://github.com/{ownerrepo}/blob/main/{filename}'
        prompt=f'https://github.com/{ownerrepo}/blob/main/{filename[:-5]}.txt'
        rows.append({'title':title,'category':'single_html_visual_study','model':'claude-fable-5-2','repo':ownerrepo,
          'repos':[ownerrepo],'repo_role':'collection_with_original_html_and_prompt','source_url':src,'sources':[src],
          'prompt_url':prompt,'prompt_urls':[prompt],'prompt_status':'published','prompt_statuses':['published'],
          'delivery':'one standalone HTML (CSS and JS embedded)','evidence':['repository_documentation'],'creators':[]})
    for filename,title in [('shooter.html','Shooter — Time-dev 5.1'),('Soccer.html','Soccer — Time-dev 5.1')]:
        repo='Time-dev-alt/Fable-5.1-Games'; src=f'https://github.com/{repo}/blob/main/{filename}'
        rows.append({'title':title,'category':'single_html_game','model':'claude-fable-5-1','repo':repo,'repos':[repo],
          'repo_role':'collection_with_html_files','source_url':src,'sources':[src],'delivery':'standalone HTML',
          'evidence':['repository_name_and_files'],'creators':[],'prompt_urls':[],'prompt_statuses':[]})
    # Repair special live-only rows separately to keep the record schema explicit.
    for title,play,post,creator in special:
        rows.append({'title':title,'category':'game','model':'claude-fable-5-2','repo':'','repos':[],
          'repo_role':'','play_url':play,'plays':[play],'post_url':post,'posts':[post],
          'creator':creator,'creators':[creator],'source_url':source_special,'sources':[source_special],
          'evidence':['community_index'],'prompt_urls':[],'prompt_statuses':[]})
    for r in rows:
        identity=(r.get('play_url') or '')+'|'+(r.get('repo') or '')+'|'+r['title']
        r['project_id']='fab_'+hashlib.sha1(identity.encode('utf-8')).hexdigest()[:14]
        r.setdefault('category','game'); r.setdefault('model','unknown'); r.setdefault('repo','')
        r.setdefault('repos',[r['repo']] if r['repo'] else []); r.setdefault('repo_role','')
        r.setdefault('play_url',''); r.setdefault('plays',[r['play_url']] if r['play_url'] else [])
        r.setdefault('post_url',''); r.setdefault('posts',[r['post_url']] if r['post_url'] else [])
        r.setdefault('creator',''); r.setdefault('creators',[r['creator']] if r['creator'] else [])
        r.setdefault('source_url',''); r.setdefault('sources',[r['source_url']] if r['source_url'] else [])
        r.setdefault('evidence',['community_index']); r.setdefault('prompt_url',''); r.setdefault('prompt_urls',[r['prompt_url']] if r['prompt_url'] else [])
        r.setdefault('prompt_status',''); r.setdefault('prompt_statuses',[r['prompt_status']] if r['prompt_status'] else [])
        r.setdefault('publish_date',''); r.setdefault('description',''); r.setdefault('tech_stack',''); r.setdefault('delivery','')
    return rows

def seed_database(conn: sqlite3.Connection, seed_path: Path = SEED_PATH):
    categories = category_catalog()
    for cat in categories:
        conn.execute("INSERT INTO categories(id,name,group_name,content_type) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,group_name=excluded.group_name,content_type=excluded.content_type",
                     (cat["id"], cat["name"], cat["group"], cat["content_type"]))
    count = 0
    if seed_path.exists():
        seed_rows=[json.loads(line) for line in seed_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    elif seed_path.resolve() == SEED_PATH.resolve():
        # The bundled SQLite snapshot may have stable IDs that differ from the
        # fallback curated list. Never merge fallback rows into a populated DB.
        if conn.execute('SELECT COUNT(*) FROM projects').fetchone()[0]:
            conn.commit()
            return 0
        seed_rows=build_curated_seed_rows()
    else:
        raise FileNotFoundError(f'Explicit seed file not found: {seed_path}')
    for p in seed_rows:
        pid = p.get("project_id") or "fab_" + hashlib.sha1((p.get("title", "") + p.get("source_url", "")).encode()).hexdigest()[:14]
        slug = slugify(p.get("title", ""), pid)
        # Keep slugs unique even when similarly named projects exist.
        if conn.execute("SELECT 1 FROM projects WHERE slug=? AND id<>?", (slug, pid)).fetchone():
            slug = f"{slug}-{pid[-5:]}"
        claim = p.get("model", "unknown") or "unknown"
        cats_raw = [x.strip() for x in (p.get("category", "") or "").split(";") if x.strip()]
        cat_ids = list(dict.fromkeys(classify(x, p.get("link_kind", "")) for x in cats_raw)) or ["other_game"]
        primary_cat = cat_ids[0]
        cat_info = next((x for x in categories if x["id"] == primary_cat), categories[-1])
        creators = p.get("creators") or ([p.get("creator")] if p.get("creator") else [])
        creator = " / ".join(dict.fromkeys(x for x in creators if x))
        per_source_evidence = p.get("evidence_by_source") or {}
        if not isinstance(per_source_evidence, dict):
            raise ValueError("evidence_by_source must map source URLs to provenance")
        ts = now()
        conn.execute("""INSERT INTO projects(id,slug,title,original_title,description,content_type,model_claim,model_version,model_confidence,creator,published_at,prompt_status,source_status,playable_status,created_at,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(id) DO UPDATE SET slug=excluded.slug,title=excluded.title,original_title=excluded.original_title,description=excluded.description,content_type=excluded.content_type,model_claim=CASE WHEN projects.model_confidence='community_claim' THEN excluded.model_claim ELSE projects.model_claim END,model_version=CASE WHEN projects.model_confidence='community_claim' THEN excluded.model_version ELSE projects.model_version END,creator=excluded.creator,published_at=excluded.published_at,prompt_status=excluded.prompt_status,updated_at=CASE WHEN projects.slug=excluded.slug AND projects.title=excluded.title AND projects.original_title IS excluded.original_title AND projects.description=excluded.description AND projects.content_type=excluded.content_type AND projects.creator=excluded.creator AND projects.published_at IS excluded.published_at AND projects.prompt_status=excluded.prompt_status AND projects.model_claim=CASE WHEN projects.model_confidence='community_claim' THEN excluded.model_claim ELSE projects.model_claim END AND projects.model_version=CASE WHEN projects.model_confidence='community_claim' THEN excluded.model_version ELSE projects.model_version END THEN projects.updated_at ELSE excluded.updated_at END""",
          (pid,slug,p.get("title", "Untitled"),p.get("title", "Untitled"),p.get("description", ""),cat_info["content_type"],claim,model_version(claim),"community_claim",creator,p.get("publish_date") or None,";".join(p.get("prompt_statuses",[]) or ([p.get("prompt_status")] if p.get("prompt_status") else [])) or "unknown","indexed" if p.get("repos") else "no_repository","external_demo" if p.get("plays") else "not_checked",ts,ts))
        # The scalar UPSERT above cannot detect category-only changes.
        # Keep timestamps stable on a repeated identical import, but bump them
        # when relation membership, primary priority or original labels change.
        new_categories = [(cid, 1 if i == 0 else 0, "; ".join(cats_raw))
                          for i, cid in enumerate(cat_ids)]
        previous_categories = [
            tuple(row) for row in conn.execute(
                "SELECT category_id,is_primary,raw_label FROM project_categories "
                "WHERE project_id=?", (pid,)
            )
        ]
        if sorted(previous_categories) != sorted(new_categories):
            conn.execute("DELETE FROM project_categories WHERE project_id=?", (pid,))
            for cid, primary, raw in new_categories:
                conn.execute(
                    "INSERT INTO project_categories(project_id,category_id,is_primary,raw_label) "
                    "VALUES(?,?,?,?)", (pid, cid, primary, raw)
                )
            conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (ts, pid))
        repos = p.get("repos") or ([p.get("repo")] if p.get("repo") else [])
        for repo_name in repos:
            meta = parse_repo(repo_name)
            if not meta: continue
            conn.execute("""INSERT INTO repositories(full_name,owner,name,html_url,clone_url,repo_role)
              SELECT ?,?,?,?,?,? WHERE NOT EXISTS(SELECT 1 FROM repositories WHERE full_name=?)""", (meta["full_name"],meta["owner"],meta["name"],meta["html_url"],meta["clone_url"],infer_relation(repo_name,p.get("repo_role", "")),meta["full_name"]))
            rid = conn.execute("SELECT id FROM repositories WHERE full_name=?", (meta["full_name"],)).fetchone()[0]
            entry = infer_entry_path(p, repo_name)
            conn.execute("""INSERT INTO project_repositories(project_id,repository_id,relation_type,is_primary,entry_path,entry_confidence)
              VALUES(?,?,?,?,?,?) ON CONFLICT(project_id,repository_id) DO UPDATE SET relation_type=excluded.relation_type,entry_path=CASE WHEN excluded.entry_path<>'' THEN excluded.entry_path ELSE project_repositories.entry_path END""",
              (pid,rid,infer_relation(repo_name,p.get("repo_role", "")),1 if repo_name==repos[0] else 0,entry,"source_link" if entry else "unresolved"))
        for url in p.get("plays", []) or ([p.get("play_url")] if p.get("play_url") else []):
            if url: conn.execute("INSERT INTO links(project_id,link_type,url,label) SELECT ?,?,?,? WHERE NOT EXISTS(SELECT 1 FROM links WHERE project_id=? AND link_type=? AND url=?)",(pid,"demo",url,"在线演示",pid,"demo",url))
        for url in p.get("posts", []) or ([p.get("post_url")] if p.get("post_url") else []):
            if url: conn.execute("INSERT INTO links(project_id,link_type,url,label) SELECT ?,?,?,? WHERE NOT EXISTS(SELECT 1 FROM links WHERE project_id=? AND link_type=? AND url=?)",(pid,"author_post",url,"作者原帖",pid,"author_post",url))
        for url in p.get("prompt_urls", []) or ([p.get("prompt_url")] if p.get("prompt_url") else []):
            if url: conn.execute("INSERT INTO prompts(project_id,status,prompt_url) SELECT ?,?,? WHERE NOT EXISTS(SELECT 1 FROM prompts WHERE project_id=? AND prompt_url=?)",(pid,"published",url,pid,url))
        for url in p.get("sources", []) or ([p.get("source_url")] if p.get("source_url") else []):
            if not url: continue
            name = urlparse(url).netloc or "unknown source"
            conn.execute("INSERT INTO evidence_sources(name,source_type,url) SELECT ?,?,? WHERE NOT EXISTS(SELECT 1 FROM evidence_sources WHERE url=?)",(name,"community_index",url,url))
            sid = conn.execute("SELECT id FROM evidence_sources WHERE url=?",(url,)).fetchone()[0]
            # Prefer faithful per-source provenance from the seed; the project-level
            # `evidence` list is only a fallback for hand-authored seeds.
            # A URL identifies a source, not a single evidence claim. Legacy
            # JSONL contains one dict per URL; new exports contain a list.
            if url in per_source_evidence:
                rows = per_source_evidence[url]
                if isinstance(rows, dict):
                    rows = [rows]
                if not isinstance(rows, list) or not rows:
                    raise ValueError("evidence_by_source must contain a nonempty dict/list")
            else:
                fallback = p.get("evidence") or [p.get("evidence_kind", "community_index")]
                if not isinstance(fallback, list) or not all(
                    isinstance(value, str) and value for value in fallback
                ):
                    raise ValueError("Fallback evidence must contain nonempty string types")
                rows = [{"evidence_type": kind} for kind in fallback]
            seen_types = {}
            for mapping in rows:
                if (not isinstance(mapping, dict) or
                        not isinstance(mapping.get("evidence_type"), str) or
                        not mapping["evidence_type"]):
                    raise ValueError("Invalid per-source evidence type")
                ev_type = mapping["evidence_type"]
                if ev_type in SYNTHETIC_EVIDENCE_TYPES:
                    continue
                confidence = mapping.get("confidence") or (
                    "medium" if ev_type in ("repository_documentation",
                                            "repository_name_and_files") else "low"
                )
                if not isinstance(confidence, str) or not confidence:
                    raise ValueError("Invalid per-source evidence confidence")
                if ev_type in seen_types and seen_types[ev_type] != confidence:
                    raise ValueError("Conflicting confidence for identical source/evidence type")
                seen_types[ev_type] = confidence
                conn.execute(
                    "INSERT OR IGNORE INTO project_evidence(project_id,evidence_source_id,"
                    "evidence_type,confidence,observed_at) VALUES(?,?,?,?,?)",
                    (pid, sid, ev_type, confidence, ts)
                )
        count += 1
    conn.commit()
    return count


def create_run(conn, operation: str) -> int:
    cur = conn.execute("INSERT INTO ingest_runs(started_at,operation,status) VALUES(?,?,?)",(now(),operation,"running"))
    conn.commit(); return cur.lastrowid


def finish_run(conn, run_id: int, status="success", **kwargs):
    allowed = {"repositories_seen","repositories_cloned","games_playable","notes"}
    fields = {k:v for k,v in kwargs.items() if k in allowed}
    fields.update({"finished_at":now(),"status":status})
    sql = ",".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE ingest_runs SET {sql} WHERE id=?",(*fields.values(),run_id)); conn.commit()


def log_error(conn, run_id, repo, project_id, stage, error):
    conn.execute("INSERT INTO ingest_errors(run_id,repository_full_name,project_id,stage,error,created_at) VALUES(?,?,?,?,?,?)",
                 (run_id,repo or "",project_id or "",stage,str(error)[:3000],now()))
    conn.commit()
