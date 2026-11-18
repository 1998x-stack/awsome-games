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

    def test_failed_repo_refresh_rolls_back_filesystem_and_sqlite(self):
        from db import connect, now
        (self.repo/'index.html').write_text('<!doctype html><title>new</title>')
        self.track()
        original=self.base/'snapshot/example__game'
        original.mkdir(parents=True)
        (original/'keep.html').write_text('<title>previous snapshot</title>')
        conn=connect(self.base/'catalog.sqlite')
        conn.execute("""INSERT INTO projects(id,slug,title,created_at,updated_at)
                        VALUES('project-test','project-test','Sample',?,?)""",(now(),now()))
        conn.execute("""INSERT INTO repositories(full_name,owner,name,html_url,clone_url,
                          clone_status,clone_path,commit_sha)
                        VALUES('example/game','example','game','https://github.com/example/game',
                               'https://github.com/example/game.git','cloned',?,'old-sha')""",
                     (str(original),))
        rid=conn.execute("SELECT id FROM repositories WHERE full_name='example/game'").fetchone()[0]
        conn.execute("INSERT INTO project_repositories(project_id,repository_id) VALUES('project-test',?)",(rid,))
        conn.execute("""INSERT INTO repository_files(repository_id,relative_path,extension,sha256)
                        VALUES(?,'keep.html','.html','original-hash')""",(rid,))
        conn.commit()
        row=conn.execute("SELECT * FROM repositories WHERE id=?",(rid,)).fetchone()
        with patch.object(collector,'DEST',self.base/'snapshot'),patch.object(collector,'clone_one',return_value=(self.repo,'new-sha','main')),patch.object(collector,'choose_entry',side_effect=RuntimeError('simulated post-copy DB failure')):
            result=collector.process_repo(conn,None,row,None,False,True,10_000,100_000)
        self.assertEqual(result["status"],"error")
        self.assertEqual((original/'keep.html').read_text(),'<title>previous snapshot</title>')
        self.assertFalse((original/'index.html').exists())
        status=conn.execute("SELECT clone_status,commit_sha,error_message FROM repositories WHERE id=?",(rid,)).fetchone()
        self.assertEqual(status["clone_status"],"cloned")
        self.assertEqual(status["commit_sha"],"old-sha")
        self.assertIn("refresh_failed_preserved",status["error_message"])
        paths=[r[0] for r in conn.execute("SELECT relative_path FROM repository_files WHERE repository_id=?",(rid,))]
        self.assertEqual(paths,["keep.html"])
        conn.close()

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

    def test_metadata_write_failure_recovers_old_games_and_catalog(self):
        site=self.base/'site'
        previous=site/'games/_repos/example__game'
        previous.mkdir(parents=True)
        (previous/'keep.html').write_text('previous-version')
        (site/'data').mkdir(exist_ok=True)
        (site/'data/catalog.json').write_text('{"original":true}')
        actual_replace=publisher.os.replace
        triggered=[]
        def break_once(source,target):
            if str(target).endswith('data/summary.json') and not triggered:
                triggered.append(True)
                raise OSError('simulated metadata write failure')
            return actual_replace(source,target)
        with patch.object(publisher.os,'replace',side_effect=break_once):
            with self.assertRaisesRegex(OSError,'simulated metadata'):
                self.publish(allow=True)
        self.assertTrue(triggered)
        self.assertEqual((previous/'keep.html').read_text(),'previous-version')
        self.assertFalse((previous/'index.html').exists())
        self.assertEqual((site/'data/catalog.json').read_text(),'{"original":true}')

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

class FreshRecreateSafetyTests(unittest.TestCase):
    """`--fresh` must never destroy the authoritative SQLite without a verified copy."""

    def test_backup_is_verified_and_restorable(self):
        import sqlite3
        import build_catalog
        from db import connect
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'catalog.sqlite'
            conn=connect(path)
            conn.execute("INSERT INTO projects(id,slug,title,created_at,updated_at) "
                         "VALUES('p','p','Sample','2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00')")
            conn.commit(); conn.close()
            backup=build_catalog.backup_database(path)
            self.assertTrue(backup.is_file())
            self.assertEqual(backup.parent.name,'backups')
            restored=sqlite3.connect(backup)
            try:
                self.assertEqual(restored.execute('SELECT COUNT(*) FROM projects').fetchone()[0],1)
                self.assertEqual(restored.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            finally:
                restored.close()
            self.assertIsNone(build_catalog.backup_database(Path(tmp)/'absent.sqlite'))

    def test_recreate_backs_up_before_unlinking(self):
        """Ordering guard: the deletion must come after the backup call."""
        import build_catalog
        source=Path(build_catalog.__file__).read_text(encoding='utf-8')
        backup_at=source.index('backup = backup_database(DB_PATH)')
        unlink_at=source.index('DB_PATH.unlink()')
        self.assertLess(backup_at,unlink_at)
        self.assertIn('refusing to recreate',source)


class SeedReproducibilityTests(unittest.TestCase):
    """Idempotent import must not rewrite timestamps or burn autoincrement rowids."""

    def _seed(self, conn, stamp):
        import db
        with patch.object(db, 'now', return_value=stamp):
            return db.seed_database(conn, db.SEED_PATH)

    def test_reimport_does_not_churn_sequences_or_timestamps(self):
        import db
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / 'repro.sqlite')
            self.assertEqual(self._seed(conn, '2026-01-01T00:00:00+00:00'), 155)
            def snapshot():
                return (
                    dict(conn.execute('SELECT name, seq FROM sqlite_sequence')),
                    {r[0] for r in conn.execute('SELECT updated_at FROM projects')},
                    {t: conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
                     for t in ('projects', 'repositories', 'links', 'prompts', 'evidence_sources')},
                )
            before = snapshot()
            self.assertEqual(before[1], {'2026-01-01T00:00:00+00:00'})
            self.assertEqual(self._seed(conn, '2026-02-02T00:00:00+00:00'), 155)
            self.assertEqual(snapshot(), before,
                             're-import changed timestamps, rowid sequences or row counts')
            conn.close()

    def test_guarded_inserts_still_create_missing_rows(self):
        """The WHERE NOT EXISTS guards must still insert genuinely new rows."""
        import db
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / 'restore.sqlite')
            self._seed(conn, '2026-01-01T00:00:00+00:00')
            conn.execute('DELETE FROM links WHERE link_type=\'demo\'')
            conn.execute('DELETE FROM evidence_sources WHERE url IN (SELECT url FROM evidence_sources LIMIT 5)')
            conn.execute('DELETE FROM repositories')
            conn.commit()
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM repositories').fetchone()[0], 0)
            self.assertEqual(self._seed(conn, '2026-01-01T00:00:00+00:00'), 155)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM repositories').fetchone()[0], 54)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM links WHERE link_type='demo'").fetchone()[0], 59)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM evidence_sources').fetchone()[0], 81)
            # Every project-repository mapping must be resolvable again.
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM project_repositories').fetchone()[0], 150)
            conn.close()


if __name__=='__main__': unittest.main()


class AttributionPublicationTests(unittest.TestCase):
    """MIT/BSD/Apache notices must travel with approved code, nothing else may sneak in."""

    def _publish(self, extra):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); src=base/'snap/example__game'; src.mkdir(parents=True)
            (src/'index.html').write_text('<!doctype html><title>game</title>')
            for name,body in extra.items():
                target=src/name; target.parent.mkdir(parents=True,exist_ok=True)
                target.write_text(body)
            dest=base/'out'; dest.mkdir()
            publisher.copy_approved_assets(src,dest,10_000_000)
            return sorted(p.relative_to(dest).as_posix() for p in dest.rglob('*') if p.is_file())

    def test_licence_and_notice_files_are_published(self):
        files=self._publish({'LICENSE':'MIT License\nCopyright (c) 2026 TimeDev',
                             'NOTICE':'notice','THIRD_PARTY_NOTICES.md':'third party'})
        self.assertIn('LICENSE',files)
        self.assertIn('NOTICE',files)
        self.assertIn('THIRD_PARTY_NOTICES.md',files)
        self.assertIn('index.html',files)

    def test_attribution_allowlist_is_not_a_general_bypass(self):
        files=self._publish({'Makefile':'all:','run.sh':'echo hi','LICENSE-UNKNOWN-JUNK':'x',
                             '.env':'SECRET=1','credentials.json':'{"token":"x"}','bin/game':'ELF'})
        for leaked in ('Makefile','run.sh','LICENSE-UNKNOWN-JUNK','.env','credentials.json','bin/game'):
            self.assertNotIn(leaked,files,leaked)


class RuntimeReviewedStatusTests(unittest.TestCase):
    """A status measured by isolated runtime testing must survive re-collection."""

    def test_runtime_reviewed_status_is_not_overwritten_by_recollection(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            (base/'site').mkdir()
            (base/'games/_repos/example__game').mkdir(parents=True)
            (base/'games/_repos/example__game/index.html').write_text('<!doctype html><title>g</title>')
            (base/'config').mkdir()
            (base/'config/publication_approvals.json').write_text(json.dumps({'approved_repositories':[]}))
            from db import connect, now
            conn=connect(base/'catalog.sqlite')
            conn.execute("INSERT INTO projects(id,slug,title,created_at,updated_at) VALUES('p','p','Sample',?,?)",(now(),now()))
            conn.execute("""INSERT INTO repositories(full_name,owner,name,html_url,clone_url,clone_status,clone_path,commit_sha)
                            VALUES('example/game','example','game','https://github.com/example/game',
                                   'https://github.com/example/game.git','cloned',?,'old')""",(str(base/'snap'),))
            rid=conn.execute("SELECT id FROM repositories WHERE full_name='example/game'").fetchone()[0]
            conn.execute("""INSERT INTO project_repositories(project_id,repository_id,entry_path,game_path,
                              entry_confidence,playable_status,note) VALUES('p',?,'index.html',
                              'games/_repos/example__game/index.html','unique_html','sandbox_incompatible',
                              'localStorage threw: sandbox lacks allow-same-origin')""",(rid,))
            conn.commit()
            repo=base/'snap'; repo.mkdir()
            (repo/'index.html').write_text('<!doctype html><title>g</title>')
            row=conn.execute("SELECT * FROM repositories WHERE id=?",(rid,)).fetchone()
            with patch.object(collector,'ROOT',base), \
                 patch.object(collector,'DEST',base/'games/_repos'), \
                 patch.object(collector,'clone_one',return_value=(repo,'new-sha','main')), \
                 patch.object(collector,'tracked_files',return_value=['index.html']), \
                 patch.object(collector,'api_metadata',return_value={}):
                result=collector.process_repo(conn,None,row,None,False,True,10_000,100_000)
            self.assertEqual(result['status'],'cloned')
            kept=conn.execute("SELECT playable_status,note FROM project_repositories WHERE project_id='p' AND repository_id=?",(rid,)).fetchone()
            self.assertEqual(kept['playable_status'],'sandbox_incompatible')
            self.assertIn('allow-same-origin',kept['note'])
            agg=conn.execute("SELECT playable_status FROM projects WHERE id='p'").fetchone()[0]
            self.assertEqual(agg,'sandbox_incompatible')
            conn.close()


class EntrypointAssetTests(unittest.TestCase):
    """A missing favicon is not a missing game asset; a missing script is."""

    def _entry(self, tmp, body, extra=()):
        d=Path(tmp)/'repo'; d.mkdir()
        (d/'index.html').write_text(body)
        for name in extra: (d/name).write_text('x')
        return d

    def test_cosmetic_references_are_not_reported_as_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=self._entry(tmp, '<link rel="icon" href="./favicon.svg">'
                               '<link rel="apple-touch-icon" href="apple-touch-icon.png">'
                               '<link rel="mask-icon" href="safari-pinned-tab.svg">'
                               '<link rel="manifest" href="site.webmanifest">'
                               '<link rel="stylesheet" href="style.css">'
                               '<script src="engine.js"></script>'
                               '<img src="sprite.png">', extra=('style.css',))
            self.assertEqual(collector.missing_static_assets(d,'index.html'),['engine.js','sprite.png'])

    def test_font_and_icon_files_are_cosmetic_but_css_is_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=self._entry(tmp, '<link href="theme.woff2" rel="preload">'
                               '<link href="tile.ico" rel="icon">'
                               '<link href="game.css" rel="stylesheet">')
            missing=collector.missing_static_assets(d,'index.html')
            self.assertEqual(missing,['game.css'])

    def test_favicon_named_svg_is_cosmetic_without_a_rel(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=self._entry(tmp, '<img src="favicon-32.png">')
            self.assertEqual(collector.missing_static_assets(d,'index.html'),[])

    def test_same_origin_absolute_and_remote_refs_still_flagged_correctly(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=self._entry(tmp, '<script src="/src/main.tsx"></script>'
                               '<script src="https://cdn.example.com/three.js"></script>')
            self.assertEqual(collector.missing_static_assets(d,'index.html'),['root-relative:/src/main.tsx'])


class DeclaredReviewedStatusTests(unittest.TestCase):
    """A settled fact about a work's kind must survive re-collection, and an editor
    entry_path override is what decides the entrypoint in a collection repository."""

    def _fixture(self, base, files, status='needs_review', note='', entry_path=''):
        (base/'site').mkdir()
        repo_dir=base/'games/_repos'/'example__game'
        for rel,body in files.items():
            for target in (base/'snap'/rel, repo_dir/rel):
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_text(body)
        (base/'config').mkdir()
        (base/'config/publication_approvals.json').write_text(json.dumps({'approved_repositories':[]}))
        from db import connect, now
        conn=connect(base/'catalog.sqlite')
        conn.execute("INSERT INTO projects(id,slug,title,created_at,updated_at) VALUES('p','p','Sample',?,?)",(now(),now()))
        conn.execute("""INSERT INTO repositories(full_name,owner,name,html_url,clone_url,clone_status,clone_path,commit_sha)
                        VALUES('example/game','example','game','https://github.com/example/game',
                               'https://github.com/example/game.git','cloned',?,'old')""",(str(base/'snap'),))
        rid=conn.execute("SELECT id FROM repositories WHERE full_name='example/game'").fetchone()[0]
        conn.execute("""INSERT INTO project_repositories(project_id,repository_id,entry_path,game_path,
                          entry_confidence,playable_status,note) VALUES('p',?,?,?,'',?,?)""",
                     (rid,entry_path,'',status,note))
        conn.commit()
        return conn,rid,sorted(files)

    def _recollect(self, base, conn, rid, overrides, tracked):
        row=conn.execute("SELECT * FROM repositories WHERE id=?",(rid,)).fetchone()
        with patch.object(collector,'ROOT',base), \
             patch.object(collector,'DEST',base/'games/_repos'), \
             patch.object(collector,'OVERRIDES',overrides), \
             patch.object(collector,'clone_one',return_value=(base/'snap','new-sha','main')), \
             patch.object(collector,'tracked_files',return_value=list(tracked)), \
             patch.object(collector,'api_metadata',return_value={}):
            return collector.process_repo(conn,None,row,None,False,True,10_000,100_000)

    def _row(self, conn, rid, columns):
        return conn.execute(f"SELECT {columns} FROM project_repositories WHERE project_id='p' AND repository_id=?",(rid,)).fetchone()

    def test_declared_not_browser_based_survives_recollection(self):
        # A native (non-HTML) repository must not silently fall back to needs_review:
        # there is no HTML to score, so without the declaration it would look unresolved.
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            note='Rust binary: no browser artifact'
            conn,rid,tracked=self._fixture(base,{'Cargo.toml':'[package]\nname="g"','src/main.rs':'fn main(){}'},
                                           status='not_browser_based',note=note)
            overrides={'p':{'playable_status':'not_browser_based','note':note}}
            self.assertEqual(self._recollect(base,conn,rid,overrides,tracked)['status'],'cloned')
            row=self._row(conn,rid,'playable_status,note,entry_path')
            self.assertEqual(row['playable_status'],'not_browser_based')
            self.assertIn('no browser artifact',row['note'])
            self.assertEqual(row['entry_path'],'', 'a non-browser work must not claim an entrypoint')
            self.assertEqual(conn.execute("SELECT playable_status FROM projects WHERE id='p'").fetchone()[0],'not_browser_based')
            conn.close()

    def test_declared_status_is_ignored_when_the_work_has_no_such_override(self):
        # Without a declaration the same repository must stay unresolved, proving the
        # previous test passes because of the override and not because of the fixture.
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            conn,rid,tracked=self._fixture(base,{'Cargo.toml':'[package]\nname="g"'},status='not_browser_based')
            self._recollect(base,conn,rid,{},tracked)
            self.assertEqual(self._row(conn,rid,'playable_status')['playable_status'],'needs_review')
            conn.close()

    def test_override_cannot_assert_a_runtime_result(self):
        # An override must not be able to claim an outcome nobody measured.
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            conn,rid,tracked=self._fixture(base,{'index.html':'<!doctype html><title>g</title>'})
            overrides={'p':{'playable_status':'entrypoint_found','note':'forged'}}
            self._recollect(base,conn,rid,overrides,tracked)
            row=self._row(conn,rid,'playable_status,entry_confidence')
            self.assertEqual(row['entry_confidence'],'unique_html', 'the status must come from a real file, not the override')
            self.assertEqual(row['playable_status'],'entrypoint_found')
            conn.close()

    def test_reclassify_applies_overrides_offline_from_recorded_files(self):
        # An auditable correction must not need the network or a re-clone.
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            files={'index.html':'<!doctype html><title>menu</title>',
                   'game5/index.html':'<!doctype html><title>game5</title>'}
            conn,rid,tracked=self._fixture(base,files)
            for rel in tracked:
                conn.execute("""INSERT INTO repository_files(repository_id,relative_path,extension,mime_type,
                                  size_bytes,sha256,is_html_entry,copied)
                                VALUES(?,?,?,?,100,'deadbeef',1,1)""",(rid,rel,'.html','text/html'))
            conn.commit()
            row=conn.execute("SELECT * FROM repositories WHERE id=?",(rid,)).fetchone()
            with patch.object(collector,'ROOT',base), patch.object(collector,'OVERRIDES',{'p':{'entry_path':'game5/index.html'}}), \
                 patch.object(collector,'clone_one',side_effect=AssertionError('reclassify must not clone')):
                result=collector.reclassify_repo(conn,row)
            self.assertEqual(result['status'],'reclassified')
            self.assertEqual(self._row(conn,rid,'entry_path')['entry_path'],'game5/index.html')
            conn.close()

    def test_reclassify_skips_a_missing_snapshot_instead_of_inventing_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            conn,rid,tracked=self._fixture(base,{'index.html':'<!doctype html><title>g</title>'})
            row=dict(conn.execute("SELECT * FROM repositories WHERE id=?",(rid,)).fetchone())
            row['clone_path']='games/_repos/does-not-exist'
            with patch.object(collector,'ROOT',base):
                self.assertEqual(collector.reclassify_repo(conn,row)['status'],'skipped')
            conn.close()

    def test_entry_path_override_picks_the_named_work_in_a_collection(self):
        # A repository holding several games cannot be resolved by scoring alone.
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            files={'index.html':'<!doctype html><title>menu</title>'}
            for n in (3,5):
                files[f'game{n}/index.html']=f'<!doctype html><title>game{n}</title>'
            conn,rid,tracked=self._fixture(base,files)
            self._recollect(base,conn,rid,{'p':{'entry_path':'game5/index.html'}},tracked)
            row=self._row(conn,rid,'entry_path,game_path,entry_confidence,playable_status')
            self.assertEqual(row['entry_path'],'game5/index.html')
            self.assertEqual(row['entry_confidence'],'explicit_override')
            self.assertEqual(row['playable_status'],'entrypoint_found')
            self.assertTrue(row['game_path'].endswith('game5/index.html'))
            conn.close()


class VendoredEntryConsistencyTests(unittest.TestCase):
    """A committed catalog must not claim entrypoints the checkout cannot serve."""

    def test_check_catalog_only_requires_files_it_can_see(self):
        source=(ROOT/'scripts/check_catalog.py').read_text(encoding='utf-8')
        self.assertIn("playable_status='entrypoint_found'",source)
        self.assertNotIn('entrypoint_detected_not_vendored',source)

    def test_marker_uses_git_to_decide_instead_of_a_hardcoded_list(self):
        source=(ROOT/'scripts/mark_unvendored_entries.py').read_text(encoding='utf-8')
        self.assertIn('git',source)
        self.assertIn('check-ignore',source)
        self.assertIn('entrypoint_detected_not_vendored',source)
        self.assertIn('--apply',source)

    def test_gitignore_tracks_only_approved_artifacts(self):
        ignores=(ROOT/'.gitignore').read_text(encoding='utf-8')
        self.assertIn('games/_repos/*',ignores)
        self.assertIn('!games/_repos/Time-dev-alt__Fable-5.1-Games/Soccer.html',ignores)


class SurveyApplicationTests(unittest.TestCase):
    """A measurement may reach the catalog only as a restrictive, evidenced status.

    Before this existed the runtime statuses in the database had no writer at all, so
    they could not be reproduced or traced back to a measurement.
    """

    def _conn(self, base, status='entrypoint_detected_not_vendored'):
        (base/'config').mkdir(parents=True, exist_ok=True)
        (base/'config/publication_approvals.json').write_text('{"approved_repositories": []}')
        from db import connect, now
        conn = connect(base/'catalog.sqlite')
        conn.execute("INSERT INTO projects(id,slug,title,created_at,updated_at) VALUES('p','p','Sample',?,?)", (now(), now()))
        conn.execute("""INSERT INTO repositories(full_name,owner,name,html_url,clone_url,clone_status,clone_path,commit_sha)
                        VALUES('example/game','example','game','https://github.com/example/game',
                               'https://github.com/example/game.git','cloned','games/_repos/example__game','deadbeef')""")
        rid = conn.execute("SELECT id FROM repositories").fetchone()[0]
        conn.execute("""INSERT INTO project_repositories(project_id,repository_id,entry_path,game_path,
                          entry_confidence,playable_status,note) VALUES('p',?,?,?,'',?,?)""",
                     (rid, 'index.html', 'games/_repos/example__game/index.html', status, ''))
        conn.commit()
        return conn, rid

    def _survey(self, failure_class, fingerprints=True):
        return {'captured_at': '2026-11-18T00:00:00+00:00',
                'isolation': {'network_policy': 'off-loopback HTTP aborted'},
                'entries': [{'key': 'k', 'entry': '_repos/example__game/index.html',
                             'mode': 'gameplay', 'failure_class': failure_class,
                             'fingerprints': ({'initial_pixels': 'x'} if fingerprints else None)}]}

    def _status(self, conn, rid):
        return conn.execute("SELECT playable_status FROM project_repositories WHERE repository_id=?",
                            (rid,)).fetchone()[0]

    def test_a_conclusion_is_written_and_the_project_aggregate_follows(self):
        import sys
        sys.path.insert(0, str(ROOT/'scripts'))
        import apply_survey_to_catalog as applier
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            conn, rid = self._conn(base)
            planned, _, _, _ = applier.plan(conn, self._survey('SANDBOX_OPAQUE_ORIGIN_BREAKS_OWN_SCRIPT'),
                                           'survey.json', 'a'*64)
            self.assertEqual(len(planned), 1)
            applier.apply_plan(conn, planned)
            self.assertEqual(self._status(conn, rid), 'sandbox_incompatible')
            note = conn.execute("SELECT note FROM project_repositories WHERE repository_id=?", (rid,)).fetchone()[0]
            self.assertIn('sha256', note)
            self.assertEqual(conn.execute("SELECT playable_status FROM projects WHERE id='p'").fetchone()[0],
                             'sandbox_incompatible')
            conn.close()

    def test_a_new_finding_may_not_weaken_an_existing_harder_one(self):
        import sys
        sys.path.insert(0, str(ROOT/'scripts'))
        import apply_survey_to_catalog as applier
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            conn, rid = self._conn(base, status='sandbox_incompatible')
            planned, _, weaker, _ = applier.plan(conn, self._survey('NO_OBSERVABLE_RESPONSE'),
                                                'survey.json', 'b'*64)
            self.assertEqual(planned, [])
            self.assertEqual(len(weaker), 1)
            self.assertEqual(self._status(conn, rid), 'sandbox_incompatible')
            conn.close()

    def test_nothing_here_can_make_an_artifact_publishable(self):
        import sys
        sys.path.insert(0, str(ROOT/'scripts'))
        import apply_survey_to_catalog as applier
        for cls in ('PASS', 'OTHER', 'DRIVER_FLAKE_OR_TIMEOUT', 'INPUT_RESPONSIVE'):
            self.assertNotIn(cls, applier.CLASS_TO_STATUS, cls)
            self.assertNotIn('entrypoint_found', applier.CLASS_TO_STATUS.values(), cls)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            conn, rid = self._conn(base)
            planned, _, _, _ = applier.plan(conn, self._survey('PASS'), 'survey.json', 'c'*64)
            self.assertEqual(planned, [])
            self.assertEqual(self._status(conn, rid), 'entrypoint_detected_not_vendored')
            conn.close()

    def test_trustworthy_requires_timestamp_isolation_and_evidence_for_each_claim(self):
        import sys
        sys.path.insert(0, str(ROOT/'scripts'))
        import apply_survey_to_catalog as applier
        self.assertTrue(applier.survey_is_trustworthy(self._survey('NO_OBSERVABLE_RESPONSE'))[0])
        no_stamp = self._survey('NO_OBSERVABLE_RESPONSE'); no_stamp['captured_at'] = ''
        self.assertFalse(applier.survey_is_trustworthy(no_stamp)[0])
        no_iso = self._survey('NO_OBSERVABLE_RESPONSE'); no_iso['isolation'] = {}
        self.assertFalse(applier.survey_is_trustworthy(no_iso)[0])
        no_evidence = self._survey('NO_OBSERVABLE_RESPONSE', fingerprints=False)
        self.assertFalse(applier.survey_is_trustworthy(no_evidence)[0])
        # An entry that failed before it could be measured claims nothing, so its
        # missing fingerprints must not block the findings that do have evidence.
        mixed = self._survey('NO_OBSERVABLE_RESPONSE')
        mixed['entries'].append({'key': 'unmeasured', 'entry': '_repos/example__game/broken.html',
                                 'mode': 'load', 'failure_class': 'DRIVER_FLAKE_OR_TIMEOUT',
                                 'fingerprints': None})
        self.assertTrue(applier.survey_is_trustworthy(mixed)[0])

    def test_an_evidenced_pass_retracts_a_previous_restrictive_finding(self):
        # A stale restrictive status must be correctable, or the catalog accumulates
        # claims that later, equally evidenced measurement has refuted.
        import sys
        sys.path.insert(0, str(ROOT/'scripts'))
        import apply_survey_to_catalog as applier
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            conn, rid = self._conn(base, status='sandbox_incompatible')
            survey = self._survey('PASS')
            survey['entries'][0]['status'] = 'BROWSER_LOAD_CHECKED'
            survey['entries'][0]['iframe_isolation'] = True
            planned, unchanged, weaker, _ = applier.plan(conn, survey, 'survey.json', 'd'*64)
            self.assertEqual(len(planned), 1)
            self.assertTrue(planned[0]['retraction'])
            self.assertEqual(planned[0]['status'], 'runtime_needs_retest')
            applier.apply_plan(conn, planned)
            self.assertEqual(self._status(conn, rid), 'runtime_needs_retest')
            note = conn.execute("SELECT note FROM project_repositories WHERE repository_id=?", (rid,)).fetchone()[0]
            self.assertIn('retracts', note)
            conn.close()

    def test_a_pass_without_confirmed_isolation_cannot_retract_anything(self):
        import sys
        sys.path.insert(0, str(ROOT/'scripts'))
        import apply_survey_to_catalog as applier
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            conn, rid = self._conn(base, status='sandbox_incompatible')
            survey = self._survey('PASS')
            survey['entries'][0]['status'] = 'BROWSER_LOAD_CHECKED'
            survey['entries'][0]['iframe_isolation'] = False
            planned, _, weaker, _ = applier.plan(conn, survey, 'survey.json', 'e'*64)
            self.assertEqual(planned, [])
            self.assertEqual(len(weaker), 1)
            self.assertEqual(self._status(conn, rid), 'sandbox_incompatible')
            conn.close()

    def test_a_blocked_driver_may_claim_without_fingerprints_but_must_record_why(self):
        import sys
        sys.path.insert(0, str(ROOT/'scripts'))
        import apply_survey_to_catalog as applier
        blocked = self._survey('PAGE_BLOCKED_DRIVER', fingerprints=False)
        blocked['entries'][0]['status'] = 'TIMEOUT_ABORTED'
        blocked['entries'][0]['console_errors'] = []
        self.assertFalse(applier.survey_is_trustworthy(blocked)[0])
        blocked['entries'][0]['console_errors'] = ["hard timeout after 60s; the page blocked the driver "
                                                   "and the process group was killed"]
        self.assertTrue(applier.survey_is_trustworthy(blocked)[0])

    def test_a_hand_written_survey_cannot_move_the_catalog(self):
        import sys
        sys.path.insert(0, str(ROOT/'scripts'))
        import apply_survey_to_catalog as applier
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'forged.json'
            path.write_text(json.dumps({'entries': [{'key': 'k',
                'entry': '_repos/example__game/index.html', 'failure_class': 'NO_OBSERVABLE_RESPONSE'}]}))
            with self.assertRaises(SystemExit):
                import subprocess
                proc = subprocess.run([sys.executable, str(ROOT/'scripts/apply_survey_to_catalog.py'),
                                       '--survey', str(path), '--apply'], capture_output=True, text=True)
                if proc.returncode:
                    raise SystemExit(proc.stderr)
