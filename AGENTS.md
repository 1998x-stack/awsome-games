# Development rules for awsome-games

- **Read-only third-party code collection**: never execute cloned code or install its dependencies in the host environment.
- **No forced commits/pushes of external game snapshots**: first review SPDX metadata and asset redistribution rights.
- **Separate evidence and status**: a source candidate is not an original author repository, and an HTML file is not verified playable.
- **Preserve the database**: SQLite is authoritative; generated JSON/CSV and Pages are derived projections.
- **Preserve previous snapshots** on I/O failures; add a regression test for any collector fix.
- **Sandbox untrusted HTML**: do not grant both `allow-scripts` and `allow-same-origin` to same-origin content.
- **Never use jsDelivr to host executable HTML**: it returns `text/plain`.
- **Run** `python3 -m unittest discover -s tests -v`, `python3 scripts/build_catalog.py --check`, `python3 scripts/check_catalog.py`, `python3 scripts/build_site.py`, `node --check site/assets/app.js` before finalizing.
- **Report candidly**: distinguish source commit status, local build/test results, network clone results, Pages deployment, and actual gameplay verification.

- **Evidence refresh uses atomically versioned pairs**: Never load current sources and entities from separate revisions. Validate the active hash pointer.
- **Editorial review is separate**: Only approved, cited entries from config/research_reviews.json may override community-source fields; keep review history.
- **Fail closed on publication**: Refuse symlinks/secret files, avoid copying external games without approval; retain prior artifact on I/O failure.
- **Browser security**: Block HTTP and WebSocket in Playwright, but require OS/network isolation for untrusted programs.
- **Additional validation**: Run Python compileall, bash -n scripts/*.sh, node --check site/assets/research.js; Pages deployment must be test-gated.

