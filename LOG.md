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

## 2026-10-17

**CRUD hub** (`create_read_update_delete_simple_io_data_base`)
- API contract: a bad `?limit` (it must be 1-500), a body that is not a JSON object, or a write with no known columns now answers **400**. A constraint failure, such as a NOT NULL column or deleting a row that other rows still reference, answers **409**. Before, those requests crashed the handler and dropped the connection.
- Text cleaning moved into the data layer, so the GUI's writes go through `textsafe` too. The GUI's Update stores blank fields as NULL.
- Added `test_db.py` and `test_api.py` (the API is tested over real HTTP against a temporary database). 32 tests pass on 5 runs in a row. Seed output is unchanged and deterministic.

**Mock data, wider** (`create_read_update_delete_simple_io_data_base`)
- People are random pairs from new common first/last-name lists (`data/first_names.txt`, `data/last_names.txt`), unique across staff and customers. Free text is lorem ipsum (`lorem.py`).
- Seed sizes: 120 employees, 3,000 customers, 15,000 orders, 15,000 documents, 2,000 tickets, about 17,000 events. Seeding takes about 6 s; two runs give byte-identical databases.
- Schema: `tickets.body` (TEXT). API: `?offset=N` paging and an `X-Total-Count` header. `db.create_rows` inserts many rows in one transaction.
- `export_mock.py` writes a `mock/` JSON snapshot into every project, with references kept whole, so each project runs on its own.
- Added `test_seed.py`; 41 hub tests pass.

**simple_ticket_tracker**
- Built in Rust → WebAssembly with an HTML page and a minimal JS loader. Kanban board (open / in progress / closed) with create, edit, move, delete, and filters. Runs on its snapshot, or live against the hub (each API call shown in the status bar; falls back to the snapshot when the hub is down). Added `SPEC.md`. 16 tests.

**data_dash**
- Rebuilt in Rust → WebAssembly, replacing the FastAPI + React plan. Business tab (revenue by month/category, top products and customers, tickets by status) from the snapshot or the live hub; fixture tab charts `numbers.dat` and `tracks.dat` as `data/README.md` describes. Hand-built SVG charts, validated reference palette. 18 tests.

**Verification**
- Both apps checked in a browser: standalone and live modes, no console errors. Tracker: move, create (escaped HTML), delete round-trip through the API. Dash: live totals match SQL over all 15,000 orders.

**Every project runs on its own** (bare bones; each also talks to the hub)
- Hub seed: `order.created` events now carry `customer_id`, and order/ticket events from the seeded today's last 3 days stay `pending` (222 in all), so the dispatcher has a queue. Snapshots re-exported. 42 hub tests.
- content_management_system: the cgo SQLite server moved to `reference/` (kept, not built). New stdlib server on :8720: post list, post pages, related posts (`internal/related`), did-you-mean (`internal/suggest`), search, health. Posts from `mock/posts.json`; authors from the snapshot or, with `-hub`, the hub's `employees`. New `internal/store` with tests.
- document_mover_and_changer: `python -m docpipe` renders invoices, receipts and packing slips at each `documents` row's path, with a SHA-256 manifest; `--hub ... --register` reads the newest orders from the hub and writes back missing `documents` rows and a `documents.generated` event. 51 tests.
- notification_and_message_hub: `go run ./cmd/dispatch` routes pending events to customers, throttles per recipient on the events' own clock and writes an outbox; with `-hub` it PATCHes event statuses (a second run finds the queue empty).
- Checked against the running hub: CMS authors (120) from the API, docpipe registered its run event, the dispatcher sent 222 events' messages and marked them.

**Publishing**
- Six project repos pushed. The staged originals in `_extracted/` are private, so they are now git-ignored and were removed from this repo's unpublished history before its first push; the local copy is unchanged. Provenance notes no longer name a local folder. Leftover files nothing used were removed from the projects.

## Open
- cms: writing posts (auth, storage); a pure-Go SQLite driver if posts move to a database.
- document_mover_and_changer: stages 2-3 (parsing, chunking) for incoming files.
- notification_and_message_hub: real channels behind the outbox; retry for held messages.
- simple_ticket_tracker: comments, priorities, due dates.
