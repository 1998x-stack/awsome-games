#!/usr/bin/env python3
"""Evidence-first Fable research ingestion. Adds tables; never rewrites legacy projects."""
from __future__ import annotations
import json
import re
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "research" / "v1"

DDL = """
CREATE TABLE IF NOT EXISTS research_repositories (
 full_name TEXT PRIMARY KEY, display_title TEXT, source_channel TEXT,
 relation TEXT, tech TEXT, browser_hint TEXT, license_state TEXT,
 model_evidence TEXT, readme_url TEXT, review_level TEXT,
 evidence_url TEXT, source_note TEXT,
 browser_status TEXT NOT NULL DEFAULT 'NOT_TESTED'
);
CREATE TABLE IF NOT EXISTS research_works (
 work_id TEXT PRIMARY KEY, title TEXT NOT NULL, repository_full_name TEXT,
 demo_url TEXT, rendering_stack TEXT, build_method TEXT, artifact_kind TEXT,
 human_contribution TEXT NOT NULL DEFAULT 'UNKNOWN',
 human_status TEXT NOT NULL DEFAULT 'NOT_VERIFIED',
 external_dependencies TEXT NOT NULL DEFAULT 'NOT_VERIFIED',
 prompt_status TEXT NOT NULL DEFAULT 'NOT_VERIFIED',
 prompt_evidence_url TEXT NOT NULL DEFAULT '',
 entry_path TEXT NOT NULL DEFAULT '',
 entry_status TEXT NOT NULL DEFAULT 'UNVERIFIED',
 model_evidence TEXT NOT NULL DEFAULT 'COMMUNITY_CLAIM',
 source_url TEXT NOT NULL,
 FOREIGN KEY(repository_full_name) REFERENCES research_repositories(full_name)
);
CREATE TABLE IF NOT EXISTS research_posts (
 post_key TEXT PRIMARY KEY, entity_id TEXT NOT NULL, post_url TEXT,
 title TEXT, creator TEXT, category TEXT, sources TEXT,
 kind_signal TEXT, work_id TEXT, match_status TEXT, match_method TEXT,
 entity_status TEXT, confidence TEXT, model_claim TEXT,
 play_urls TEXT, repo_urls TEXT,
 FOREIGN KEY(work_id) REFERENCES research_works(work_id)
);
CREATE TABLE IF NOT EXISTS research_source_records (
 source TEXT NOT NULL, source_id TEXT NOT NULL, post_id TEXT,
 post_url TEXT, title TEXT, category TEXT, author TEXT,
 play_url TEXT, repo_url TEXT, source_url TEXT,
 PRIMARY KEY(source, source_id)
);
CREATE TABLE IF NOT EXISTS research_claims (
 claim_id TEXT PRIMARY KEY, item TEXT, proposition TEXT,
 status TEXT, model_recommendation TEXT, relation_recommendation TEXT,
 primary_url TEXT, counter_url TEXT, limitation TEXT
);
CREATE TABLE IF NOT EXISTS research_project_links (
 project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 work_id TEXT NOT NULL REFERENCES research_works(work_id) ON DELETE CASCADE,
 method TEXT NOT NULL, PRIMARY KEY(project_id, work_id)
);
CREATE TABLE IF NOT EXISTS research_browser_runs (
 run_id INTEGER PRIMARY KEY AUTOINCREMENT, work_id TEXT,
 repo_full_name TEXT, tested_at TEXT NOT NULL, environment TEXT,
 entry_url TEXT, result TEXT NOT NULL, console_errors TEXT NOT NULL,
 blocked_requests TEXT NOT NULL, screenshot_path TEXT,
 FOREIGN KEY(work_id) REFERENCES research_works(work_id)
);
CREATE INDEX IF NOT EXISTS idx_research_posts_entity ON research_posts(entity_id);
CREATE INDEX IF NOT EXISTS idx_research_posts_work ON research_posts(work_id);
CREATE INDEX IF NOT EXISTS idx_research_sources_post ON research_source_records(post_id);
"""

# Only verified README + GitHub tree entry associations, never infer for multi-game repos.
REVIEWED_ENTRIES = {
 ("realcodebear/saltline-fable-5.2", "saltline"): "index.html",
 ("wquguru/fable52-fps-repro", "sublevel 07"): "demos/04-fps/index.html",
 ("SharpWizard/ironvale", "ironvale"): "ironvale.html",
 ("DNDNoob/EmberDeep", "emberdeep"): "index.html",
 ("GavinLOrio/Fable-5.2-random-game", "aquila"): "index.html",
 ("GavinLOrio/Fable-5.2-random-game", "dawnward"): "rome/index.html",
 ("S77FFY/daedalus", "daedalus"): "index.html",
 ("hahaliu1029/fable5.2demo", "tidebell 潮钟"): "tidebell/index.html",
 ("hahaliu1029/fable5.2demo", "mothlight // vesper-9"): "mothlight/index.html",
 ("hahaliu1029/fable5.2demo", "青云宗 · 御剑采灵"): "game/index.html",
 ("hahaliu1029/fable5.2demo", "misremember"): "misremember/index.html",
}
# These source paths were identified in public GitHub file trees.
REVIEWED_ENTRIES = {(r.lower(), t.casefold()): p for (r,t),p in REVIEWED_ENTRIES.items()}

def read(name: str) -> dict:
    obj = json.loads((DATA / name).read_text(encoding="utf-8"))
    if obj.get("schema_version") != 1 or not isinstance(obj.get("records"), list):
        raise ValueError(f"Invalid research snapshot: {name}")
    return obj

def repo_key(url: str) -> str:
    m = re.match(r"^https://github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9_.-]+)(?:[/?#]|$)", url or "", re.I)
    return (m.group(1) + "/" + re.sub(r"\.git$", "", m.group(2), flags=re.I)).lower() if m else ""

def valid_url(url: str) -> str:
    try:
        p = urlparse(url or "")
        if p.scheme in ("https", "http") and p.netloc and not p.username and not p.password:
            return url
    except (ValueError, TypeError):
        pass
    return ""

def norm_title(s: str) -> str:
    return " ".join(str(s or "").casefold().split())

def ingest(conn: sqlite3.Connection) -> dict:
    """Upsert factual snapshots idempotently. Existing 155-item catalog is preserved."""
    conn.executescript(DDL)
    repos = read("repositories.json")["records"]
    works = read("works.json")["records"]
    posts = read("entities.json")["records"]
    sources = read("sources.json")["records"]
    claims = read("claims.json")["records"]
    audit = {str(r.get("GitHub仓库","")).lower():r for r in read("readme_audits.json")["records"]}
    repo_names = {}
    with conn:
        for r in repos:
            fullname = r.get("仓库全名") or ""
            if "/" not in fullname or repo_key(r.get("唯一URL") or "") != fullname.lower():
                raise ValueError("Invalid repository candidate: " + fullname)
            repo_names[fullname.lower()] = fullname
            conn.execute("""INSERT INTO research_repositories
                (full_name,display_title,source_channel,relation,tech,browser_hint,
                 license_state,model_evidence,readme_url,review_level,evidence_url,source_note)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(full_name) DO UPDATE SET
                display_title=excluded.display_title,source_channel=excluded.source_channel,
                relation=excluded.relation,tech=excluded.tech,browser_hint=excluded.browser_hint,
                license_state=excluded.license_state,model_evidence=excluded.model_evidence,
                readme_url=excluded.readme_url,review_level=excluded.review_level,
                evidence_url=excluded.evidence_url,source_note=excluded.source_note""",
                (fullname,r.get("关联作品或标题"),r.get("发现渠道"),r.get("关联性质"),
                 r.get("技术形态（静态检查）"),r.get("浏览器项目（启发式）"),
                 r.get("GitHub许可证检测"),r.get("模型归属核验分级"),
                 valid_url(r.get("源README/PR链接")),r.get("README核验程度"),
                 valid_url(r.get("上游索引/主链接")),r.get("源码归属备注")))
        for r in works:
            repo_raw = repo_key(r.get("GitHub仓库"))
            full_name = repo_names.get(repo_raw)
            title = str(r.get("规范作品名") or "")
            entry = REVIEWED_ENTRIES.get((repo_raw, norm_title(title)), "")
            review = audit.get(repo_raw, {})
            prompt_text = str(review.get("提示词公开情况") or "")
            prompt = "AUTHOR_DOCUMENTED" if ("是：" in prompt_text or "公开" in prompt_text) else "NOT_VERIFIED"
            conn.execute("""INSERT INTO research_works
                (work_id,title,repository_full_name,demo_url,rendering_stack,build_method,
                artifact_kind,human_contribution,human_status,external_dependencies,
                prompt_status,prompt_evidence_url,entry_path,entry_status,model_evidence,source_url)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(work_id) DO UPDATE SET
                title=excluded.title,repository_full_name=excluded.repository_full_name,
                demo_url=excluded.demo_url,rendering_stack=excluded.rendering_stack,
                build_method=excluded.build_method,artifact_kind=excluded.artifact_kind,
                human_contribution=excluded.human_contribution,human_status=excluded.human_status,
                external_dependencies=excluded.external_dependencies,prompt_status=excluded.prompt_status,
                prompt_evidence_url=excluded.prompt_evidence_url,
                entry_path=excluded.entry_path,entry_status=excluded.entry_status,
                model_evidence=excluded.model_evidence,source_url=excluded.source_url""",
                (r.get("work_id"),title,full_name,valid_url(r.get("试玩URL")),
                 r.get("渲染栈（原清单）"),r.get("构建方式（原清单）"),
                 r.get("交付形态（原清单）"),
                 str(review.get("模型归属声明") or "UNKNOWN")[:1200],
                 "AUTHOR_DESCRIPTION_ONLY" if review else "NOT_VERIFIED",
                 str(review.get("外部依赖与运行条件") or "NOT_VERIFIED")[:1200],
                 prompt,
                 {"sharpwizard/ironvale":"https://github.com/SharpWizard/ironvale/blob/main/PROMPTS.md",
                  "wquguru/fable52-fps-repro":"https://github.com/wquguru/fable52-fps-repro/tree/main/prompts"}.get(repo_raw,""),
                 entry,"TREE_PATH_REVIEWED_NOT_EXECUTED" if entry else "UNVERIFIED",
                 "COMMUNITY_CLAIM",valid_url(r.get("GitHub仓库"))))
        for r in posts:
            post_id = str(r.get("post_id") or "")
            key = post_id if re.fullmatch(r"\d+",post_id) else "orphan:" + post_id
            work_id = r.get("work_id") or None
            if work_id and not conn.execute("SELECT 1 FROM research_works WHERE work_id=?",(work_id,)).fetchone():
                work_id = None
            play = [u for u in (r.get("play_urls") or []) if valid_url(u)]
            rr = [u for u in (r.get("repository_urls") or []) if valid_url(u)]
            conn.execute("""INSERT INTO research_posts
                (post_key,entity_id,post_url,title,creator,category,sources,kind_signal,
                 work_id,match_status,match_method,entity_status,confidence,model_claim,
                 play_urls,repo_urls)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(post_key) DO UPDATE SET
                entity_id=excluded.entity_id,post_url=excluded.post_url,title=excluded.title,
                creator=excluded.creator,category=excluded.category,sources=excluded.sources,
                kind_signal=excluded.kind_signal,work_id=excluded.work_id,
                match_status=excluded.match_status,match_method=excluded.match_method,
                entity_status=excluded.entity_status,confidence=excluded.confidence,
                model_claim=excluded.model_claim,play_urls=excluded.play_urls,repo_urls=excluded.repo_urls""",
                (key,r.get("entity_id"),valid_url(r.get("post_url")),r.get("title"),
                 r.get("creator"),r.get("category"),r.get("sources"),r.get("kind_signal"),
                 work_id,r.get("match_status"),r.get("match_method"),
                 r.get("entity_resolution_status"),r.get("confidence"),r.get("model_claim"),
                 json.dumps(play,ensure_ascii=False),json.dumps(rr,ensure_ascii=False)))
        for r in sources:
            conn.execute("""INSERT INTO research_source_records
                (source,source_id,post_id,post_url,title,category,author,play_url,repo_url,source_url)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source,source_id) DO UPDATE SET
                post_id=excluded.post_id,post_url=excluded.post_url,title=excluded.title,
                category=excluded.category,author=excluded.author,play_url=excluded.play_url,
                repo_url=excluded.repo_url,source_url=excluded.source_url""",
                (r.get("source"),r.get("source_id"),r.get("post_id"),
                 valid_url(r.get("post_url")),r.get("title"),r.get("category"),r.get("author"),
                 valid_url(r.get("play_url")),valid_url(r.get("repo_url")),valid_url(r.get("source_url"))))
        for r in claims:
            conn.execute("""INSERT INTO research_claims
                (claim_id,item,proposition,status,model_recommendation,relation_recommendation,
                 primary_url,counter_url,limitation)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(claim_id) DO UPDATE SET
                item=excluded.item,proposition=excluded.proposition,status=excluded.status,
                model_recommendation=excluded.model_recommendation,
                relation_recommendation=excluded.relation_recommendation,
                primary_url=excluded.primary_url,counter_url=excluded.counter_url,
                limitation=excluded.limitation""",
                (r.get("论断ID"),r.get("项目/实体"),r.get("需要判断的论断"),
                 r.get("证据状态"),r.get("模型记录建议"),r.get("项目关系建议"),
                 valid_url(r.get("证据来源链接")),valid_url(r.get("原帖/补充链接")),
                 r.get("仍需核实")))
        # Exact repo + title only. No fuzzy matches and no migration of Fable model claims.
        conn.execute("DELETE FROM research_project_links")
        for r in conn.execute("""SELECT p.id AS project_id,p.title AS title,
              r.full_name AS repo FROM projects p JOIN project_repositories pr ON pr.project_id=p.id
              JOIN repositories r ON r.id=pr.repository_id""").fetchall():
            for w in conn.execute("SELECT work_id,title FROM research_works WHERE lower(repository_full_name)=lower(?)",(r["repo"],)).fetchall():
                if norm_title(r["title"])==norm_title(w["title"]):
                    conn.execute("INSERT OR IGNORE INTO research_project_links VALUES (?,?,?)",
                                 (r["project_id"],w["work_id"],"EXACT_REPO_AND_TITLE"))
    return counts(conn)

def counts(conn: sqlite3.Connection) -> dict:
    return {k:conn.execute("SELECT COUNT(*) FROM research_"+k).fetchone()[0] for k in
            ("repositories","works","posts","source_records","claims","project_links")}

def project_links(conn: sqlite3.Connection) -> dict:
    rows=conn.execute("SELECT project_id,work_id FROM research_project_links").fetchall()
    out={}
    for p,w in rows:out.setdefault(p,[]).append(w)
    return out

def export_projection(conn: sqlite3.Connection) -> dict:
    def objs(q):
        return [dict(row) for row in conn.execute(q)]
    works=objs("""SELECT w.*, r.model_evidence AS repository_model_evidence,
        r.relation AS repository_relation,r.license_state,r.review_level,r.readme_url,
        r.browser_status FROM research_works w LEFT JOIN research_repositories r
        ON r.full_name=w.repository_full_name ORDER BY w.work_id""")
    for w in works:
        w["evidence_level"]="READ_ME_REVIEWED" if w["review_level"]=="README_REVIEWED" else "COMMUNITY_INDEX_ONLY"
        w["execution_verified"]=False  # Never promote static entry detection into actual gameplay verification.
    posts=objs("""SELECT post_key,entity_id,post_url,title,creator,category,sources,
        kind_signal,work_id,match_status,entity_status,confidence,model_claim,play_urls,repo_urls
        FROM research_posts ORDER BY post_key""")
    for p in posts:
        p["play_urls"]=json.loads(p["play_urls"]);p["repo_urls"]=json.loads(p["repo_urls"])
    repos=objs("""SELECT full_name,display_title,source_channel,relation,tech,browser_hint,
        license_state,model_evidence,readme_url,review_level,evidence_url,source_note,browser_status
        FROM research_repositories ORDER BY lower(full_name)""")
    claims=objs("""SELECT * FROM research_claims ORDER BY claim_id""")
    stats=counts(conn)
    return {"schema_version":1,"captured_at":"2026-11-17",
            "warning":"Source records, original posts and works are different units. No third-party gameplay has been executed or verified.",
            "stats":stats,"works":works,"posts":posts,"repositories":repos,
            "claims":claims}

if __name__ == "__main__":
    from db import connect
    conn=connect()
    result=ingest(conn)
    print(json.dumps(result,ensure_ascii=False))
    conn.close()
