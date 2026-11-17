#!/usr/bin/env bash
# Conservative metadata refresh only. Never bulk-clone/execute community code.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ $# -gt 0 && "$1" == "--dry-run" ]]; then
  python3 scripts/refresh_research.py --dry-run
  exit 0
fi
if [[ $# -gt 0 && "$1" != "--write" ]]; then
  echo "Usage: bash scripts/refresh_all.sh [--dry-run|--write]" >&2
  exit 2
fi
python3 scripts/refresh_research.py --write
python3 scripts/build_catalog.py --check
python3 scripts/check_catalog.py
python3 scripts/build_site.py
python3 -m unittest discover -s tests -v
node --check site/assets/app.js
node --check site/assets/research.js
printf '\nMetadata refresh complete. Review the versioned JSON diff before committing.\n'
