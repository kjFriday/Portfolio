# Developing

How to work on the Generic Company Inc. portfolio: what to install, where things are, and the loop
from an edit to a push. The source files explain themselves; this page gets you to the right file.
The rules are in [RULES.md](../RULES.md). Commands run from the portfolio root unless a folder is named.

## Toolchains

| Tool | Version | Used by |
|---|---|---|
| Python | 3.10+ (3.11+ for Color Voats, which reads TOML with `tomllib`) | CRUD Hub, Doc Pipeline, the four utilities, `tools/*.py` |
| Go | 1.24, no cgo | Journal, Notify Hub, Wizard Maker |
| Rust | stable, MSVC toolchain (`x86_64-pc-windows-msvc`) | Ticket Tracker, Data Dash, Dev Console |
| `wasm32-unknown-unknown` target and `wasm-pack` | any current | the Ticket Tracker and Data Dash pages |

Check them:

```
python --version
go version
rustc --version
rustup target list --installed
wasm-pack --version
```

Add the WebAssembly pieces with `rustup target add wasm32-unknown-unknown` and `cargo install wasm-pack`.
Every program uses the standard library first; a project's README names any dependency and why.

## Layout

| Folder | What | Git |
|---|---|---|
| `company/` | the seven Generic Company programs, which share one SQLite database | each is a git submodule with its own repository |
| `utilities/` | stand-alone programs: Storage Manager, QR Studio, Color Voats, QR Palette | part of this repository |
| `tools/` | the Dev Console, `stamp.py`, `pixel_icons.py`, `verify.ps1`, `shot.ps1` and their tests | part of this repository |
| `docs/` | this page, market notes and research specs | part of this repository |
| `icons/silk/` | the unedited icon originals | part of this repository |

Where to start reading in each program:

| Program | Folder | Language | Start at |
|---|---|---|---|
| CRUD Hub | `company/crud_hub` | Python | `main.py`, then `db.py` (the schema) and `seed.py` |
| Doc Pipeline | `company/doc_pipeline` | Python | `docpipe/__main__.py` |
| Journal | `company/journal` | Go | `main.go`, then `internal/` |
| Notify Hub | `company/notify_hub` | Go | `cmd/notify/` |
| Ticket Tracker | `company/ticket_tracker` | Rust | `src/main.rs` (desktop host), `src/lib.rs` and `src/web.rs` (the page), `src/core/` |
| Data Dash | `company/data_dash` | Rust | the same layout as the Ticket Tracker |
| Wizard Maker | `company/wizard_maker` | Go | `main.go` |
| Storage Manager | `utilities/storage_manager` | Python | `storage_manager.py` |
| QR Studio | `utilities/qr_studio` | Python | `qr_studio.py`, then the `qr_codec` package |
| Color Voats | `utilities/color_voats` | Python | `color_voats.py`, then `voats_core.py`, `algos.py`, `factory.py` |
| QR Palette | `utilities/qr_palette` | Python | `qr_palette.py`, then `gui/` and the modules beside it |
| Dev Console | `tools/dev_console` | Rust | `src/main.rs`, then `src/app.rs` |

Each project's README has a "where to add things" list, its twins and the traps its comments warn about.

New programs go in `company/` when they use the shared database, and in `utilities/` when they stand alone.

## The loop

1. **Edit.** Keep every file and definition documented (see "Annotation standard" below). If the file has
   a twin, make the same change there.
2. **Format.** Go: `gofmt -w .` in the module folder (`gofmt -l .` lists files that need it). Rust:
   `cargo fmt` in the crate folder (`cargo fmt --check` only checks); it reads the crate's
   `rustfmt.toml` (120 columns). Python has no formatter; match the surrounding style.
3. **Test.** Run the program's tests (table below), or tick Live tests in the Dev Console.
4. **Restamp.** `python tools/stamp.py --restamp PATH [PATH ...]` for every source file you changed,
   with paths relative to the portfolio root.
5. **Commit.** A change inside `company/<name>` is committed in that submodule first, then the
   superproject commits the new submodule pointer. Commit titles are 29 characters or fewer.
6. **Push.** Push the submodules first, then the superproject, so the pointer never names a commit
   the submodule's remote lacks.

```
git -C company/journal add internal/app/app.go
git -C company/journal commit -m "Fix post dates"
git add company/journal
git commit -m "Update journal"
git -C company/journal push
git push
```

Changes in `utilities/`, `tools/` or `docs/` are ordinary commits in this repository.

## Stamps

Every tracked source file (`.py`, `.ps1`, `.go`, `.rs`, `.js`, `.css`, `.html`, `.sql`) begins with a
header and ends with a stamp. `tools/stamp.py` writes and checks them; it is standard library only and
runs from any folder.

- **Header:** the program, the file's path inside it, an About line, the copyright and SPDX line, and
  two notice lines. The About line is the first sentence of the file's own doc comment, cut at 90
  characters.
- **Footer:** an HMAC-SHA256 of the author's name, the file's path from the portfolio root and
  everything above the footer. Editing the file, or moving it, breaks the stamp.
- **The key** is 32 bytes held outside the repository: in the `PORTFOLIO_STAMP_KEY` environment
  variable or a key file in the user's home folder (`--init-key` creates it once). Only the author has
  it, so only the author can stamp; anyone may still change a file under the license.
- **Not stamped:** generated files, third-party excerpts (`reference/`), test fixtures (`testdata/`) and
  tool settings (`.claude/`).

| Command | What |
|---|---|
| `python tools/stamp.py --check` | verify every stamp; exit 1 if any is missing or invalid |
| `python tools/stamp.py --dry-run` | list what would be stamped, write nothing |
| `python tools/stamp.py` | stamp files that have no stamp yet |
| `python tools/stamp.py --restamp PATH ...` | re-stamp files after your own edits |

The Dev Console's Apply version restamps the source files it changes by itself.

## Twins

Some files are kept as copies in two programs, because the programs share no code at run time. A change
to one goes to both, in the same session. Each project's README and `PROVENANCE.md` list the allowed
differences (usually the stamp header, an import line or an app id).

| File | Copy in | Copy in |
|---|---|---|
| `internal/app`, `internal/desktop`, `internal/install` | `company/journal` | `company/notify_hub` |
| `src/host/*`, `build.rs`, `tests/icon.rs`, `src/lib.rs`, `www/main.js`, `rustfmt.toml` | `company/ticket_tracker` | `company/data_dash` |
| `textsafe.py`, `paths.py`, `installer.py` and their tests in `tests/` | `company/crud_hub` | `company/doc_pipeline/docpipe` (tests in `company/doc_pipeline/tests`) |
| `algos.py` | `utilities/color_voats` | `utilities/qr_palette` |
| the `qr_codec` package (every module but `images.py` and `distort.py`) | `utilities/qr_studio` | `utilities/qr_palette` |
| `textsafe.py` | `company/crud_hub` | `utilities/qr_palette` |

The cleaning rules of `textsafe.py` are also ported, not copied, to `src/core/validate.rs` (`clean`) in
the Ticket Tracker and `src/host/textsafe.rs` in Data Dash; keep the rules the same.

## Annotation standard

Code is annotated at teaching level: a newcomer should learn what a file does and why from the file.

- Every file starts with a doc comment: what it does, who calls it, its main flow as numbered steps,
  the types it defines, and where to start reading.
- The first sentence of that doc comment is at most 90 characters. `tools/stamp.py` copies it into the
  header's About line and cuts anything longer with "...".
- Every definition (function, method, type, constant, field group) has a doc comment: what it does,
  its inputs and results, and its errors. Notes on why go beside the code they explain.
- The doc comment goes where the language's tools look for it: a Python docstring, a Go `//` comment
  directly above the declaration, a Rust `///` or `//!` comment.

## Comment-sensitive spots

Some comments and lines are read by tools, so their place and wording matter.

- **Version lines.** The Dev Console changes only the first version line in each `version_files` entry
  (`"version"` in JSON, `__version__ =` in Python, `Version =` in Go, `version =` in TOML). Keep the real
  version first: no example version line in a comment above it, and `Cargo.toml`'s `[package]` version
  above any dependency's `version =`.
- **Generated files.** `icon/` and `rsrc_windows_amd64.syso` (from `tools/pixel_icons.py`), `mock/`
  (from the CRUD Hub's `export_mock.py`), Color Voats' `rankers/` (from `factory.py`), `www/pkg/` (from
  `wasm-pack`) and `Cargo.lock` are written by tools. Never edit them by hand, and do not annotate them.
- **"Generated ... do not edit".** `tools/stamp.py` skips any file whose first 600 characters contain
  "generated" followed within 80 characters by "do not edit" (any case). Never write that phrase near
  the top of a hand-written file, or it stops being stamped.
- **`//go:embed`.** The directive must sit directly above its `var`. Put the doc comment above the
  directive, separated by a `//` line:

  ```go
  // license is the program's license text, compiled in.
  //
  //go:embed LICENSE
  var license string
  ```

- **No Rust doc-test blocks.** `cargo test` compiles every code block in a `///` or `//!` comment as a
  test, fenced or indented. Describe examples in prose and inline backticks instead.
- **Color Voats' `algos.py`.** `factory.py` copies function bodies into the rankers, so notes go above
  each `def`, not inside it.

## Dev Console

`tools/dev_console` is one window that builds, tests, runs, version-checks and smoke-checks every
program in `tools/dev_console/config/programs.ini`, with live re-testing on save. Start it from
`tools/dev_console`:

```
cargo run --release
```

To add a program, add its section to `config/programs.ini` and its key to `[programs] order`; no code
changes. See [its README](../tools/dev_console/README.md).

## End-to-end check

`tools/verify.ps1` runs the six database programs against one sandbox database in the temp folder:
it builds the Go programs, seeds a fresh database, opens each window once in `--smoke` mode and checks
the report, makes the programs talk through the file, and checks nothing still holds it open. Build the
Rust programs first (`cargo build --release --features desktop` in `company/ticket_tracker` and
`company/data_dash`), then from the portfolio root:

```
powershell -ExecutionPolicy Bypass -File tools\verify.ps1
```

Each check prints `ok` or `FAIL`; the exit code is 1 when any failed.

## Tests

The commands below are the `test` and `build` lines of `tools/dev_console/config/programs.ini`. Run
each in the program's folder.

| Program | Folder | Test | Build |
|---|---|---|---|
| CRUD Hub | `company/crud_hub` | `python -m unittest discover -s tests -p "test_*.py"` | none |
| Doc Pipeline | `company/doc_pipeline` | `python -m unittest discover -s tests` | none |
| Journal | `company/journal` | `go test ./...` | `go build ./...` |
| Notify Hub | `company/notify_hub` | `go test ./...` | `go build ./...` |
| Ticket Tracker | `company/ticket_tracker` | `cargo test` | `cargo build --release --features desktop` |
| Data Dash | `company/data_dash` | `cargo test` | `cargo build --release --features desktop` |
| Wizard Maker | `company/wizard_maker` | `go test ./...` | `go build ./...` |
| Storage Manager | `utilities/storage_manager` | `python storage_manager.py --selftest` | none |
| QR Studio | `utilities/qr_studio` | `python -m unittest discover -s tests` | none |
| Color Voats | `utilities/color_voats` | `python -m unittest discover -s tests` | none |
| QR Palette | `utilities/qr_palette` | `python -m unittest discover -s tests` | none |
| Dev Console | `tools/dev_console` | `cargo test` | `cargo build --release` |
| portfolio tools | the portfolio root | `python -m unittest discover -s tools` | none |

The Rust desktop programs also have `cargo test --features desktop`. Before their desktop build, the
page is built with `wasm-pack build --target web --out-dir www/pkg --no-typescript`.
