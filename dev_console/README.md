# Generic Company Dev Console

One window for working on the whole Generic Company Inc. portfolio: build, test, run, version-check and
smoke-check each of the seven programs, watch their output, and re-run tests as you save.

The console runs each program's own commands as separate processes, so the programs still share no code
at run time.

## Run

```
cargo run --release
```

Start it from anywhere inside the portfolio folder; it finds the portfolio by looking upward for
`RULES.md`.

## What it does

- **Programs** (left): the seven programs with their language and the result of their last test run.
  **Test all** runs every suite at once.
- **Actions** for the selected program: Build (Go and Rust only), Test, Run, Version (`--version`) and
  Smoke (`--smoke FILE`; the report is added to the log).
- **Live tests**: tick it, and the program's tests run again whenever a file in its folder is saved.
- **Desktop shortcuts** (Ctrl+Shift+D): builds every program from source (Go: `go build`; Rust: `wasm-pack` then `cargo build --release --features desktop`; Python needs no build), then puts two shortcuts per program on the desktop: `<name> <version>` (from its `setup.json`, with its own icon) that starts that build, and `<name> source` that opens its folder. A program that fails to build gets no shortcut. Running it again replaces the old set, so a new version replaces the old shortcut; **Remove desktop shortcuts** takes the set away. The list of what was placed is kept in the user's config folder.
- **Jobs and log**: a tab per job with its status; output appears as it is printed (last 5,000 lines).

## Views

The window has four views (Ctrl+1 to Ctrl+4). Every button, field and mark has a hover tooltip that says what it does, which command it runs, and its keys.

- **Run**: the actions below for the selected program, and the output of the selected job.
- **Versions & commands**: the selected program's version as written in each of its `version_files`, flagged when they disagree. Type a version, or bump the patch, minor or major part, then **Apply version** writes it into every file and renews the stamps of the source files it changed (`stamp.py --restamp`); nothing is committed. Below it, the program's commands (launch, test, build, desktop build, desktop run) can be edited; the tooltip shows how each line is split into words. **Save commands** writes `config/programs.ini`.
- **Seed data**: the CRUD Hub's shared database (default `GENERIC_COMPANY_DB`, then `%LOCALAPPDATA%\Generic Company Inc\generic_company.db`): its size, rows per table and dated backups. **Refresh counts** reads it; **Back up now**, **Reseed** (backup, then refill in place), **Rebuild fresh** (delete and rebuild, no backup), **Restore selected** (backup, then copy the chosen backup over it) and **Export mock snapshots** all run the hub's own `seed.py` / `export_mock.py`, so the hub stays the only program that writes the schema. Reseed, Rebuild fresh and Restore ask for a second click.
- **live-production**: each program with a `production` command or `production_url` in `programs.ini` (today the Journal, as `go run . -public -addr 127.0.0.1:8722`). **Start** runs the command (it refuses while something else already answers on the address), waits for the site to answer and checks it; **Stop** ends it and every process it started (`taskkill /T`), and closing the console stops it too; **Open in browser**; **Check now** checks the address whether or not the console started it, so `production_url` can also be a deployed `https://` site; **Keep checking** repeats on a timer. The checks are the `production_checks` list (`METHOD /path STATUS`), then the four security headers (Content-Security-Policy, X-Frame-Options, X-Content-Type-Options, Referrer-Policy) on every 200 answer, then that no answer shows your user folder or the portfolio folder. They go through Windows' own `curl.exe`. The server's output is the job's log.

## Config fileset

`config/` holds the defaults:

| File | Sections | What |
|---|---|---|
| `controls.ini` | `[controls]` | every keyboard control; `action = Ctrl+Shift+Key`, empty turns it off |
| `programs.ini` | one per program | name, folder, language, launch/test/build/desktop commands, the optional `production`, `production_url` and `production_checks`, and version files; edited in the Versions & commands view. The highest layer that has this file is used whole |
| `settings.ini` | `[view]`, `[live]`, `[production]` | text size and its limits, live-mode interval and skipped folders, and the live-production check interval, check timeout and start wait |

Layers, lowest first: built-in defaults, `config/` in this project, `config/` beside the installed exe,
then the user's own copies in `%LOCALAPPDATA%\Generic Company Inc\GenericCompany.DevConsole\`. A layer
only needs the keys it changes. The console saves the text size to the user's `settings.ini`.

Default controls:

| Control | Keys |
|---|---|
| Text larger / smaller / reset | Ctrl+Plus (or Ctrl+=) / Ctrl+Minus / Ctrl+0 |
| Build, Test, Run, Version, Smoke | F4, F5, F6, F7, F8 |
| Test all | Ctrl+Shift+T |
| Live tests on/off | Ctrl+L |
| Desktop shortcuts | Ctrl+Shift+D |
| Run / Versions & commands / Seed data / live-production view | Ctrl+1 / Ctrl+2 / Ctrl+3 / Ctrl+4 |
| Next / previous program | Ctrl+Down / Ctrl+Up |

## Install

`--install` copies the program and its `config/` folder to
`%LOCALAPPDATA%\Programs\Generic Company Inc\Generic Company Dev Console\`, adds a Start menu shortcut
under **Generic Company Inc** and lists it in **Apps & features**. `--uninstall` removes all of that and
keeps your settings. `--root DIR` does both inside DIR; `--quiet` shows no message box.

## Icon

`icon/` is generated by `tools/pixel_icons.py` from Silk's `application_xp_terminal.png` (Mark James, CC BY 2.5); see [icon/README.md](icon/README.md). `build.rs` links `icon/app.res` into the exe and the window uses `icon/app-32.rgba`. The credit is also in the window's About section.

## Dependency

`eframe` (egui) draws the native window. The other Rust programs use a WebView page, but a dev tool that
mostly shows buttons and scrolling text is simpler as an immediate-mode native UI, with no HTML or
JavaScript to keep in step. Everything else (config parsing, file watching, process handling, install)
uses the standard library.

## Tests

```
cargo test
```

`cargo test -- --ignored` also runs the two slow ones: the Journal's production command started on a
free port, checked (every check passes) and stopped (the port is closed again), once through
`production.rs` and once through the view's own Start and Stop. They need Go.
