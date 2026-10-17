# Rules

How work is done in the ACME Inc. portfolio.

## Data
1. **Mock data only.** Every person, company, address and order is invented. No real personal data, credentials or customer records, ever.
2. **Deterministic seeds.** `seed.py` must produce identical output on every run.
3. **Reused data keeps its license.** Note the source and license in that folder's `data/README.md`. Only CC0 / public-domain or self-authored data is accepted.

## The hub
4. The CRUD hub owns the schema. Other projects read and write **through its API**, not the SQLite file.
5. Schema changes are made in `db.py` `SCHEMA` and logged.
6. All string input passes `textsafe` before it is stored.

## Reused code
7. Originals go to `_extracted/` **unedited**, with a SHA-256 line in `MANIFEST.tsv`. Never edit staged files. `_extracted/` stays local (git-ignored) and is never published.
8. Adapted copies live in the project and are listed in its `PROVENANCE.md` (file → source → symbols).
9. Copy the needed functions only, rename to neutral ACME Inc. terms, and add tests.

## Code
10. Standard library first. Add a dependency only when it earns its place, and say why in the project README.
11. Every helper ships with tests; tests must pass repeatedly (no flaky ordering or float equality).
12. Match the surrounding style.

## Changes and history
13. Small, revertible commits; commit titles of 29 characters or fewer.
14. Nothing is deleted unless a verified backup exists.
15. `LOG.md` gets a dated entry for each working session.

## Public by default
16. `LOG.md`, `README.md` and docs hold **public information only**: no local paths, machine names, account details, backup locations or private project names.

## License
17. All code is AGPL-3.0 (see `LICENSE`). Contributions are accepted under the same license.
