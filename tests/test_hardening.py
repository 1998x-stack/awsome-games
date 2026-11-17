"""Regression coverage for source ingestion and permission-gated static publishing."""
import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import collect_repositories as collector
import build_site as publisher


class CollectorHardeningTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.base=Path(self.tmp.name)
        self.repo=self.base/'upstream'
        self.repo.mkdir()
        subprocess.run(['git','init','-q',str(self.repo)],check=True)
        subprocess.run(['git','-C',str(self.repo),'config','user.email','test@example.invalid'],check=True)
        subprocess.run(['git','-C',str(self.repo),'config','user.name','Test'],check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def track(self):
        subprocess.run(['git','-C',str(self.repo),'add','-A'],check=True)
        subprocess.run(['git','-C',str(self.repo),'commit','-qm','fixture'],check=True)

    def test_atomic_copy_secrets_and_symlinks(self):
        (self.repo/'index.html').write_text('<script src="./main.js"></script>')
        (self.repo/'main.js').write_text('console.log("ok")')
        (self.repo/'.env').write_text('SENSITIVE=do-not-copy')
        (self.repo/'big.dat').write_bytes(b'A'*101)
        (self.repo/'link.html').symlink_to(self.repo/'index.html')
        self.track()
        with patch.object(collector,'DEST',self.base/'snapshot'):
            dest,files,total,skip=collector.copy_tracked_tree('example/game',self.repo,100,1000)
        self.assertTrue((dest/'index.html').is_file())
        self.assertTrue((dest/'main.js').is_file())
        self.assertFalse((dest/'.env').exists())
        self.assertFalse((dest/'link.html').exists())
        self.assertFalse((dest/'big.dat').exists())
        self.assertEqual(skip['sensitive_file'],1)
        self.assertEqual(skip['file_too_large'],1)
        self.assertEqual(skip['unsafe_source'],1)
        self.assertEqual(len(files),2)

    def test_previous_snapshot_survives_copy_failure(self):
        existing=self.base/'snapshot'/'example__game'
        existing.mkdir(parents=True)
        (existing/'keep.txt').write_text('valuable')
        with patch.object(collector,'DEST',self.base/'snapshot'),patch.object(collector,'tracked_files',side_effect=RuntimeError('simulated I/O failure')):
            with self.assertRaisesRegex(RuntimeError,'simulated'):
                collector.copy_tracked_tree('example/game',self.repo,100,1000)
        self.assertEqual((existing/'keep.txt').read_text(),'valuable')
        self.assertFalse(list((self.base/'snapshot').glob('.partial-*')))

    def test_assets_relative_parent_allowed_but_escape_rejected(self):
        (self.repo/'games').mkdir()
        (self.repo/'shared').mkdir()
        (self.repo/'shared'/'sprite.png').write_bytes(b'png')
        (self.repo/'games'/'index.html').write_text('<img src="../shared/sprite.png">')
        self.assertEqual(collector.missing_static_assets(self.repo,'games/index.html'),[])
        (self.repo/'games'/'index.html').write_text('<img src="../../../etc/passwd"><script src="missing.js"></script>')
        self.assertEqual(len(collector.missing_static_assets(self.repo,'games/index.html')),2)

    def test_reject_malicious_paths(self):
        for bad in ('../outside','/etc/passwd','C:\\windows\\system32','./index.html','a//b','a/../b',''):
            self.assertIsNone(collector.safe_rel_path(bad),bad)


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.base=Path(self.tmp.name)
        (self.base/'site').mkdir()
        (self.base/'games/_repos/example__game').mkdir(parents=True)
        (self.base/'games/_repos/example__game/index.html').write_text('<!doctype html><title>game</title>')
        (self.base/'config').mkdir()
        (self.base/'config/publication_approvals.json').write_text(json.dumps({'approved_repositories':[]}))
        self.data={'generated_at':'2026-11-16','repository_ref':'fixture','summary':{'projects':1,'repositories':1,'projects_with_html_entrypoints':1},'projects':[{'title':'game','repositories':[{'full_name':'example/game','game_path':'games/_repos/example__game/index.html','playable_status':'entrypoint_found'}]}]}

    def tearDown(self):
        self.tmp.cleanup()

    def publish(self,allow=False,max_size=1024*1024,preview=False):
        (self.base/'config/publication_approvals.json').write_text(json.dumps({'approved_repositories':['example/game'] if allow else []}))
        with patch.object(publisher,'ROOT',self.base),patch.object(publisher,'APPROVALS',self.base/'config/publication_approvals.json'),patch.object(publisher,'connect',return_value=MagicMock()),patch.object(publisher,'export_catalog',return_value=copy.deepcopy(self.data)):
            result=publisher.build_site(include_unapproved=preview,max_site_bytes=max_size)
            public=json.loads((self.base/'site/data/catalog.json').read_text())
            return result,public

    def test_default_does_not_publish_unlicensed_code(self):
        result,catalog=self.publish()
        self.assertEqual(result['published_games'],0)
        self.assertFalse((self.base/'site/games/_repos/example__game/index.html').exists())
        self.assertEqual(catalog['projects'][0]['published_game_path'],'')

    def test_approved_repo_publishes_correct_relative_path(self):
        result,catalog=self.publish(allow=True)
        self.assertEqual(result['published_games'],1)
        self.assertTrue((self.base/'site/games/_repos/example__game/index.html').is_file())
        self.assertEqual(catalog['projects'][0]['published_game_path'],'games/_repos/example__game/index.html')

    def test_publication_size_cap_enforced(self):
        with self.assertRaisesRegex(RuntimeError,'Pages artifact'):
            self.publish(allow=True,max_size=5)

    def test_approved_snapshots_never_copy_secrets_or_executable_scripts(self):
        path=self.base/'games/_repos/example__game'
        (path/'.env.production').write_text('DO_NOT_PUBLISH=secret')
        (path/'credentials.json').write_text('{"token":"secret"}')
        (path/'run.sh').write_text('echo not a web asset')
        (path/'image.svg').write_text('<svg/>')
        self.publish(allow=True)
        site=self.base/'site/games/_repos/example__game'
        self.assertFalse((site/'.env.production').exists())
        self.assertFalse((site/'credentials.json').exists())
        self.assertFalse((site/'run.sh').exists())
        self.assertTrue((site/'index.html').exists())
        self.assertTrue((site/'image.svg').exists())

    def test_approved_snapshot_symlink_escape_fails_closed_and_keeps_old_site(self):
        source=self.base/'games/_repos/example__game'
        outside=self.base/'outside.txt'
        outside.write_text('PRIVATE')
        (source/'escape.json').symlink_to(outside)
        old=self.base/'site/games/_repos/example__game'
        old.mkdir(parents=True)
        (old/'keep.html').write_text('previous snapshot')
        with self.assertRaisesRegex(RuntimeError,"symlink"):
            self.publish(allow=True)
        self.assertEqual((old/'keep.html').read_text(),'previous snapshot')
        self.assertFalse((old/'escape.json').exists())

    def test_reject_invalid_publishing_approvals(self):
        path=self.base/'config/publication_approvals.json'
        path.write_text(json.dumps({'approved_repositories':['../../etc/passwd']}))
        with self.assertRaisesRegex(ValueError,"approved_repositories"):
            with patch.object(publisher,'APPROVALS',path):
                publisher.publishable_repositories()

    def test_preview_unapproved_forbidden_on_ci(self):
        with patch.dict('os.environ',{'CI':'true'}):
            with self.assertRaisesRegex(RuntimeError,"CI or Pages"):
                self.publish(allow=False,preview=True)

    def test_publication_limit_does_not_destroy_previous_snapshot(self):
        old=self.base/'site/games/_repos/example__game'
        old.mkdir(parents=True)
        (old/'keep.html').write_text('old copy')
        with self.assertRaisesRegex(RuntimeError,"Pages artifact"):
            self.publish(allow=True,max_size=5)
        self.assertEqual((old/'keep.html').read_text(),'old copy')

    def test_player_is_not_same_origin_with_untrusted_game(self):
        html=(ROOT/'site/index.html').read_text()
        js=(ROOT/'site/assets/app.js').read_text()
        self.assertIn('sandbox="allow-scripts allow-pointer-lock allow-forms allow-modals"',html)
        self.assertNotIn('allow-same-origin',html)
        self.assertNotIn('cdn.jsdelivr.net',js)


class SeedIdempotenceTests(unittest.TestCase):
    def test_missing_default_seed_does_not_double_existing_records(self):
        from db import connect, seed_database, SEED_PATH
        with tempfile.TemporaryDirectory() as tmp:
            conn=connect(Path(tmp)/'test.sqlite')
            self.assertEqual(seed_database(conn, SEED_PATH),155)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM projects').fetchone()[0],155)
            missing=Path(tmp)/'missing-default.jsonl'
            with patch('db.SEED_PATH',missing):
                self.assertEqual(seed_database(conn,missing),0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM projects').fetchone()[0],155)
            with self.assertRaises(FileNotFoundError):
                seed_database(conn,Path(tmp)/'explicit-missing.jsonl')
            conn.close()

if __name__=='__main__': unittest.main()
