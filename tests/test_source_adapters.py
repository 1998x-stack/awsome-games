"""M4 adapters preserve four upstream normalizations without fetching external URLs."""
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from source_adapters import ADAPTERS, BY_NAME, SourceAdapter
from refresh_research import normalize, post_id, SOURCES


class SourceAdapterTests(unittest.TestCase):
    def test_registry_is_unique_and_pinned_to_readonly_metadata(self):
        self.assertEqual(len(ADAPTERS),4)
        self.assertEqual({x.name for x in ADAPTERS},
                         {"FableList","VibeGamer","DramaSo","Sandbase"})
        self.assertEqual(tuple((a.name,a.url) for a in ADAPTERS),SOURCES)
        self.assertTrue(all(a.url.startswith("https://raw.githubusercontent.com/") for a in ADAPTERS))

    def test_schema_variants_and_original_source_links(self):
        for name in BY_NAME:
            a=BY_NAME[name]
            payload={"entries":[{"id":"a"}]} if a.collection_key else [{"id":"a"}]
            self.assertEqual(len(a.entries(payload)),1)
            with self.assertRaises(ValueError):
                a.entries([1])
            with self.assertRaises(ValueError):
                a.entries([])
        row=normalize("VibeGamer",
            {"slug":"v1","maker":{"handle":"original-author"},
             "name":"demo","tags":["3D","FPS"],"post_url":"https://x.com/a/status/456",
             "play_url":"https://example.com/play","open_source_url":"https://github.com/owner/demo"},
             0,BY_NAME["VibeGamer"].url)
        self.assertEqual(row["source_id"],"v1")
        self.assertEqual(row["author"],"original-author")
        self.assertEqual(row["category"],"3D / FPS")
        self.assertEqual(row["post_id"],"456")
        self.assertIn("/blob/main/",row["source_url"])
        self.assertEqual(row["repo_url"],"https://github.com/owner/demo")
        with self.assertRaisesRegex(ValueError,"tags"):
            normalize("VibeGamer",{"tags":"BAD"},1,BY_NAME["VibeGamer"].url)

    def test_sources_remain_metadata_not_author_verification(self):
        for a in ADAPTERS:
            result=a.normalize({},0,a.url,post_id)
            self.assertNotIn("APPROVED",str(result))
            self.assertNotIn("model_evidence",result)
            self.assertEqual(result["post_id"],None)

if __name__=="__main__":
    unittest.main()
