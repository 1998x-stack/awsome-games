"""Reviewer controls must be explicit, auditable and idempotent."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from db import connect,seed_database,SEED_PATH
from research_pipeline import ingest,export_projection
from review_evidence import apply_manifest,validate_manifest

class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.base=Path(self.tmp.name)
        self.conn=connect(self.base/'catalog.sqlite')
        seed_database(self.conn,SEED_PATH)
        ingest(self.conn)
    def tearDown(self):
        self.conn.close();self.tmp.cleanup()
    def write(self,item):
        path=self.base/'review.json'
        path.write_text(json.dumps(item),encoding='utf-8')
        return path

    def test_dryrun_apply_reimport_are_idempotent(self):
        payload={"schema_version":1,"works":[{
            "work_id":"F52-W001","review_status":"APPROVED",
            "evidence_url":"https://github.com/Rikinshah787/Game-Fable-5.2/blob/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/README.md",
            "primary_evidence_kind":"PINNED_SOURCE_REPOSITORY","reviewer":"test-reviewer",
            "entry_path":"game/index.html","model_evidence":"PRIMARY_AUTHOR_DOCUMENTED",
            "reviewer_note":"Exact file tree verified"
        }],"posts":[]}
        file=self.write(payload)
        self.assertEqual(apply_manifest(self.conn,file,dry_run=True)["written"],0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM research_work_reviews").fetchone()[0],0)
        self.assertEqual(apply_manifest(self.conn,file)["written"],1)
        self.assertEqual(apply_manifest(self.conn,file)["written"],0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM research_review_history").fetchone()[0],1)
        ingest(self.conn)
        work=next(w for w in export_projection(self.conn)["works"] if w["work_id"]=="F52-W001")
        self.assertEqual(work["entry_path"],"game/index.html")
        self.assertEqual(work["model_evidence"],"PRIMARY_AUTHOR_DOCUMENTED")
        self.assertEqual(work["review_status"],"APPROVED")
        self.assertEqual(work["review_evidence_url"],payload["works"][0]["evidence_url"])
        self.assertFalse(work["execution_verified"])

    def test_unsafe_review_entry_rejected(self):
        payload={"schema_version":1,"works":[{"work_id":"F52-W001",
            "review_status":"APPROVED","evidence_url":"https://example.com/evidence",
            "primary_evidence_kind":"PINNED_SOURCE_REPOSITORY","reviewer":"test-reviewer",
            "reviewer_note":"fixture",
            "entry_path":"../../outside.html"}],"posts":[]}
        with self.assertRaisesRegex(ValueError,"entry"):
            validate_manifest(payload)
        payload["works"][0]["entry_path"]="index.html"
        payload["works"][0]["evidence_url"]="javascript:alert(1)"
        with self.assertRaisesRegex(ValueError,"URL"):
            validate_manifest(payload)

    def test_draft_not_exported_as_approved(self):
        payload={"schema_version":1,"works":[{"work_id":"F52-W001",
            "review_status":"DRAFT","reviewer_note":"Awaiting primary evidence",
            "entry_path":"unverified.html"}],"posts":[]}
        self.assertEqual(apply_manifest(self.conn,self.write(payload))["written"],1)
        work=next(w for w in export_projection(self.conn)["works"] if w["work_id"]=="F52-W001")
        self.assertNotEqual(work["entry_path"],"unverified.html")
        self.assertEqual(work["review_status"],"UNREVIEWED")

    def test_https_alone_does_not_establish_original_provenance(self):
        payload={"schema_version":1,"works":[{"work_id":"F52-W001",
            "review_status":"APPROVED","evidence_url":"https://example.com/unrelated",
            "primary_evidence_kind":"PINNED_SOURCE_REPOSITORY","reviewer":"analyst",
            "reviewer_note":"Source appears plausible"}],"posts":[]}
        with self.assertRaisesRegex(ValueError,"not bound"):
            apply_manifest(self.conn,self.write(payload))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM research_work_reviews").fetchone()[0],0)

    def test_unreviewed_draft_cannot_upgrade_fields(self):
        payload={"schema_version":1,"works":[{"work_id":"F52-W001",
            "review_status":"DRAFT","evidence_url":"https://example.com/unverified",
            "entry_status":"BROWSER_LOAD_CHECKED"}],"posts":[]}
        self.assertEqual(apply_manifest(self.conn,self.write(payload))["written"],1)
        obj=next(x for x in export_projection(self.conn)["works"] if x["work_id"]=="F52-W001")
        self.assertEqual(obj["review_status"],"UNREVIEWED")
        self.assertFalse(obj["execution_verified"])

    def test_unknown_work_rejected_without_writes(self):
        payload={"schema_version":1,"works":[{"work_id":"ABSENT",
            "review_status":"APPROVED","evidence_url":"https://example.com/primary",
            "primary_evidence_kind":"PINNED_SOURCE_REPOSITORY","reviewer":"test-reviewer",
            "reviewer_note":"test fixture"}],"posts":[]}
        with self.assertRaisesRegex(ValueError,"unknown work"):
            apply_manifest(self.conn,self.write(payload))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM research_work_reviews").fetchone()[0],0)

if __name__=="__main__":unittest.main()
