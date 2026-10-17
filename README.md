# ACME Inc. — a mini software ecosystem

Six small programs that run a fictional company, **ACME Inc.**, from one shared mock database. ACME Inc., its staff, customers, orders and tickets are all invented.

```
                 ┌──────────────────────────────┐
                 │  CRUD hub  (Python, SQLite)  │
                 │  tkinter GUI + REST :8700    │
                 └──────────────┬───────────────┘
                                │ JSON over HTTP
   ┌───────────────┬────────────┼─────────────┬────────────────┐
   ▼               ▼            ▼             ▼                ▼
  CMS          Data Dash   Doc pipeline   Notify hub    Ticket tracker
  (Go)       (Rust/WASM)     (Python)        (Go)         (Rust/WASM)
```

| Project | Folder | Status |
|---|---|---|
| CRUD hub | `create_read_update_delete_simple_io_data_base` | Working: GUI, REST API, seed data, tests |
| Content management | `content_management_system` | Helper packages tested; server not yet wired |
| Data dashboard | `data_dash` | Working: business + fixture charts, standalone or live |
| Document pipeline | `document_mover_and_changer` | `docpipe` helpers tested; pipeline not built |
| Notification hub | `notification_and_message_hub` | Throttle + textsafe packages; dispatcher not built |
| Ticket tracker | `simple_ticket_tracker` | Working: kanban board with CRUD, standalone or live |

## Standalone or connected

Every project carries a `mock/` folder: a JSON snapshot of the hub's seeded rows (same ids), written by
`export_mock.py`. A project runs on its snapshot with nothing else started, and switches to the live hub
API to show the projects talking to each other. The Rust/WASM apps have a *Data* switch for this
(`?source=hub` in the URL does the same).

Mock data: people are random pairs from common first- and last-name lists (realistic, but no one real);
free text is lorem ipsum. `seed.py` builds 120 employees, 3,000 customers, 15,000 orders and documents,
2,000 tickets and about 17,000 events, identical on every run.

```bash
python seed.py
```

```bash
python export_mock.py
```

(run in `create_read_update_delete_simple_io_data_base`)

## Quick start (Ticket tracker, Data Dash)

Requires Rust with the `wasm32-unknown-unknown` target and `wasm-pack`. In `simple_ticket_tracker` or
`data_dash`:

```bash
wasm-pack build --target web --out-dir www/pkg --no-typescript
```

```bash
python -m http.server 8710 --bind 127.0.0.1 --directory www
```

(use port 8711 for `data_dash`), then open the page. Each project's README has the details.

## Quick start (CRUD hub)

Requires Python 3.10+ (stdlib only).

```bash
cd create_read_update_delete_simple_io_data_base
python seed.py
```

```bash
python api.py
```

Then open `http://127.0.0.1:8700/api/` or run `python main.py` for the desktop GUI.

### API

| Method | Path | Does |
|---|---|---|
| GET | `/api/` | List tables and columns |
| GET | `/api/{table}?limit=N&offset=M` | List rows, newest first (`limit` 1-500); `X-Total-Count` header gives the table size |
| GET | `/api/{table}/{id}` | One row |
| POST | `/api/{table}` | Create (JSON body) → `{"id": n}` |
| PATCH | `/api/{table}/{id}` | Update |
| DELETE | `/api/{table}/{id}` | Delete |

Tables: `employees`, `customers`, `products`, `orders`, `tickets`, `documents`, `events`. String input is sanitized; an unknown table returns `404` with a `did_you_mean` hint.

## Tests

```bash
python -m unittest discover
```

(run in `create_read_update_delete_simple_io_data_base`; in `document_mover_and_changer` add `-s tests`)

```bash
go test ./internal/...
```

(run in `content_management_system`)

```bash
cargo test
```

(run in `simple_ticket_tracker` and `data_dash`)

## Layout

- `LOG.md` — dated work log.
- `RULES.md` — rules for working in this repo.
- `_extracted/` — unedited originals of reused code plus a SHA-256 `MANIFEST.tsv`; each project's `PROVENANCE.md` maps adapted files back to them.

## License

Copyright (C) 2026 kjFriday.

This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, version 3. It is distributed WITHOUT ANY WARRANTY; see [LICENSE](LICENSE) for details.

Mock data derived from Wikidata is CC0 1.0 (see each `data/README.md`).
