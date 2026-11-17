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
