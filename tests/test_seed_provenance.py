"""Evidence provenance must survive the SQLite -> JSONL -> SQLite round trip.

`export_seed.py` reconstructs a seed from a committed snapshot. It used to
hardcode a synthetic `sqlite_snapshot_reconstruction` evidence type, so every
rebuild re-inserted a placeholder row next to the real citation, doubling
`project_evidence` and publishing a fake "source" for every project.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import db as db_module
import export_seed


class SeedProvenanceRoundTripTests(unittest.TestCase):
    def test_round_trip_preserves_real_evidence_types_and_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = db_module.connect(Path(tmp) / 'first.sqlite')
            self.assertEqual(db_module.seed_database(first, db_module.SEED_PATH), 155)
            def evidence_rows(conn):
                return sorted((r[0], r[1], r[2]) for r in conn.execute(
                    'SELECT project_id, evidence_type, confidence FROM project_evidence'))
            original = evidence_rows(first)
            self.assertTrue(original, 'committed seed must carry real provenance')
            self.assertFalse(
                any(row[1] in db_module.SYNTHETIC_EVIDENCE_TYPES for row in original))

            seed = Path(tmp) / 'seed.jsonl'
            self.assertEqual(export_seed.export_seed(Path(tmp) / 'first.sqlite', seed), 155)
            second = db_module.connect(Path(tmp) / 'second.sqlite')
            self.assertEqual(db_module.seed_database(second, seed), 155)

            self.assertEqual(evidence_rows(second), original,
                             're-import changed evidence types, confidences or counts')
            self.assertEqual(
                second.execute('SELECT COUNT(*) FROM project_evidence').fetchone()[0],
                len(original))
            first.close()
            second.close()

    def test_multiple_evidence_types_same_source_round_trip(self):
        """A source URL is not a unique evidence claim; keep both true types."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            seed = path / 'multi.jsonl'
            url = 'https://github.com/owner/original-work'
            seed.write_text(json.dumps({
                'project_id':'fab_multi', 'title':'Multiple provenance',
                'repos':[], 'sources':[url],
                'evidence_by_source': {url:[
                    {'evidence_type':'repository_documentation','confidence':'medium'},
                    {'evidence_type':'author_original_statement','confidence':'high'},
                    {'evidence_type':'sqlite_snapshot_reconstruction','confidence':'low'},
                ]},
            })+'\n',encoding='utf-8')
            first=db_module.connect(path/'first.sqlite')
            self.assertEqual(db_module.seed_database(first,seed),1)
            def snapshot(c):
                return [(r['evidence_type'],r['confidence']) for r in
                        c.execute("""SELECT pe.evidence_type,pe.confidence FROM project_evidence pe
                         JOIN evidence_sources e ON e.id=pe.evidence_source_id
                         WHERE e.url=? ORDER BY pe.evidence_type""",(url,))]
            self.assertEqual(snapshot(first),[
                ('author_original_statement','high'),
                ('repository_documentation','medium')])
            exported=path/'export.jsonl'
            self.assertEqual(export_seed.export_seed(path/'first.sqlite',exported),1)
            data=json.loads(exported.read_text(encoding='utf-8'))
            self.assertEqual(len(data['evidence_by_source'][url]),2)
            second=db_module.connect(path/'second.sqlite')
            self.assertEqual(db_module.seed_database(second,exported),1)
            self.assertEqual(snapshot(first),snapshot(second))
            self.assertEqual(db_module.seed_database(second,exported),1)
            self.assertEqual(len(snapshot(second)),2)
            first.close();second.close()

    def test_reconstruction_marker_never_becomes_a_citation(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed = Path(tmp) / 'marker.jsonl'
            seed.write_text(json.dumps({
                'project_id': 'fab_deadbeef0000',
                'title': 'Marker only',
                'repos': [],
                'sources': ['https://example.org/only-reconstruction'],
                'evidence': ['sqlite_snapshot_reconstruction'],
                'evidence_by_source': {
                    'https://example.org/only-reconstruction': {
                        'evidence_type': 'sqlite_snapshot_reconstruction',
                        'confidence': 'low',
                    },
                },
            }) + '\n', encoding='utf-8')
            conn = db_module.connect(Path(tmp) / 'marker.sqlite')
            self.assertEqual(db_module.seed_database(conn, seed), 1)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM projects').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM project_evidence').fetchone()[0], 0,
                             'a reconstruction marker must not be stored as evidence')
            # The record itself is still recorded so nothing is silently lost.
            self.assertEqual(
                conn.execute('SELECT source_status FROM projects').fetchone()[0], 'no_repository')
            conn.close()

    def test_export_rejects_corrupt_evidence_by_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed = Path(tmp) / 'bad.jsonl'
            seed.write_text(json.dumps({
                'project_id': 'fab_bad00000000',
                'title': 'Bad provenance',
                'sources': ['https://example.org/x'],
                'evidence_by_source': ['not-a-mapping'],
            }) + '\n', encoding='utf-8')
            conn = db_module.connect(Path(tmp) / 'bad.sqlite')
            with self.assertRaisesRegex(ValueError, 'evidence_by_source'):
                db_module.seed_database(conn, seed)
            conn.close()


if __name__ == '__main__':
    unittest.main()
