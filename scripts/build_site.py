#!/usr/bin/env python3
"""Permission-gated, size-bounded static Pages publisher.

Only a reviewed/explicitly approved repository can supply executable assets.
Never execute third-party code, follow symlinks or copy secrets. Stage before
replacing an existing published snapshot so exceptions preserve the prior build.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from db import ROOT, connect
from build_catalog import export_catalog
from research_pipeline import ingest as ingest_research, export_projection
from review_queue import build_queue

APPROVALS = ROOT / "config" / "publication_approvals.json"
REPO_PATTERN = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9_.-]+$")
ALLOWED_ASSETS = {
    ".html", ".htm", ".js", ".mjs", ".css", ".json",
    ".wasm", ".glb", ".gltf", ".obj", ".mtl", ".bin",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".ico",
    ".mp3", ".wav", ".ogg", ".aac", ".mp4", ".webm",
    ".woff", ".woff2", ".ttf", ".otf", ".atlas", ".vert", ".frag",
}
SENSITIVE_NAMES = {".env", ".npmrc", ".pypirc", "credentials.json",
                   "service-account.json", "id_rsa", "id_ed25519"}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
EXCLUDED_DIRS = {".git", ".cache", "node_modules", ".next", ".venv",
                 "venv", "__pycache__", "test-results"}


def publishable_repositories(config_path=None):
    config_path = config_path or APPROVALS
    data = json.loads(config_path.read_text(encoding="utf-8"))
    entries = data.get("approved_repositories", [])
    if not isinstance(entries, list) or any(
        not isinstance(e, str) or not REPO_PATTERN.fullmatch(e) for e in entries
    ):
        raise ValueError("approved_repositories must contain safe GitHub owner/repo names")
    if len(entries) != len(set(e.casefold() for e in entries)):
        raise ValueError("duplicate repository approval")
    return {e.casefold() for e in entries}


def is_sensitive(path: Path) -> bool:
    parts = path.parts
    if any(p.casefold() in EXCLUDED_DIRS for p in parts):
        return True
    if any(p.casefold().startswith(".env") for p in parts):
        return True
    low = path.name.casefold()
    return low in SENSITIVE_NAMES or path.suffix.casefold() in SENSITIVE_SUFFIXES


def copy_approved_assets(source: Path, target: Path, max_bytes: int) -> int:
    """Copy only reviewed static asset types, strictly inside one source tree."""
    if not source.is_dir() or source.is_symlink():
        raise RuntimeError("Missing or unsafe repository snapshot: " + str(source))
    root = source.resolve()
    size = 0
    for item in sorted(source.rglob("*")):
        rel = item.relative_to(source)
        if item.is_symlink() or not item.resolve().is_relative_to(root):
            raise RuntimeError("unsafe symlink or path escape: " + str(rel))
        if is_sensitive(rel):
            # Do not copy secrets even when the upstream repository was approved.
            continue
        if item.is_dir():
            continue
        if not item.is_file():
            raise RuntimeError("nonregular file in snapshot: " + str(rel))
        if item.suffix.casefold() not in ALLOWED_ASSETS:
            continue
        bytes_ = item.stat().st_size
        if bytes_ < 0 or size + bytes_ > max_bytes:
            raise RuntimeError("Pages artifact size limit reached while copying assets")
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Source tree is a local collector snapshot; no install/build is attempted.
        with item.open("rb") as src, destination.open("wb") as dest:
            shutil.copyfileobj(src, dest, length=1024 * 1024)
        size += bytes_
    return size


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(x.stat().st_size for x in path.rglob("*") if x.is_file())


def build_site(include_unapproved=False, max_site_bytes=850*1024*1024):
    if max_site_bytes <= 0:
        raise ValueError("max_site_bytes must be positive")
    if include_unapproved and (os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("CI") == "true"):
        raise RuntimeError("Unapproved preview must never execute in CI or Pages")
    conn = connect()
    try:
        research = None
        review_queue = None
        if isinstance(conn, sqlite3.Connection):
            ingest_research(conn)
            research = export_projection(conn)
            review_queue = build_queue(conn)
        data = export_catalog(conn)
    finally:
        conn.close()

    site = ROOT / "site"
    site.mkdir(parents=True, exist_ok=True)
    approvals = publishable_repositories()
    copied = set()
    published = 0

    # All newly published assets are staged OUTSIDE site/ so partial copies
    # cannot leak into the Pages artifact after a failure.
    stage_root = ROOT / ".cache" / "site-staging"
    stage_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pages-", dir=stage_root) as temporary:
        stage = Path(temporary) / "games"
        stage.mkdir(parents=True)
        for project in data["projects"]:
            project["published_game_path"] = ""
            for mapping in project["repositories"]:
                name = mapping["full_name"]
                if not REPO_PATTERN.fullmatch(name):
                    raise ValueError("unsafe repository name in catalog")
                if not (include_unapproved or name.casefold() in approvals):
                    continue
                if mapping.get("playable_status") not in ("entrypoint_found", "smoke_test_passed"):
                    continue
                rel = mapping.get("game_path") or ""
                path = Path(rel)
                expected_prefix = Path("games") / "_repos" / name.replace("/", "__")
                if not rel or "\\" in rel or path.is_absolute() or ".." in path.parts:
                    continue
                if not path.is_relative_to(expected_prefix) or path.suffix.casefold() not in (".html", ".htm"):
                    continue
                source_base = ROOT / expected_prefix
                source_entry = ROOT / path
                if source_base.is_symlink() or source_entry.is_symlink() or not source_entry.is_file():
                    continue
                if not source_entry.resolve().is_relative_to(source_base.resolve()):
                    continue
                if name not in copied:
                    dest = stage / "_repos" / name.replace("/", "__")
                    remaining = max_site_bytes - _size(stage)
                    copy_approved_assets(source_base, dest, remaining)
                    copied.add(name)
                if (stage / path.relative_to("games")).is_file():
                    project["published_game_path"] = rel
                    published += 1
                    break

        data["summary"]["projects_published_for_play"] = published
        data["summary"]["repositories_published"] = len(copied)
        data["publication_policy"] = "repository_opt_in"

        artifacts = {
            "data/catalog.json": json.dumps(data, ensure_ascii=False, indent=2),
            "data/summary.json": json.dumps(data["summary"], ensure_ascii=False, indent=2),
            "build-manifest.json": json.dumps({
                "generated_at": data["generated_at"],
                "repository_ref": data["repository_ref"],
                "projects": data["summary"]["projects"],
                "repositories": data["summary"]["repositories"],
                "projects_with_entrypoints": data["summary"]["projects_with_html_entrypoints"],
                "playable_published": published,
                "repository_snapshots_published": sorted(copied),
                "preview_unapproved": include_unapproved,
            }, ensure_ascii=False, indent=2),
        }
        if research is not None:
            artifacts["data/research.json"] = json.dumps(research, ensure_ascii=False, separators=(",", ":"))
        if review_queue is not None:
            artifacts["data/review-queue.json"] = json.dumps(review_queue, ensure_ascii=False, separators=(",", ":"))

        # Include existing site template files, but exclude outputs we replace.
        replacing = set(artifacts) | {".nojekyll"}
        static_bytes = sum(
            p.stat().st_size for p in site.rglob("*")
            if p.is_file() and not p.relative_to(site).is_relative_to("games")
            and p.relative_to(site).as_posix() not in replacing
        )
        total = static_bytes + _size(stage) + sum(len(s.encode("utf-8")) for s in artifacts.values())
        if total > max_site_bytes:
            raise RuntimeError(f"Pages artifact is {total:,} bytes; cap is {max_site_bytes:,} bytes")

        # Stage metadata JSONs before touching an existing publication.
        for rel, body in artifacts.items():
            file = Path(temporary) / rel
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(body, encoding="utf-8")

        dest = site / "games"
        backup = Path(temporary) / "previous-games"
        old_metadata = Path(temporary) / "previous-metadata"
        old_metadata.mkdir(parents=True)
        for rel in artifacts:
            current = site / rel
            if current.is_file():
                retained = old_metadata / rel
                retained.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(current, retained)
        original_nojekyll = (site / ".nojekyll").exists()
        replaced=[]
        games_swapped=False
        try:
            if dest.exists():
                dest.rename(backup)
            stage.rename(dest)
            games_swapped=True
            for rel in artifacts:
                target = site / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(Path(temporary) / rel, target)
                replaced.append(rel)
            (site / ".nojekyll").write_text("", encoding="utf-8")
        except BaseException:
            for rel in reversed(replaced):
                target = site / rel
                prior = old_metadata / rel
                if prior.is_file():
                    os.replace(prior, target)
                else:
                    target.unlink(missing_ok=True)
            if games_swapped and dest.exists():
                shutil.rmtree(dest)
            if backup.exists():
                backup.rename(dest)
            if not original_nojekyll:
                (site / ".nojekyll").unlink(missing_ok=True)
            raise

    return {"projects": data["summary"]["projects"],
            "repos": data["summary"]["repositories"],
            "published_games": published,
            "published_repos": len(copied),
            "site_bytes": total}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--preview-unapproved", action="store_true",
                    help="LOCAL ONLY: never deploy this generated artifact publicly")
    ap.add_argument("--max-site-mb", type=int, default=850)
    args = ap.parse_args()
    if args.max_site_mb < 1:
        ap.error("--max-site-mb must be >=1")
    print(json.dumps(build_site(args.preview_unapproved, args.max_site_mb*1024*1024),ensure_ascii=False))


if __name__ == "__main__":
    main()
