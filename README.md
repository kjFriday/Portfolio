# Generic Company Inc. — a mini software ecosystem

**Generic Company** stands for **American Company Management Engine**: seven programs that each run on their own
and share only data (a SQLite file and JSON), with no code shared between them at run time. The rules
they share are in [ENGINE.md](create_read_update_delete_simple_io_data_base/ENGINE.md).

Six small desktop programs that run a fictional company, **Generic Company Inc.**, from one shared mock database,
and a seventh that makes install wizards for them (or for any Windows program). Generic Company Inc., its staff,
customers, orders and tickets are all invented.

Each program is self-contained: it opens its own window with its own pixel icon and version, installs
and uninstalls itself, and runs on its bundled snapshot when there is no database. The only link between
them is the **path to the shared SQLite file**.

```
   CRUD Hub      Doc Pipeline     Journal      Notify Hub    Ticket Tracker    Data Dash
   (Python)        (Python)        (Go)          (Go)        (Rust/WASM)      (Rust/WASM)
   tkinter         tkinter        WebView2      WebView2       WebView2         WebView2
      │               │              │              │              │                │
      └───────────────┴──────────────┴──────┬───────┴──────────────┴────────────────┘
                                             ▼
                          %LOCALAPPDATA%\Generic Company Inc\generic_company.db (SQLite)
```

| Program | Folder | Icon (Silk) | Reads | Writes |
|---|---|---|---|---|
| Generic Company CRUD Hub | `create_read_update_delete_simple_io_data_base` | database | every table | every table; owns the schema and the seed |
| Generic Company Doc Pipeline | `document_mover_and_changer` | folder_go | orders, documents, customers, products | documents rows, a `documents.generated` event |
| Generic Company Journal (CMS) | `content_management_system` | newspaper | employees (post authors) | nothing |
| Generic Company Notify Hub | `notification_and_message_hub` | bell | events, customers | `events.status` |
| Generic Company Ticket Tracker | `simple_ticket_tracker` | note | tickets, customers, employees | tickets |
| Generic Company Data Dash | `data_dash` | chart_bar | orders, products, customers, tickets | nothing |

**Dev Console** (`dev_console`, Rust/egui) is a tool for working on the portfolio rather than part of the company: one window that builds, tests, runs and smoke-checks all seven programs, with live re-testing on save and rebindable controls. See [dev_console/README.md](dev_console/README.md).

**Storage Manager** (`drive_and_network_storage_manager`, Python/tkinter) is a stand-alone utility that doesn't use the database. It organizes and cleans folders on local drives (scan, duplicates, sort by type or date, with preview and undo) and handles network shares (check, map, back up to a share). It is one standard-library file, written so it ports easily to other languages. Run it with `python storage_manager.py`. See [its README](drive_and_network_storage_manager/README.md).

**QR Studio** (`qr_code_studio`, Python/tkinter) is a stand-alone utility that reads QR codes from pictures (open or paste; turned, tilted, noisy or mirrored pictures are fine) and makes new ones (PNG, SVG or clipboard). The QR codec is written from scratch in one standard-library file. Run it with `python qr_studio.py`. See [its README](qr_code_studio/README.md).

**Color Voats** (`color_tile_recommender`, Python/tkinter) is a stand-alone utility: a social feed where every post is a color. It starts with the 216 colors of the 6×6×6 cube, and you can post your own. Each post has Good and Bad buttons, Save (for a Saved tab) and a comment section. The For you feed is ranked by your votes ("voats") through an algo aggregation factory. Each algo (net voats, Wilson score, color similarity, exploration, and a mixer that hands on down a chain of algos when one stalls) has a TOML or JSON weights file. A named preset picks the algo and what it uses, and `factory.py` generates a standalone Python ranker for each preset. Run it with `python color_voats.py`. See [its README](color_tile_recommender/README.md).

## Desktop apps

Every program uses the same conventions:

- **Title bar:** `Generic Company Inc. — <name> 0.2.0`. The version has one source per project (Python
  `__version__`, Go `const Version`, Rust `CARGO_PKG_VERSION`) and also appears in the About box and in
  Apps & features.
- **Database path:** `--db PATH`, then the `GENERIC_COMPANY_DB` environment variable, then the path saved from the
  program's own Database… choice (`%LOCALAPPDATA%\Generic Company Inc\<app id>\settings.json`), then
  `%LOCALAPPDATA%\Generic Company Inc\generic_company.db`. Only the hub creates the file and its schema. If the file is missing
  or its schema doesn't match, a program runs on its `mock/` snapshot and says so.
- **Install:** `--install` copies the program to `%LOCALAPPDATA%\Programs\Generic Company Inc\<name>\`, adds it to
  the Start menu under **Generic Company Inc** (`--desktop-shortcut` adds one to the desktop too), and lists it in
  **Apps & features**. It works per user and needs no admin rights.
- **Uninstall:** `--uninstall` removes all of that. It never deletes the shared database.
- **Sandbox:** `--root DIR` does all of the above inside DIR.
- **Other flags:** `--version`, `--quiet`, and `--smoke FILE` (opens the window, writes a JSON report, closes).
- **Windows:** the Python programs use tkinter. The Go and Rust programs use Edge WebView2 (part of
  Windows 10/11), and their pages are served in-process to that window only:
  - Go uses a loopback server with a per-run token.
  - Rust uses a custom `generic-company://` protocol.

| Program | Run | Install |
|---|---|---|
| CRUD Hub | `python main.py` | `python main.py --install` |
| Doc Pipeline | `python -m docpipe` | `python -m docpipe --install` |
| Journal | `go build -trimpath -ldflags "-H windowsgui" -o generic-company-cms.exe .` then `generic-company-cms.exe` | `generic-company-cms.exe -install` |
| Notify Hub | `go build -trimpath -ldflags "-H windowsgui" -o generic-company-notify.exe ./cmd/notify` then `generic-company-notify.exe` | `generic-company-notify.exe -install` |
| Ticket Tracker | `$env:CARGO_ENCODED_RUSTFLAGS = "--remap-path-prefix=$env:USERPROFILE=~"`, `wasm-pack build --target web --out-dir www/pkg --no-typescript`, `cargo build --release --features desktop`, then `target\release\generic-company-tickets.exe` | `generic-company-tickets.exe --install` |
| Data Dash | same as the tracker, then `target\release\generic-company-dash.exe` | `generic-company-dash.exe --install` |

Requirements:

- Python 3.10+ (standard library only); Color Voats needs 3.11+ for `tomllib`.
- Go 1.24 (no cgo needed).
- Rust with the MSVC toolchain, the `wasm32-unknown-unknown` target and `wasm-pack`.

Each project's README has the details and explains its dependencies.

## Install wizards

`install_wizard_maker` is the seventh program, **Generic Company Wizard Maker** (Go, standard library only, a native
Win32 window; Silk icon "wand"). It turns a `setup.json` into one self-contained `setup.exe` for any
Windows program: a classic wizard (license, folder, shortcuts) that installs per user with no admin
rights, lists the program in Apps & features, upgrades it in place by app id, and leaves an uninstaller
that removes only what it installed. It writes the same `install.json` marker and `--root` sandbox as the
programs' own `--install`, so either can take over the other's install. It does not use the database.

| Program | Run | Install |
|---|---|---|
| Wizard Maker | `go build -trimpath -ldflags "-H windowsgui -s -w" -o wizard-maker.exe .` then `wizard-maker.exe` | `wizard-maker.exe -install` |

## Icons

The icons are from the **Silk** set by Mark James (famfamfam.com/lab/icons/silk), licensed under
[Creative Commons Attribution 2.5](http://creativecommons.org/licenses/by/2.5/).

- The unedited 16×16 originals are in `icons/silk/`.
- `tools/pixel_icons.py` (standard library only) makes each project's `icon/` folder: 32, 48 and 256 px
  PNGs, an `.ico` and a Windows resource.
- The only change it makes is enlarging the originals by whole pixels (nearest-neighbour), so every size
  stays pixelated.
- Each `icon/README.md` credits the source and lists every file's SHA-256.
- The tests check that every size matches the original pixel for pixel.

```bash
python tools/pixel_icons.py
```

## Mock data

People are random pairs from common first- and last-name lists, so they look realistic but no one is
real. Free text is lorem ipsum. `seed.py` builds:

- 120 employees
- 3,000 customers
- 15,000 orders and their documents
- 2,000 tickets
- about 17,000 events

The data is identical on every run. Reseeding a database that is already in use backs it up first and
refills it in place. `export_mock.py` writes each project's `mock/` snapshot, plus `mock/schema.sql`
(the hub's schema) for their tests.

```bash
python seed.py
```

```bash
python export_mock.py
```

(run in `create_read_update_delete_simple_io_data_base`)

## Tests

| Project folder | Command |
|---|---|
| `create_read_update_delete_simple_io_data_base` | `python -m unittest discover` |
| `document_mover_and_changer` | `python -m unittest discover -s tests` |
| `content_management_system`, `notification_and_message_hub`, `install_wizard_maker` | `go test ./...` |
| `simple_ticket_tracker`, `data_dash` | `cargo test`, then `cargo test --features desktop` |
| `drive_and_network_storage_manager` | `python storage_manager.py --selftest` |
| `qr_code_studio` | `python -m unittest test_qr_studio` |
| `color_tile_recommender` | `python -m unittest discover -p "test_*.py"` |
| the portfolio folder (icon tool) | `python -m unittest discover -s tools` |
| the portfolio folder (stamps) | `python -m unittest test_stamp` |

`tools/verify.ps1` runs all six programs against one sandbox database. It checks:

- each window's title, icon, version and source;
- that the doc pipeline's registration shows up for the hub;
- that a second Notify pass finds nothing pending;
- that nothing is left holding the file.

## Layout

- `LOG.md`: dated work log.
- `RULES.md`: rules for working in this repo.
- `icons/silk/`: the icon originals; `tools/`: the icon tool, the end-to-end check and a window-screenshot helper.
- Reused code: each project's `PROVENANCE.md` maps adapted files to their originals by SHA-256. The
  originals are kept privately by the owner and are not published.

## License

Copyright (C) 2026 kjFriday.

Every source file begins with a short header (project, file, what it does, the license) and ends with a
stamp: an HMAC-SHA256 of the author's name, the file's path and the rest of the file, made with a key only
the author holds. You may change any file under the license. The stamp shows whether a file still
matches the version the author wrote. `stamp.py` (standard library only) adds and checks the stamps:

```bash
python stamp.py --check
```

`python stamp.py` stamps new files, and `python stamp.py --restamp PATH` re-stamps a file the author has
changed. Generated files, third-party excerpts (`reference/`) and test fixtures (`testdata/`) are not
stamped.

This program is free software: you can redistribute it and/or modify it under the terms of the GNU
Affero General Public License as published by the Free Software Foundation, version 3. It is
distributed WITHOUT ANY WARRANTY; see [LICENSE](LICENSE) for details.

Mock data derived from Wikidata is CC0 1.0 (see each `data/README.md`). Icons: Silk by Mark James, CC BY
2.5, enlarged by nearest-neighbour (see `icons/silk/README.md`).
