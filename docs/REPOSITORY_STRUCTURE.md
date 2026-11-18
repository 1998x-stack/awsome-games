# Repository structure & file lifecycle

> Audited against `main` at `2df5aa8623ba5643f04de69f0ebe6977273114f0`, following PR #15 (2026-11-18). Counts below describe tracked Git files, not all local third-party snapshots.

## Inventory

The audited tree contains **104 tracked files** and **18 directory nodes**. Major tracked groups: `data/` 23 files, `scripts/` 26, `tests/` 13, `docs/` 13, `site/` 8 and `config/` 6.

| Path | Source of truth / role | Mutation policy |
| --- | --- | --- |
| `config/categories.json` | Category vocabulary | Review and test changes |
| `config/project_overrides.json` | Curated entry path and artifact-kind decisions | Evidence-backed edits + reclassification |
| `config/publication_approvals.json` | **Public redistribution approval gate** | Rights and security approval required |
| `config/research_reviews.json` | Reviewed facts distinct from upstream snapshot | Validated explicit application |
| `data/seeds/` | Legacy seed and stable IDs | Preserve identity |
| `data/research/v1/` | Versioned raw research snapshots | Preserve provenance |
| `data/catalog.sqlite` | Tracked operational catalog snapshot | Backup before destructive changes |
| `data/reports/` | Historical browser and reviewer evidence | Append and retain history |
| `games/_repos/` | Untrusted external code, gitignored except approved Soccer artifact | Never blanket-add/publish |
| `scripts/` | Import, browser probes, approvals, site generation | Preserve CLI and module imports |
| `scripts/isolation/` | OS-level networkless Docker boundary | Security review required |
| `site/` | Tracked web HTML/CSS/JS | Generated site data is not source |
| `tests/` | Regression and safety checks | Expand with every new invariant |
| `.github/workflows/` | CI, Pages, research drift and seed recovery | Review triggers and write permissions |
| `docs/` | Runbooks, architecture, audit history | Keep examples synced to code |

### Generated, not source

`data/catalog.json`, `data/summary.json`, `data/projects.csv`, `data/repositories.csv`, `site/data/`, `site/games/`, `site/build-manifest.json`, `.cache/` and `data/backups/` are generated/ignored outputs. They should not be checked in as an accidental second source of truth.

### Execution ownership

- `db.py`: core schema and seed import. `research_pipeline.py`: research schema and ingest. `review_evidence.py`: independent review history.
- `build_catalog.py`: mutable seed/research import and JSON/CSV export; `check_catalog.py`: source-path consistency checks. **`audit_database.py`: independent read-only schema/count/FK audit.**
- `collect_repositories.py`: external snapshots and entrypoint mapping. `mark_unvendored_entries.py`: prevent falsely advertising uncommitted code as playable.
- `browser_batch_probe.py` + `browser_gameplay_probe.py` + `input_attribution.py` + `consolidate_repo_survey.py`: evidence collection and the same input-attribution rule.
- `apply_survey_to_catalog.py`: restrictive survey evidence writer. `build_runtime_evidence.py` / `import_browser_report.py`: reviewed runtime evidence.
- `build_site.py`: allowlisted publication projection, not a generic games/_repos copier.

## Invariants and refactor policy

1. Preserve `config/publication_approvals.json` and the iframe sandbox (no `allow-same-origin`); a clean load or input response is not gameplay proof or redistribution permission.
2. Retain historical survey reports even after retracting older claims. Research source snapshots cannot overwrite human-reviewed decisions.
3. Preserve project IDs, source records, GitHub commit pins and review provenance; do not collapse posts, works and repositories into the same entity.
4. Do **not** mass-move existing scripts yet: the code relies on direct `python scripts/foo.py` entrypoints and neighboring imports. Any package reorganization needs compatibility entrypoints and CI/E2E coverage.
5. PR #12 conflicts with the merged baseline and needs independent rebase/permission/schema review, not blind bulk merge.

## Validation

```bash
python scripts/build_catalog.py --check
python scripts/audit_database.py --profile full
python scripts/check_catalog.py
python -m unittest discover -s tests -v
python scripts/build_site.py
node --check site/assets/app.js
bash -n scripts/*.sh scripts/isolation/*.sh bootstrap.sh
```

This inventory does not claim all 123 local entrypoints are gameplay verified (they are not), or that all 32 M2 candidate repositories were cleared for cloning.
