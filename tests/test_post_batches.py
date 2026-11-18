"""Frozen M1 post queues must cover leads without auto-promoting works."""
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from make_post_batches import build
class PostBatchTests(unittest.TestCase):
    def test_stable_partition_and_no_false_approvals(self):
        result=build()
        self.assertEqual(result['total_posts'],907)
        self.assertEqual(result['unresolved_posts'],904)
        self.assertEqual(result['mapped_posts'],2)
        self.assertEqual(result['candidate_posts'],1)
        self.assertEqual(len(result['batches']),40)
        all_posts=[r['post_key'] for b in result['batches'] for r in b['records']]
        self.assertEqual(len(all_posts),907)
        self.assertEqual(len(set(all_posts)),907)
        self.assertTrue(all(len(b['records'])<=25 and b['queue_state']=='UNREVIEWED'
                            for b in result['batches']))
        self.assertEqual({g['id']:g['posts'] for g in result['groups']},
          {'P00_MAPPED':2,'P01_CANDIDATE':1,'P10_REPO_LEADS':19,
           'P20_GAME_PLAY':175,'P21_OTHER_PLAY':6,
           'P30_GAME_NO_LINK':99,'P40_OTHER_NO_LINK':33,'P50_VIDEO_SCENE_TOOL':572})
if __name__=='__main__':unittest.main()
