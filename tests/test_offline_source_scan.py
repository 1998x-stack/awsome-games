"""Only read immutable Git objects, never execute tracked source or follow symlinks."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from audit_local_source_tree import scan_git_repository


class OfflineSourceScannerTests(unittest.TestCase):
    def test_fixture_git_tree_scanned_without_executing_source(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            def git(*args):
                p=subprocess.run(["git","-C",str(root),*args],check=True,
                                 text=True,capture_output=True)
                return p.stdout.strip()
            git("init","-q")
            git("config","user.email","fixture@example.invalid")
            git("config","user.name","Fixture")
            (root/"index.html").write_text('<script>fetch("https://example.org/data")</script>',encoding="utf-8")
            (root/"package.json").write_text('{"scripts":{"build":"node build.js"},'
                                            '"dependencies":{"three":"0.170.0"}}',encoding="utf-8")
            (root/"unused.py").write_text('raise Exception("DO NOT EXECUTE")',encoding="utf-8")
            (root/"secret.pem").write_text('PRIVATE_KEY_SHOULD_NOT_BE_SCANNED',encoding="utf-8")
            (root/"sprite.png").write_bytes(b"PNG fixture")
            (root/"external.html").symlink_to(root/"index.html")
            git("add","-A")
            git("commit","-qm","fixture")
            sha=git("rev-parse","HEAD")
            result=scan_git_repository(root,"fixture/original",sha)
            self.assertEqual(result["pinned_commit_sha"],sha)
            self.assertEqual(result["files_total"],6)
            bypath={x["path"]:x for x in result["files"]}
            self.assertEqual(bypath["external.html"]["status"],"SYMLINK_METADATA_ONLY")
            self.assertEqual(bypath["secret.pem"]["status"],"SENSITIVE_METADATA_ONLY")
            self.assertEqual(bypath["sprite.png"]["status"],"BINARY_OR_UNKNOWN_METADATA_ONLY")
            self.assertEqual(bypath["unused.py"]["status"],"TEXT_STATIC_SCAN")
            self.assertEqual(bypath["index.html"]["indicators"]["fetch_call"],1)
            self.assertIn("example.org",result["potential_external_hosts"])
            self.assertEqual(result["package_manifests"][0]["dependencies"],["three"])
            self.assertEqual(result["package_manifests"][0]["build_scripts"],["build"])
            self.assertEqual(result["audit_status"],"ALL_TEXT_FILES_SCANNED")
            with self.assertRaisesRegex(ValueError,"Local HEAD"):
                scan_git_repository(root,"fixture/original","a"*40)
            with self.assertRaisesRegex(ValueError,"Invalid repository"):
                scan_git_repository(root,"../../escape",sha)


if __name__=="__main__":
    unittest.main()
