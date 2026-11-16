#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/refresh_community_indexes.py --online
python3 scripts/build_catalog.py --seed data/projects.jsonl
python3 scripts/collect_repositories.py "$@"
python3 scripts/build_catalog.py
python3 scripts/build_site.py
python3 scripts/check_catalog.py
