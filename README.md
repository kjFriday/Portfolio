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
  (Go)     (FastAPI+React)   (Python)      (planned)       (planned)
```

| Project | Folder | Status |
|---|---|---|
| CRUD hub | `create_read_update_delete_simple_io_data_base` | Working: GUI, REST API, seed data, tests |
| Content management | `content_management_system` | Helper packages tested; server not yet wired |
| Data dashboard | `data_dash` | Fixture data only |
| Document pipeline | `document_mover_and_changer` | `docpipe` helpers tested; pipeline not built |
| Notification hub | `notification_and_message_hub` | Design reference + templates |
| Ticket tracker | `simple_ticket_tracker` | Needs a spec |

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
| GET | `/api/{table}?limit=N` | List rows |
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

## Layout

- `LOG.md` — dated work log.
- `RULES.md` — rules for working in this repo.
- `_extracted/` — unedited originals of reused code plus a SHA-256 `MANIFEST.tsv`; each project's `PROVENANCE.md` maps adapted files back to them.

## License

Copyright (C) 2026 kjFriday.

This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, version 3. It is distributed WITHOUT ANY WARRANTY; see [LICENSE](LICENSE) for details.

Mock data derived from Wikidata is CC0 1.0 (see each `data/README.md`).
