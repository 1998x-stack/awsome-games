"""No-network tests for conservative incremental metadata refresh."""
import sys
import json
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from refresh_research import normalize, merge_entities, prepare, write_json, post_id

class RefreshResearchTests(unittest.TestCase):
    def test_post_id_and_shapes(self):
        self.assertEqual(post_id("https://x.com/u/status/123456789?t=0"),"123456789")
        self.assertIsNone(post_id("https://example.org/hello"))
        src="https://raw.githubusercontent.com/a/b/main/data/works.json"
        r=normalize("FableList",{"id":42,"title":"A","post":"https://x.com/u/status/456",
                                  "section":"游戏","url":"https://example.com/play"},0,src)
        self.assertEqual(r["post_id"],"456")
        self.assertEqual(r["source_id"],"42")
        self.assertEqual(r["play_url"],"https://example.com/play")
        self.assertEqual(r["source_url"],"https://github.com/a/b/blob/main/data/works.json")
        g=normalize("VibeGamer",{"slug":"slug","name":"Game","tags":["FPS","Arcade"]},0,src)
        self.assertEqual(g["source_id"],"slug")
        self.assertEqual(g["category"],"FPS / Arcade")

    def test_existing_evidence_is_preserved(self):
        old=[{"post_id":"123","entity_id":"ENT-X","match_status":"MAPPED","model_claim":"AUTHOR_PROVED"}]
        new=[{"post_id":"123","source":"FableList"},{"post_id":"456","source":"Sandbase",
              "title":"New","play_url":"https://example.org/play","source_id":"2"},
             {"post_id":"456","source":"DramaSo","title":"Duplicate new","source_id":"3"}]
        merged,n=merge_entities(old,new)
        self.assertEqual(n,1)
        self.assertEqual(len(merged),2)
        self.assertEqual(merged[0],old[0])
        self.assertEqual(merged[1]["entity_resolution_status"],"PROVISIONAL_PLAYABLE_POST")
        self.assertEqual(merged[1]["work_id"],None)

    def test_shrink_guard_and_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)/"v1";base.mkdir()
            current=Path(tmp)/"current"
            previous={"schema_version":1,"records":[{"source":s,"source_id":"1"} for s in
                       ("FableList","VibeGamer","DramaSo","Sandbase")]}
            entities={"schema_version":1,"records":[]}
            write_json(base/"sources.json",previous)
            write_json(base/"entities.json",entities)
            calls=[]
            def fake_fetch(url):
                calls.append(url)
                if "works.json" in url:return []
                if "games.json" in url:return []
                if "collection.json" in url:return {"entries":[]}
                return []
            with self.assertRaisesRegex(ValueError,"Source shrank"):
                prepare(base,current,fake_fetch,allow_shrink=False)
            src,posts,count=prepare(base,current,fake_fetch,allow_shrink=True)
            self.assertEqual(len(src["records"]),0)
            self.assertEqual(len(posts["records"]),0)
            self.assertEqual(count,0)
            self.assertFalse(current.exists(),"dry run must not create or overwrite snapshots")

    def test_refresh_tool_does_not_contain_auto_execute(self):
        script=(ROOT/'scripts/refresh_research.py').read_text()
        self.assertNotIn("subprocess.run",script)
        self.assertNotIn("os.system",script)
        self.assertIn("raw.githubusercontent.com",script)

if __name__=="__main__":unittest.main()
