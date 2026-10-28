# Generic Company Inc. Portfolio — Log

Generic Company Inc. is a fictional company. All data in this ecosystem is mock data.

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
- Renamed the company from "Company X" to "Generic Company Inc." everywhere: env vars `GENERIC_COMPANY_DB` / `GENERIC_COMPANY_HOST` / `GENERIC_COMPANY_PORT`, database file `generic_company.db`, Go module `generic-company/cms`, mock email domain `generic-company.example`. All tests re-run and pass.

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

**Six desktop programs, one shared database** (version 0.2.0 everywhere)
- Each project is now a self-contained program: its own window with its own pixel icon and version in the title, `--install` / `--uninstall` per user (Start menu under Generic Company Inc, Apps & features, no admin rights), and a `--root` sandbox. The only link between programs is the path to the shared SQLite file (`--db`, `GENERIC_COMPANY_DB`, a saved setting, or `%LOCALAPPDATA%\Generic Company Inc\generic_company.db`); with no database each runs on its snapshot.
- Icons: six Silk icons (Mark James, CC BY 2.5), enlarged by whole pixels only. `tools/pixel_icons.py` (stdlib) writes each project's `icon/` (PNG sizes, `.ico`, a Windows resource with a DPI-aware manifest, a Go `.syso`); RULES #3 allows CC BY icons with credit.
- CRUD hub: menu, status bar, About; reseeding backs the file up and refills it in place; `export_mock.py` also writes `mock/schema.sql`. The REST API is retired (in git history).
- Doc pipeline: a tkinter window (run, register, manifest, preview); reads and writes the database directly.
- CMS and Notify hub: WebView2 windows (`github.com/jchv/go-webview2`, pure Go) over an in-process server that only the window can use; SQLite through `modernc.org/sqlite` v1.46.1 (last for Go 1.24). Notify has a queue/dispatch/deliveries window.
- Ticket tracker and Data Dash: a `desktop` cargo feature (`wry`, `tao`, `rusqlite` bundled) hosts the wasm page and answers the hub's API contract from the shared file through an `generic_company://` protocol; Data Dash read-only.
- RULES #4: programs open the shared file by path and write only their own rows. New rule 18: every project is a self-contained desktop program.

**Verification**
- Python: hub 54 and docpipe 81 tests, 5 runs each. Go: `go vet` clean, `go test -count=5` passes in both. Rust: `cargo test` and `cargo test --features desktop` pass in both. Icon tool: 13 tests.
- `tools/verify.ps1` against a fresh sandbox database: all six windows open with their icon, version and the database as source; the doc pipeline's registration is visible to the hub; Notify takes 222 pending events to 0 and a second pass changes nothing; the file is free once every program closes.
- Sandbox install, launch of the installed copy and self-uninstall checked for all six. A real (non-sandbox) install has not been run.

**install_wizard_maker** (new: Generic Company Wizard Maker, the seventh program)
- Makes install wizards: `wizard-maker.exe build setup.json` (or its window) turns a program's files into one self-contained `setup.exe`. Go 1.24, standard library only: native Win32 windows through `syscall`, shortcuts through COM (with the AppUserModelID the PowerShell shortcuts cannot set), the registry through advapi32.
- A setup is the maker's own exe with the program's icon and version info rewritten into its last PE section (pure Go, no UpdateResource), then a zip and a 32-byte trailer. Same input, same bytes, wherever the folder is.
- The wizard: Welcome, License (Next waits for "I accept"), Install Folder (only a new, empty or own folder), Shortcuts, Installing, Finish (Launch through the new shortcut). Upgrade in place by app id, repair at the same version, a downgrade refused. Per user only: it refuses to run as administrator.
- Installing is one transaction (unpack and check SHA-256 first, set replaced files aside, any failure or Cancel puts everything back; tested by failing at every step). The uninstaller removes only what setup installed and only unchanged files, then removes itself after it exits.
- Same marker (`install.json`), folders and `--root` sandbox as the six programs' own `--install`, so either installer can take over the other's install. `{python}` programs get the newest registered CPython (PEP 514) in their shortcut.
- Layouts grow with both the DPI and the user's text size ("Make text bigger"); `-smoke FILE` walks every window, captures each page and reports every control.
- The maker installs itself (`-install` builds its own setup.exe and runs it; Help menu too). Icon: Silk "wand" (CC BY 2.5), added with a `controls` manifest option in `tools/pixel_icons.py` (Common Controls 6, asInvoker); the six projects' `app.res` are unchanged.
- Verification: `go vet` clean; `go test -count=5 ./...` passes (end-to-end installs, upgrades, refusals and uninstalls in a sandbox, through the quiet path and through the windows). Icon tool: 16 tests. A real (non-sandbox) install of a throwaway fixture showed its Apps & features entry and Start-menu shortcut, and its uninstaller left nothing behind. The maker's own setup.exe (from its `setup.json`) installs and uninstalls in a sandbox. Only 142 % text size was checked by eye (the layout scales with it); other DPI settings were not.

**A setup.exe for each program** (made with Generic Company Wizard Maker)
- Each of the six projects has a `setup.json`: `wizard-maker.exe build setup.json` makes `dist\<name>-0.2.0-setup.exe` (git-ignored). App id, name, group (Generic Company Inc), icon and settings folder (which the uninstaller offers to remove) are the ones the program's own `--install` uses.
- What each packs: the CMS and the Notify hub, their exe; the ticket tracker and Data Dash, the release exe and `www` (with `www/pkg` rebuilt); the CRUD hub and the doc pipeline, exactly the files their own installer copies (22 and 31), started by the newest registered Python 3.10+ with the AppUserModelID their window sets (`GenericCompany.Hub`, `GenericCompany.DocPipe`), so the taskbar keeps window and shortcut together.
- Checked for all six, each in its own sandbox: quiet install (every file matches its source by SHA-256; marker, Start-menu shortcut and Apps & features entry as expected), the installed copy started the way its shortcut starts it (title, icon, version, the shared database as source), a repair at the same version, the uninstaller with `-purge` (settings folder gone, shared database kept, nothing left behind), and both windows walked with `-smoke` at 96 DPI and 142 % text size (every control inside its window, clear of the others, its text fitting). Rebuilding gives byte-identical setups. No real (non-sandbox) install was run.
- The six projects have no LICENSE file of their own, so their setups show no License page.

## 2026-10-18

**Setups ready to publish** (the six programs)
- Trimmed build paths. The exes and the wasm carried the build machine's user folder (Go module cache, cargo registry, rustup library sources) and the project folder. The Go READMEs now build with `go build -trimpath`. The Rust READMEs first set `CARGO_ENCODED_RUSTFLAGS` to `--remap-path-prefix=<user folder>=~`, which `wasm-pack` and `cargo build` both use (one flag, so a folder name with spaces works); cargo's `trim-paths` profile option is still unstable on cargo 1.99. The portfolio README's table matches.
- Ticket tracker and Data Dash: the source-tree fallback for `www` no longer compiles in the project folder (`CARGO_MANIFEST_DIR`). It stays in release builds, since `target\release\generic-company-*.exe`, `--install` run from there and `tools/verify.ps1` use it, but is found at run time: the `www` in the project above the `target` folder holding the exe. An installed copy uses the `www` beside it, as before. New test.
- Each project now has the AGPL-3.0 `LICENSE`, and its `setup.json` names it, so its setup shows the License page (Next waits for "I accept"). The doc pipeline README gained a License section. Each README's Install section says how to build the setup.
- Checked from a clean checkout of each repo: tests pass (CRUD hub 63, doc pipeline 90, Go vet and tests in both, Rust 16 + 38 and 18 + 41). The exes, the wasm, the maker and all six setups were built as the READMEs say; no exe, wasm or installed file holds the user folder, the portfolio folder or a module-cache path. The same sandbox check as on 2026-10-17 passed for all six, now with the License page walked by `-smoke`. Rebuilding gives byte-identical setups.

**Source stamps** (portfolio and all seven projects)
- New `stamp.py` (standard library only) with `test_stamp.py` (27 tests). It adds a header to every tracked source file (project, file, a one-line description taken from the file's own doc comment, copyright, AGPL-3.0 SPDX line, a pointer to `PROVENANCE.md` where the project has one). It also adds a footer: an HMAC-SHA256 of the author's name, the file's path and the rest of the file, under a private key kept outside the repo. `--check` reports files that are unstamped or no longer match; `--restamp PATH` re-stamps after the author's own edits.
- 193 files stamped (Go, Python, Rust, PowerShell, JS, CSS, HTML). Not stamped: the five generated `mock/schema.sql` files, `reference/` excerpts and `testdata/` fixtures. Shebangs, coding cookies, doctypes and build tags stay where they must, and line endings and BOMs are kept.
- Checked after stamping: CRUD hub 63, doc pipeline 90, icon tool 16, Go vet and tests in all three Go projects, Rust 16 + 3 / 38 + 3 (tracker) and 18 + 3 / 41 + 3 (Data Dash) with and without `desktop`; gofmt clean. `cargo fmt --check` reports the same diffs as before stamping, none in the stamps.

## 2026-10-26

**The Generic Company engine**
- Generic Company now stands for **American Company Management Engine**: the seven programs and the contracts
  they share. Named in the portfolio README, the hub README and the hub's About box.
- New `ENGINE.md` in the hub: one rule (every program runs on its own and shares data, never code or
  processes) and five contracts (database, JSON snapshot, settings, install marker, identity), plus
  the order for paring the programs down.
- Checked: hub 63 tests pass; `--smoke` against a temporary database opens the window; `stamp.py
  --check` is clean after re-stamping `main.py`.

## 2026-10-28

**Rename**
- ACME is now Generic Company everywhere: display names, app ids (`GenericCompany.*`), the `GENERIC_COMPANY_DB` variable, binaries (`generic-company-*.exe`), Go module paths and the shared `generic_company.db`. The wizard payload magic is now `GENCOWZ1`, so installers built before the rename need rebuilding.

**dev_console** (new, Rust/egui)
- One native window that builds, tests, runs, version-checks and smoke-checks all seven programs, with output streamed into a tab per job and a pass/fail mark per program.
- Live tests: re-runs a program's tests when a file in its folder is saved.
- Config fileset in `dev_console/config/`: `settings.ini` (text size, live interval, skipped folders) and `controls.ini` (every keyboard control, rebindable). The user's own copies under the app's settings folder override single keys.
- Text size with Ctrl+Plus / Ctrl+Minus / Ctrl+0, saved between runs.
- `--install`, `--uninstall`, `--root`, `--quiet`, `--version`, `--smoke FILE`, like the other programs.
- Desktop shortcuts button: builds all seven programs from source, then places a versioned shortcut to each build (with its icon) and a shortcut to each source folder on the desktop; re-running replaces old versions, and a Remove button takes them away.
- Three views with hover tooltips on every control: Run; Versions & commands (version across all of a program's version files, with bump buttons and a restamp; commands editable and saved to the new `config/programs.ini`); Seed data (shared database counts, backups, reseed, fresh rebuild, restore and mock export, all through the CRUD Hub's own `seed.py` / `export_mock.py`).
- Icon: Silk `application_xp_terminal.png` (CC BY 2.5), added to `icons/silk` and `tools/pixel_icons.py`.

**drive_and_network_storage_manager** (new, Python/tkinter)
- Generic Company Storage Manager: organizes and cleans folders on local drives and handles network shares. One file, standard library only.
- Scan (size, largest and stale files, empty folders), duplicate finder (size, then SHA-256), organize by type or year-month, and a Network tab: saved shares, reachability and free space, map / disconnect (`net use`), one-way backup of a folder to a share.
- Every change is previewed and confirmed. Nothing is deleted: extra duplicates go to a trash folder inside the scanned folder, and each change can be undone. Passwords are never stored.
- Written to port easily: plain functions and records, explicit loops, errors returned as records, and the core kept apart from the GUI.
- `--version`, `--smoke FILE` and `--selftest` (29 checks, all pass). Added to the Dev Console's `programs.ini`.

**drive_and_network_storage_manager 0.2.0** (faster, simpler window)
- One `os.scandir` pass finds sizes, dates and empty folders (no per-file `stat`, no second walk); duplicates reuse it and are narrowed by size, then both ends of large files, then SHA-256, read on 8 threads; a backup lists source and share once and compares in memory. On 40,000 files: scan 9.6 s to 0.3 s, duplicates 38.0 s to 4.2 s, backup planning 13.5 s to 0.6 s.
- New window: one Analyze button and a sidebar (Overview, Largest, Old, Duplicates, Empty, Unreadable, Organize, Network shares, Activity) with counts; actions work on the selection or on everything; lists sort, cap at 2,000 rows and update after a change without a new scan; choose which duplicate to keep; show in folder; recent folders and drives in the folder box; Delete, Ctrl+Z, F5.
- `--folder PATH [--view KEY]`; `--selftest` now 49 checks, all pass; an in-process window test pressed every action and checked the disk.

**qr_code_studio** (new, Python/tkinter)
- Generic Company QR Studio: reads QR codes from pictures and makes new ones. One file, standard library only; the codec is written from scratch (Reed-Solomon, encoder for versions 1-40 and levels L/M/Q/H, finder and alignment search, perspective sampling).
- Read tab (open or paste a picture), Make tab (live preview, save PNG or SVG, copy the picture) and a local History tab. Links open only after confirmation.
- `--read`, `--make`, `--version`, `--smoke FILE` and `--selftest`; `test_qr_studio.py` (24 tests, all pass) covers the ISO/IEC 18004 annex example, every version and mask, and turned, mirrored, scaled, noisy, tilted and unevenly lit pictures. Added to the Dev Console's `programs.ini`.
- Icon: a self-drawn 16×16 QR glyph, enlarged with `tools/pixel_icons.py`.

**Ticket tracker and Data Dash: every page request answered 400**
- The rename made the window's protocol `generic_company://`. A URI scheme cannot hold `_`, so wry could not rebuild each request's URI and answered 400 before the program saw it: the page, the wasm and every `/api` call. The protocol is now `generic-company://` (`host::SCHEME`), with a test that the URI parses.
- Checked: `cargo test`, with and without `desktop`, in both; `wasm-pack` and release builds; `--smoke` as the Dev Console runs it: Data Dash 15,000 orders and 2,000 tickets from the shared database, the tracker 2,000 tickets.

**content_management_system: `-public`, to host the Journal as a website**
- `-public -addr :8080` serves the pages and API read-only: no database form (`POST /about` gets 405), no local paths in the footer, About page or log, no `/api/health`. `-serve` and `-public` send CSP, `X-Frame-Options`, `nosniff` and `Referrer-Policy`, use read/write/idle timeouts and stop cleanly on Ctrl+C or SIGTERM.
- Builds for Linux too (`internal/desktop/window_other.go`, `internal/install/hide_*.go`): there only `-serve` and `-public` work.
- Checked: `go vet` and `go test` (new `TestPublic`), `GOOS=linux` vet and build, and the `cms-public` preview in a browser.

**dev_console: live-production view** (Ctrl+4)
- Starts and stops a program's live site from its new `production` command in `programs.ini` (the Journal: `go run . -public -addr 127.0.0.1:8722`), opens it, and checks `production_url`: each `production_checks` entry (`GET / 200, … POST /about 405, GET /api/health 404`), the four security headers on every 200 answer, and no user or portfolio folder path in any answer. Checks go through Windows' `curl.exe`, so a deployed `https://` URL works too; "Keep checking" repeats them (`settings.ini [production]`).
- Jobs can now be stopped: `Event::Started` carries the process id, Stop runs `taskkill /T` (the server `go run` starts dies with it) and the job ends as Stopped, not as a failure. Closing the console stops a running live site.
- Checked: `cargo test` (47), and `cargo test -- --ignored`: the Journal started on a free port passed all 7 checks and its port was closed after Stop, both through `production.rs` and through the view's own Start and Stop. `--smoke` lists the four views. The window itself was not looked at.

## Open
- cms: writing posts; moving posts into the shared database (a `posts` table in the hub's schema).
- document_mover_and_changer: stages 2-3 (parsing, chunking) for incoming files.
- notification_and_message_hub: real channels behind the outbox; retry for held messages.
- simple_ticket_tracker: comments, priorities, due dates.
- install_wizard_maker: code signing; the six programs' `--uninstall` could hand over to `uninstall.exe` when a wizard installed them.