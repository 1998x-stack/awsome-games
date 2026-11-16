#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m pip install -r requirements.txt
python3 scripts/build_catalog.py
python3 scripts/build_site.py
python3 scripts/check_catalog.py
printf '\nBootstrap complete. Run scripts/collect_repositories.py to fetch game source files.\n'
