"""Browser evidence import uses genuine staged file hashes but never asserts gameplay."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from db import connect,seed_database,SEED_PATH
from research_pipeline import ingest,export_projection
from import_browser_report import prepare_evidence,save_evidence,staged_entry,validate_report


class RuntimeEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.tmp.name)
        cls.conn=connect(cls.root/"runtime.sqlite")
        seed_database(cls.conn,SEED_PATH)
        ingest(cls.conn)
        path=cls.root/"demos"/"04-fps"/"index.html"
        path.parent.mkdir(parents=True)
        path.write_text("<html><body>safe fixture</body></html>",encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    def report(self):
        return {"tested_at":"2026-11-17T00:00:00+00:00",
                "entry":"demos/04-fps/index.html","status":"BROWSER_LOAD_CHECKED",
                "iframe_isolation":True,"frame_body_loaded":True,
                "console_errors":[],"blocked_requests":[],"blocked_websockets":[],
                "failed_requests":[],"http_errors":[],"gameplay_verified":False}

    def test_roundtrip_provides_hash_and_remains_not_gameplay_verified(self):
        item=prepare_evidence(self.conn,work_id="F52-W012",commit_sha="a"*40,
            root=self.root,report=self.report(),browser_version="fixture-123",environment="test-only")
        self.assertEqual(len(item["entry_sha256"]),64)
        save_evidence(self.conn,item)
        save_evidence(self.conn,item)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM research_runtime_evidence WHERE evidence_id=?",
                                            (item["evidence_id"],)).fetchone()[0],1)
        work=next(w for w in export_projection(self.conn)["works"] if w["work_id"]=="F52-W012")
        self.assertEqual(work["latest_browser_evidence"]["report_status"],"BROWSER_LOAD_CHECKED")
        self.assertFalse(work["execution_verified"])

    def test_bad_evidence_fails_closed(self):
        report=self.report()
        report["gameplay_verified"]=True
        with self.assertRaises(ValueError):
            validate_report(report,"demos/04-fps/index.html")
        report=self.report()
        report["console_errors"]=["Uncaught Error"]
        with self.assertRaises(ValueError):
            validate_report(report,"demos/04-fps/index.html")
        with self.assertRaises(ValueError):
            staged_entry(self.root,"../outside.html")
        with self.assertRaises(ValueError):
            prepare_evidence(self.conn,work_id="F52-W012",commit_sha="mutable-main",
                             root=self.root,report=self.report(),browser_version="x",environment="test")


if __name__=="__main__":
    unittest.main()
