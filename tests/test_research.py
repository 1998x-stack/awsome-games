"""Regression tests: research evidence is additive, idempotent, and never confuses entry with gameplay."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from db import connect, seed_database, SEED_PATH
from research_pipeline import ingest, counts, export_projection, valid_url, repo_key, REVIEWED_ENTRIES, classify_prompt_evidence
from browser_smoke import clean_entry

class ResearchIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.conn=connect(Path(cls.tmp.name)/'research.sqlite')
        cls.legacy_count=seed_database(cls.conn,SEED_PATH)
        cls.before=cls.conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        cls.counts=ingest(cls.conn)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    def test_all_source_snapshots_are_present(self):
        self.assertEqual(self.counts["repositories"],83)
        self.assertEqual(self.counts["works"],64)
        self.assertEqual(self.counts["posts"],907)
        self.assertEqual(self.counts["source_records"],1118)
        self.assertEqual(self.counts["claims"],12)
        self.assertGreaterEqual(self.counts["project_links"],25)

    def test_legacy_catalog_is_not_clobbered(self):
        self.assertEqual(self.legacy_count,155)
        self.assertEqual(self.before,155)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0],155)
        self.assertEqual(self.conn.execute("PRAGMA integrity_check").fetchone()[0],"ok")
        self.assertEqual(self.conn.execute("PRAGMA foreign_key_check").fetchall(),[])

    def test_reimport_is_idempotent(self):
        second=ingest(self.conn)
        self.assertEqual(second,self.counts)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0],155)

    def test_unique_original_posts_and_unresolved_are_distinct(self):
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM research_posts WHERE post_key GLOB '[0-9]*'").fetchone()[0],906)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM research_posts WHERE post_key LIKE 'orphan:%'").fetchone()[0],1)
        self.assertGreater(self.conn.execute("SELECT COUNT(*) FROM research_posts WHERE entity_status LIKE '%UNRESOLVED%'").fetchone()[0],500)
        self.assertEqual(self.conn.execute("SELECT COUNT(DISTINCT post_key) FROM research_posts").fetchone()[0],907)

    def test_conservative_work_entry_status(self):
        row=self.conn.execute("SELECT entry_path,entry_status FROM research_works WHERE title='Dawnward'").fetchone()
        self.assertEqual(row["entry_path"],"rome/index.html")
        self.assertEqual(row["entry_status"],"TREE_PATH_REVIEWED_NOT_EXECUTED")
        row=self.conn.execute("SELECT entry_path FROM research_works WHERE title='SUBLEVEL 07'").fetchone()
        self.assertEqual(row["entry_path"],"demos/04-fps/index.html")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM research_browser_runs").fetchone()[0],0)
        data=export_projection(self.conn)
        self.assertTrue(all(x["execution_verified"] is False for x in data["works"]))

    def test_prompt_negation_and_human_contribution_semantics(self):
        self.assertEqual(classify_prompt_evidence("未发现公开原始提示词"), "NOT_LOCATED")
        self.assertEqual(classify_prompt_evidence("提示词未公开"), "NOT_LOCATED")
        self.assertEqual(classify_prompt_evidence("是：PROMPTS.md列出21条提示词"), "PUBLISHED_AUTHOR_MATERIAL")
        self.assertEqual(classify_prompt_evidence("部分需求原文、实现报告公开"), "PARTIAL_MATERIALS_NEED_REVIEW")
        rows={x["repository_full_name"].casefold():x for x in self.conn.execute(
            "SELECT * FROM research_works WHERE repository_full_name LIKE 'SharpWizard/%' OR repository_full_name LIKE 'realcodebear/%'")}
        self.assertEqual(rows["realcodebear/saltline-fable-5.2"]["prompt_status"],"NOT_LOCATED")
        self.assertEqual(rows["sharpwizard/ironvale"]["prompt_status"],"PUBLISHED_AUTHOR_MATERIAL")
        self.assertIn("21",rows["sharpwizard/ironvale"]["human_contribution"])
        self.assertNotIn("README称",rows["sharpwizard/ironvale"]["human_contribution"])

    def test_approved_editorial_review_survives_snapshot_reimport(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            conn=connect(Path(tmp)/"curation.sqlite")
            seed_database(conn,SEED_PATH)
            ingest(conn)
            conn.execute("""INSERT INTO research_work_reviews
                (work_id,review_status,evidence_url,entry_path,prompt_status,
                 human_contribution,reviewed_at)
                VALUES(?,?,?,?,?,?,?)""",
                ("F52-W001","APPROVED","https://github.com/example/evidence",
                 "reviewed/index.html","PUBLISHED_AUTHOR_MATERIAL","Human edit witnessed","2026-11-17"))
            first=conn.execute("SELECT post_key FROM research_posts WHERE post_key GLOB '[0-9]*' LIMIT 1").fetchone()[0]
            conn.execute("""INSERT INTO research_post_reviews
                (post_key,review_status,evidence_url,entity_id,confidence,reviewed_at)
                VALUES(?,?,?,?,?,?)""",
                (first,"APPROVED","https://example.org/specific-source",
                 "CURATED-ENTITY","author_documentation","2026-11-17"))
            conn.commit()
            ingest(conn)
            export=export_projection(conn)
            work=next(w for w in export["works"] if w["work_id"]=="F52-W001")
            post=next(p for p in export["posts"] if p["post_key"]==first)
            self.assertEqual(work["entry_path"],"reviewed/index.html")
            self.assertEqual(work["prompt_status"],"PUBLISHED_AUTHOR_MATERIAL")
            self.assertEqual(work["review_status"],"APPROVED")
            self.assertEqual(post["entity_id"],"CURATED-ENTITY")
            self.assertEqual(post["review_status"],"APPROVED")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM research_work_reviews").fetchone()[0],1)
            conn.close()

    def test_source_snapshot_replacement_does_not_falsify_count(self):
        import research_pipeline
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            conn=connect(Path(tmp)/"snapshot.sqlite")
            seed_database(conn,SEED_PATH)
            ingest(conn)
            original=research_pipeline.read
            def one_source(name):
                value=original(name)
                if name=="sources.json":
                    value=dict(value)
                    value["records"]=value["records"][:7]
                    value["captured_at"]="2026-12-01"
                return value
            with patch.object(research_pipeline,"read",side_effect=one_source):
                stats=ingest(conn)
                self.assertEqual(stats["source_records"],7)
                self.assertEqual(export_projection(conn)["captured_at"],"2026-12-01")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM research_source_records").fetchone()[0],7)
            conn.close()

    def test_model_conflicts_are_not_promoted_to_fable(self):
        rows={x["item"]:x for x in self.conn.execute("SELECT * FROM research_claims")}
        self.assertIn("One Sweep",rows)
        self.assertEqual(rows["One Sweep"]["status"],"DISPUTED")
        self.assertEqual(rows["Kagami"]["status"],"REFUTED")
        self.assertEqual(rows["RYŪ"]["status"],"REFUTED")
        out=export_projection(self.conn)
        self.assertEqual(out["stats"]["repositories"],83)
        self.assertTrue(any(x["model_evidence"]=="AUTHOR_CLAIM_OTHER_MODEL_OPUS_5_5" for x in out["repositories"]))

    def test_project_link_requires_exact_repo_and_title(self):
        links=self.conn.execute("""SELECT p.title AS title,w.title AS work_title,
            lower(r.full_name) AS original_repo,lower(w.repository_full_name) AS research_repo
            FROM research_project_links k
            JOIN projects p ON p.id=k.project_id
            JOIN research_works w ON w.work_id=k.work_id
            JOIN project_repositories pr ON pr.project_id=p.id
            JOIN repositories r ON r.id=pr.repository_id
            WHERE lower(r.full_name)=lower(w.repository_full_name)""").fetchall()
        self.assertTrue(links)
        self.assertTrue(all(x["title"].casefold().strip()==x["work_title"].casefold().strip() for x in links))

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for JS syntax check")
    def test_research_page_js_syntax_and_untrusted_text_policy(self):
        result=subprocess.run(["node","--check",str(ROOT/'site/assets/research.js')],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        js=(ROOT/'site/assets/research.js').read_text()
        self.assertIn("textContent",js)
        self.assertNotIn("innerHTML",js)
        self.assertIn("rel='noopener noreferrer'",js)
        html=(ROOT/'site/research.html').read_text()
        self.assertIn('script src="./assets/research.js"',html)

    def test_urls_and_paths_reject_unsafe_input(self):
        self.assertEqual(repo_key("https://github.com/Owner/Game/pull/7"),"owner/game")
        self.assertFalse(valid_url("javascript:alert(1)"))
        self.assertFalse(valid_url("https://u:p@github.com/repo"))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'demo.html').write_text("<title>fixture</title>")
            self.assertEqual(clean_entry(root,'demo.html'),(root/'demo.html').resolve())
            for path in ("../secret.html","/etc/passwd","folder/../demo.html","demo.js"):
                with self.assertRaises(ValueError):clean_entry(root,path)

if __name__=="__main__":
    unittest.main()
