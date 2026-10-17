# ACME Inc. Portfolio — Log

ACME Inc. is a fictional company. All data in this ecosystem is mock data.

## 2026-10-16

**CRUD hub** (`create_read_update_delete_simple_io_data_base`)
- Seven-table SQLite schema: employees, customers, products, orders, tickets, documents, events.
- `seed.py` generates deterministic mock data (same output every run).
- `api.py`: stdlib REST API on port 8700 (`GET/POST/PATCH/DELETE /api/{table}`); input is sanitized; an unknown table returns a `did_you_mean` hint.
- `main.py`: tkinter GUI with one CRUD tab per table.
- Added `textsafe.py` (input sanitizer) and `sigil.py` (identicon avatars), with tests.

**Code reuse pass**
- Reviewed older personal projects for generic, reusable code; 12 candidates kept after review, 83 rejected.
- Originals staged unedited in `_extracted/` with a SHA-256 manifest; adapted copies placed in each project with a `PROVENANCE.md`.

**content_management_system**
- New Go packages, all tested: `internal/related` (TF-IDF related posts), `internal/suggest` (did-you-mean), `internal/textfmt` (text helpers), `internal/health` (runtime health JSON).

**document_mover_and_changer**
- New `docpipe` package, tested: chunked SHA-256 hashing, metadata text folding, text-shape document classifier.

**notification_and_message_hub**
- Throttle design reference and seasonal message templates.

**data_dash**
- Chart fixture data files.

**Verification**
- Go: `go vet` + `go test` pass (repeated 20×). Python: 13 hub tests and 41 docpipe tests pass.

**Docs and rename**
- Added `README.md`, `RULES.md` and `LICENSE` (AGPL-3.0).
- Renamed the company from "Company X" to "ACME Inc." everywhere: env vars `ACME_DB` / `ACME_HOST` / `ACME_PORT`, database file `acme.db`, Go module `acme/cms`, mock email domain `acme.example`. All tests re-run and pass.

**Cleanup**
- Older source projects removed from the portfolio folder after their backups were verified file-by-file (SHA-256). Reused code remains in `_extracted/`.

## Open
- cms: switch to a pure-Go SQLite driver so `main.go` builds; wire the new packages into routes.
- data_dash: build the dashboard over the hub API.
- document_mover_and_changer: build the pipeline (orders → invoice files → `documents` table).
- notification_and_message_hub: choose a language; build the event dispatcher.
- simple_ticket_tracker: needs a real spec.
- Put each project under version control; umbrella repo with submodules.
