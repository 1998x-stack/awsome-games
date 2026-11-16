#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m pip install -r requirements.txt
python3 scripts/build_catalog.py
python3 scripts/collect_repositories.py "$@"
python3 scripts/build_catalog.py
python3 scripts/build_site.py
python3 scripts/check_catalog.py
printf '\nDone. Local site: site/index.html\nRun: python3 -m http.server 8000 --directory site\n'
