# SQLite schema migrations (evidence-gated)

Initial baseline: `main` commit `adfdc3b`. The actual SQLite schema SHA-256
`21fdf1d9dbcb2262ffdbbb77b7120efcc622b70835a6cfbaaa1993bbcfca0cd0`
was independently observed in Actions [run 44235409998](https://github.com/1998x-stack/awsome-games/actions/runs/44235409998) after building the catalog.
26 tables, FK violations 0, integrity ok, user_version 0.

## Purpose and what v1 changes

`scripts/migrate_database.py` is a strict, explicit, reversible migration
entry point. Migration `0001-baseline-existing-catalog` adds only a
`schema_migrations` ledger table and sets `PRAGMA user_version=1`.
It **does not rename, delete, update or infer** any existing project, evidence
or research row. It does not claim new game validation or licensing.

The ledger holds migration ID, SHA-256 of the migration SQL, before/after schema
fingerprints and application UTC time. Unknown baseline fingerprints, unknown
future versions and tampered ledger content fail closed. Any newly changed DDL
requires a distinct future numbered migration and its own before/after test.

## Operational sequence

On a clean checkout with the currently committed **v0** SQLite:

```bash
python scripts/build_catalog.py --check
python scripts/audit_database.py --profile full
python scripts/migrate_database.py                       # read-only plan
python scripts/migrate_database.py --verify-copy         # CI test on temp copy
```

**Only for a deliberate local rollout**, after ensuring no other writer is
active and retaining an independent offline backup:

```bash
python scripts/migrate_database.py --apply
python scripts/migrate_database.py                       # show already_applied
python scripts/audit_database.py --profile full
python scripts/check_catalog.py
```

The apply path takes a BEGIN IMMEDIATE lock, creates a *WAL-aware SQLite backup
while the write reservation is held*, validates backup integrity/FKs, checks the
fingerprint again, runs the single schema migration in a transaction, and
verifies that a deterministic digest of every pre-existing row stays unchanged.
If a pre-commit check fails, the transaction is rolled back. If a later
unexpected issue arises, the backup path is printed for explicit restoration.

Local backups go to `data/backups/` (already ignored by Git). Do not commit
backup files, WAL sidecars or arbitrary binary copies of SQLite. Never run
`build_catalog.py --fresh` merely to force migration to pass: it can erase
curated state.

## Compatibility and CI gate

The repository currently commits the **original v0 SQLite snapshot**. The
migration is tested by `--verify-copy` on a disposable copy in CI, not
silently applied to the checkout or Pages build. Updating the committed binary
snapshot must be a separate evidence-backed change with reviewed row digests.

Only the observed 26-table v0 signature is auto-adopted. A local DB with an
older 25-table shape or an unknown extra table is intentionally rejected:
audit it first, and introduce an explicit reviewed migration rather than
bypassing the hash guard.

The existing `db.connect()` and `research_pipeline` initialize tables for
legacy compatibility; they are **not** a replacement for this explicit ledger.
Before a future column migration, callers should be changed to enforce
migration version/ordering, with clean-bootstrap and upgrade-copy tests.
