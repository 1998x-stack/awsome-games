"""No-network tests for conservative incremental metadata refresh."""
import sys
import json
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from refresh_research import normalize, merge_entities, prepare, write_json, post_id, load_current_pair, publish_pair

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
        self.assertEqual(merged[0]["entity_id"],old[0]["entity_id"])
        self.assertEqual(merged[0]["model_claim"],old[0]["model_claim"])
        self.assertIn("FableList",merged[0]["sources"])
        self.assertEqual(merged[1]["source_count"],2)
        self.assertIn("DramaSo",merged[1]["sources"])
        self.assertIn("Sandbase",merged[1]["sources"])
        self.assertEqual(merged[1]["entity_resolution_status"],"PROVISIONAL_PLAYABLE_POST")
        self.assertEqual(merged[1]["work_id"],None)

    def test_shrink_guard_and_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)/"v1";base.mkdir()
            current=Path(tmp)/"current"
            previous={"schema_version":1,"records":[{"source":s,"source_id":str(i)} for s in
                       ("FableList","VibeGamer","DramaSo","Sandbase") for i in (1,2)]}
            entities={"schema_version":1,"records":[]}
            write_json(base/"sources.json",previous)
            write_json(base/"entities.json",entities)
            calls=[]
            def fake_fetch(url):
                calls.append(url)
                if "works.json" in url:return [{"id":1,"title":"Demo"}]
                if "games.json" in url:return [{"slug":"game-one","name":"Demo"}]
                if "collection.json" in url:return {"entries":[{"id":1,"title":"Demo"}]}
                return [{"id":1,"title":"Demo"}]
            with self.assertRaisesRegex(ValueError,"Source shrank"):
                prepare(base,current,fake_fetch,allow_shrink=False)
            src,posts,count=prepare(base,current,fake_fetch,allow_shrink=True)
            self.assertEqual(len(src["records"]),4)
            self.assertEqual(len(posts["records"]),0)
            self.assertEqual(count,0)
            self.assertFalse(current.exists(),"dry run must not create or overwrite snapshots")
            publish_pair(src,posts,current)
            left,right=load_current_pair(base,current)
            self.assertEqual(left["records"],src["records"])
            self.assertEqual(right["records"],posts["records"])
            self.assertTrue((current/"active.json").exists())
            self.assertTrue((current/json.loads((current/"active.json").read_text())["snapshot_dir"]).is_dir())

    def test_atomic_pointer_rejects_partial_and_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)/"base";base.mkdir()
            current=Path(tmp)/"current";current.mkdir()
            write_json(base/"sources.json",{"schema_version":1,"captured_at":"2026-11-17","records":[]})
            write_json(base/"entities.json",{"schema_version":1,"captured_at":"2026-11-17","records":[]})
            (current/"sources.json").write_text("{}")
            with self.assertRaisesRegex(ValueError,"Partial legacy"):
                load_current_pair(base,current)
            (current/"sources.json").unlink()
            src={"schema_version":1,"captured_at":"2026-11-18","records":[{"source":"x"}]}
            ent={"schema_version":1,"captured_at":"2026-11-18","records":[{"post_id":"1"}]}
            publish_pair(src,ent,current)
            original=load_current_pair(base,current)
            self.assertEqual(original[0]["records"],src["records"])
            manifest=json.loads((current/"active.json").read_text())
            copy=current/manifest["snapshot_dir"]/"entities.json"
            copy.write_text('{"schema_version":1,"captured_at":"2026-11-18","records":[]}')
            with self.assertRaisesRegex(ValueError,"checksum mismatch"):
                load_current_pair(base,current)
            manifest["snapshot_dir"]="snapshots/../../escape"
            write_json(current/"active.json",manifest)
            with self.assertRaisesRegex(ValueError,"manifest path"):
                load_current_pair(base,current)

    def test_new_sources_cannot_demote_reviewed_entity(self):
        old=[{"post_id":"123","entity_id":"reviewed123","model_claim":"AUTHOR_EVIDENCE",
              "work_id":"F52-W010","entity_resolution_status":"REVIEWED","confidence":"high",
              "play_urls":["https://demo.test/"],"sources":"Old"}]
        new=[{"post_id":"123","source":"Sandbase","source_id":"new-one",
              "play_url":"https://other.test/"}]
        merged,count=merge_entities(old,new)
        self.assertEqual(count,0)
        self.assertEqual(merged[0]["entity_resolution_status"],"REVIEWED")
        self.assertEqual(merged[0]["model_claim"],"AUTHOR_EVIDENCE")
        self.assertEqual(merged[0]["work_id"],"F52-W010")
        self.assertEqual(merged[0]["play_url_count"],2)
        self.assertEqual(len(merged[0]["play_urls"]),2)

    def test_refresh_tool_does_not_contain_auto_execute(self):
        script=(ROOT/'scripts/refresh_research.py').read_text()
        self.assertNotIn("subprocess.run",script)
        self.assertNotIn("os.system",script)
        self.assertIn("raw.githubusercontent.com",script)

if __name__=="__main__":unittest.main()
