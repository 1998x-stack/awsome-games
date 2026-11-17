"""Proposals must be metadata-only summaries; they never approve source rows."""
import sys
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from propose_research_drift import make_index,source_digest,summarize


class SourceProposalTests(unittest.TestCase):
    def test_drift_summary_contains_ids_not_untrusted_source_bodies(self):
        a={"records":[
             {"source":"A","source_id":"1","title":"Before","model_claim":"NOT_TESTED"},
             {"source":"B","source_id":"9","title":"Keep"}]}
        b={"records":[
             {"source":"A","source_id":"1","title":"Updated","model_claim":"APPROVED"},
             {"source":"B","source_id":"9","title":"Keep"},
             {"source":"A","source_id":"2","title":"New"}]}
        s=summarize(a,b,1)
        self.assertEqual(s['state'],'REVIEW_REQUIRED')
        self.assertEqual(s['record_changes'],{"added":1,"removed":0,"modified":1,
                                              "added_original_post_ids":1})
        self.assertEqual(s['examples']['added_source_ids'],['A:2'])
        self.assertEqual(s['examples']['modified_source_ids'],['A:1'])
        self.assertEqual(s['scope'],'SOURCE_METADATA_ONLY')
        self.assertNotIn('model_claim',str(s))
        self.assertEqual(len(s['candidate_source_sha256']),64)
        self.assertNotEqual(s['candidate_source_sha256'],s['baseline_source_sha256'])

    def test_stable_order_and_duplicate_fails(self):
        records=[{'source':'A','source_id':'1','title':'a'},
                 {'source':'B','source_id':'2','title':'b'}]
        self.assertEqual(source_digest(make_index(records)),
                         source_digest(make_index(list(reversed(records)))))
        with self.assertRaises(ValueError):
            make_index(records+[dict(records[0])])
        with self.assertRaises(ValueError):
            make_index([{'source':'A'}])

    def test_no_drift_does_not_propose_changed_records(self):
        s=summarize({"records":[{"source":"A","source_id":"x"}]},
                    {"records":[{"source":"A","source_id":"x"}]},0)
        self.assertEqual(s['state'],'NO_SOURCE_RECORD_DRIFT')
        self.assertEqual(s['record_changes']['added'],0)
        self.assertEqual(s['record_changes']['modified'],0)


if __name__=="__main__":
    unittest.main()
