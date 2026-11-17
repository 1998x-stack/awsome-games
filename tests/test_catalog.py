import json, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from db import connect, seed_database, classify, model_version, parse_repo, infer_relation, infer_entry_path
from collect_repositories import choose_entry, safe_rel_path, should_skip

class CatalogTests(unittest.TestCase):
    def test_seed_import_and_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn=connect(Path(tmp)/'catalog.sqlite')
            missing=Path(tmp)/'missing-seed.jsonl'
            with patch('db.SEED_PATH', missing):
                n=seed_database(conn,missing)
            self.assertEqual(n,155)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM projects').fetchone()[0],155)
            self.assertGreaterEqual(conn.execute('SELECT COUNT(*) FROM repositories').fetchone()[0],50)
            self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(),[])
            conn.close()
    def test_author_reviewed_model_survives_seed_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn=connect(Path(tmp)/'catalog.sqlite')
            seed_database(conn, SEED_PATH)
            original=conn.execute("SELECT id,model_claim,model_version FROM projects LIMIT 1").fetchone()
            conn.execute("UPDATE projects SET model_claim=?,model_version=?,model_confidence=? WHERE id=?",
                         ("AUTHOR_CONFIRMED_OPUS_5_5","5.5","author_documentation",original["id"]))
            conn.commit()
            seed_database(conn, SEED_PATH)
            row=conn.execute("SELECT model_claim,model_version,model_confidence FROM projects WHERE id=?",
                             (original["id"],)).fetchone()
            self.assertEqual(row["model_claim"],"AUTHOR_CONFIRMED_OPUS_5_5")
            self.assertEqual(row["model_version"],"5.5")
            self.assertEqual(row["model_confidence"],"author_documentation")
            conn.close()

    def test_classification(self):
        self.assertEqual(classify('FPS'),'fps')
        self.assertEqual(classify('RTS'),'strategy')
        self.assertEqual(classify('single_html_visual_study'),'visual_experiment')
        self.assertEqual(classify('video_only'),'video_demo')
        self.assertEqual(classify('3D 竞速'),'racing')
    def test_model_version(self):
        self.assertEqual(model_version('claude-fable-5-1'),'5.1')
        self.assertEqual(model_version('claude-fable-5-2'),'5.2')
        self.assertEqual(model_version('unknown'),'unknown')
    def test_repository_parser_and_roles(self):
        self.assertEqual(parse_repo('owner/game')['clone_url'],'https://github.com/owner/game.git')
        self.assertIsNone(parse_repo('not-a-repository'))
        for value in ('../evil', 'user/..', 'user/repo?x=1', 'user/repo\\nheader', 'user/name with spaces'):
            self.assertIsNone(parse_repo(value),value)
        self.assertEqual(infer_relation('sorrycc/fable-arcade'),'collection')
        self.assertEqual(infer_relation('realcodebear/saltline-fable-5.2'),'third_party_mirror')
    def test_entry_path_inference(self):
        p={'sources':['https://github.com/MiaAI-Lab/Claude-Fable-5.2-HTML-Files/blob/main/001-test.html']}
        self.assertEqual(infer_entry_path(p,'MiaAI-Lab/Claude-Fable-5.2-HTML-Files'),'001-test.html')
        p={'plays':['https://sorrycc.github.io/fable-arcade/games/flappy-bird/']}
        self.assertEqual(infer_entry_path(p,'sorrycc/fable-arcade'),'games/flappy-bird/index.html')
    def test_choose_entry(self):
        p={'id':'1','slug':'starry-nightrider','title':'Starry Nightrider','entry_path':''}
        entry,confidence=choose_entry(p,['starry-nightrider/index.html','docs/index.html'],1)
        self.assertEqual(entry,'starry-nightrider/index.html')
        self.assertEqual(confidence,'title_path_match')
        p={'id':'2','slug':'a','title':'A','entry_path':''}
        self.assertEqual(choose_entry(p,['index.html','about.html'],2)[0],'')
        unsafe={'id':'3','slug':'demo','title':'Demo','entry_path':'../../index.html'}
        self.assertEqual(choose_entry(unsafe,['index.html'],1),('', 'unsafe_explicit_entry'))
    def test_path_and_secret_filters(self):
        self.assertIsNone(safe_rel_path('../evil.html'))
        self.assertEqual(safe_rel_path('games/index.html'),'games/index.html')
        self.assertTrue(should_skip('.env',20,1000)[0])
        self.assertTrue(should_skip('node_modules/pkg/index.js',20,1000)[0])
        self.assertFalse(should_skip('assets/scene.png',20,1000)[0])

if __name__=='__main__': unittest.main()
