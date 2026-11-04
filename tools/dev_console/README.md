# Generic Company Dev Console

One window for working on the whole Generic Company Inc. portfolio: build, test, run, version-check and
smoke-check every program listed in `config/programs.ini` (today eleven: the seven programs under `company/`
and four under `utilities/`), watch their output, and re-run tests as you save.

The console runs each program's own commands as separate processes, so the programs still share no code
at run time.

## Run

```
cd tools/dev_console
cargo run --release
```

Once built, the exe can be started from anywhere inside the portfolio folder; it finds the portfolio by
looking upward for `RULES.md` (from the current folder, then from the exe's folder). Started outside the
portfolio, the window opens but runs nothing.

## What it does

- **Programs** (left): every program in `programs.ini`, in its `[programs] order`, with its language and
  the result of its last test run. **Test all** runs every suite at once.
- **Actions** for the selected program: Build (only when it has a `build` command: today the Go and Rust
  programs), Test, Run, Version (`--version`) and Smoke (`--smoke FILE`; the report is added to the log).
- **Live tests**: tick it, and the program's tests run again whenever a file in its folder is saved.
- **Desktop shortcuts** (Ctrl+Shift+D): builds every program from source by running its `desktop_build`
  steps (Go: `go build`; Rust: `wasm-pack` then `cargo build --release --features desktop`; Python needs
  no build), then puts two shortcuts per program on the desktop: `<name> <version>` (from its `setup.json`,
  with its own icon) that starts that build, and `<name> source` that opens its folder. A program that fails
  to build gets no shortcut. Running it again replaces the old set, so a new version replaces the old
  shortcut; **Remove desktop shortcuts** takes the set away. The list of what was placed is kept in
  `desktop-shortcuts.txt` in the user's config folder.
- **Jobs and log**: a tab per job with its status; output appears as it is printed (last 5,000 lines).

## Views

The window has four views (Ctrl+1 to Ctrl+4). Every button, field and mark has a hover tooltip that says what it does, which command it runs, and its keys.

- **Run**: the actions above for the selected program, and the output of the selected job.
- **Versions & commands**: the selected program's version as written in each of its `version_files`, flagged when they disagree. Type a version, or bump the patch, minor or major part, then **Apply version** writes it into every file and renews the stamps of the source files it changed (`python tools/stamp.py --restamp`, run from the portfolio root); nothing is committed. Below it, the program's commands (launch, test, build, desktop build, desktop run, production, production URL, production checks) can be edited; the tooltip shows how each line is split into words. **Save commands** writes `programs.ini`.
- **Seed data**: the CRUD Hub's shared database (default `GENERIC_COMPANY_DB`, then `%LOCALAPPDATA%\Generic Company Inc\generic_company.db`): its size, rows per table and dated backups. **Refresh counts** reads it; **Back up now**, **Reseed** (backup, then refill in place), **Rebuild fresh** (delete and rebuild, no backup), **Restore selected** (backup, then copy the chosen backup over it) and **Export mock snapshots** all run the hub's own code in `company/crud_hub` (`seed.py`, `export_mock.py`), so the hub stays the only program that writes the schema. Reseed, Rebuild fresh and Restore ask for a second click.
- **live-production**: each program with a `production` command or `production_url` in `programs.ini` (today the Journal, as `go run . -public -addr 127.0.0.1:8722`). **Start** runs the command (it refuses while something else already answers on the address), waits for the site to answer and checks it; **Stop** ends it and every process it started (`taskkill /T`), and closing the console stops it too; **Open in browser**; **Check now** checks the address whether or not the console started it, so `production_url` can also be a deployed `https://` site; **Keep checking** repeats on a timer. The checks are the `production_checks` list (`METHOD /path STATUS`), then the four security headers (Content-Security-Policy, X-Frame-Options, X-Content-Type-Options, Referrer-Policy) on every 200 answer, then that no answer shows your user folder or the portfolio folder. They go through Windows' own `curl.exe`. The server's output is the job's log.

## Config fileset

`config/` holds the defaults:

| File | Sections | What |
|---|---|---|
| `controls.ini` | `[controls]` | every keyboard control; `action = Ctrl+Shift+Key`, empty turns it off |
| `programs.ini` | `[programs]`, then one per program | the programs and the commands the console runs for each (keys below); edited in the Versions & commands view. The highest layer that has this file is used whole |
| `settings.ini` | `[view]`, `[live]`, `[production]` | text size and its limits, live-mode interval and skipped folders, and the live-production check interval, check timeout and start wait |

Layers, lowest first: built-in defaults (the three files are baked into the exe), `config/` in this
project, `config/` beside the exe, then the user's own copies in
`%LOCALAPPDATA%\Generic Company Inc\GenericCompany.DevConsole\`. A layer only needs the keys it changes
(except `programs.ini`, which is taken whole). The console saves the text size to the user's
`settings.ini`, and **Save commands** writes `programs.ini` back to the layer it came from (with no file in
any layer, to `config/` in this project).

### programs.ini keys

`[programs] order = key, key, ...` lists the programs in sidebar order; a section not named there is
ignored. Each program then has a section named by its key:

| Key | Required | What |
|---|---|---|
| `name` | no | short name in the list (default: the section name) |
| `dir` | yes | project folder relative to the portfolio root, with `/`; every command runs there |
| `lang` | yes | `Python`, `Go` or `Rust` (shown in the list; the commands come from the keys below) |
| `launch` | yes | starts the program (Run); Version and Smoke add `--version` / `--smoke FILE` after it, so a `cargo run` launch must end with `--` |
| `test` | no | runs its tests (Test, Test all, Live tests) |
| `build` | no | builds it (Build); empty means nothing to build |
| `desktop_build` | no | the Desktop shortcuts build, as steps separated by `&&` |
| `desktop_run` | no | what the desktop shortcut starts: an exe relative to `dir`, or `pythonw <args>` |
| `production` | no | serves the live site (live-production **Start**) |
| `production_url` | no | where the live site answers: `http://host:port`, or a deployed `https://` address |
| `production_checks` | no | what live-production checks: `METHOD /path STATUS`, separated by commas |
| `version_files` | no | files relative to `dir`, separated by commas, that each hold the version; the first version line in each is the one read and changed |

Commands are not run through a shell: the console splits each line into words itself, so `&&`, `|` and
`>` mean nothing in them (only `desktop_build` is split on `&&`). Quote an argument that holds spaces with
double quotes. A listed section with no `dir` or `launch`, or another `lang`, is skipped with a warning in
the sidebar.

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

## How it works

1. `main.rs` reads the flags. `--version` prints the version from `Cargo.toml`; `--install` and
   `--uninstall` hand over to `install.rs` and exit.
2. `registry::find_root` finds the portfolio root (the folder with `RULES.md`), and `config::load` layers
   `controls.ini`, `programs.ini` and `settings.ini` (see Config fileset).
3. `App::new` (`app.rs`) turns `programs.ini` into `Program`s (`registry::load`), and the window opens. On
   the first frame `App::first_frame` sets the text size and starts the Live tests thread (`live.rs`).
4. Every frame, `app/views.rs` drains the job events (`App::drain`), applies the keys (`app/keys.rs`), and
   draws the sidebar and the current view.
5. A button or key becomes a job: `registry::command` builds the `Cmd` for a program and action, and
   `jobs::spawn` runs it in the program's folder, streaming each output line back as an `Event`. When a
   job ends, its follow-up runs: the last-test mark, a `--smoke` report read into the log, new seed
   counts, or a restamp.
6. The other views do their work through the same jobs: `versions.rs` edits version lines, `seed.rs`
   builds the CRUD Hub commands, `production.rs` probes a site with `curl.exe` on a background thread, and
   `desktop.rs` runs build steps and a PowerShell script for the shortcuts.
7. `--smoke FILE` writes a JSON report after the first frame (title, version, number of programs,
   whether the root was found, controls, warnings, views, live sites) and closes the window.

Where state lives:

| What | Where |
|---|---|
| Defaults | `config/*.ini` here, baked into the exe at build time (`include_str!` in `config.rs`) |
| Your settings, controls and saved commands | `%LOCALAPPDATA%\Generic Company Inc\GenericCompany.DevConsole\` |
| Placed desktop shortcuts | `desktop-shortcuts.txt` in that same folder |
| Versions | each program's own `version_files` (no copy in the console) |
| Seed data | the CRUD Hub's database and its dated backups, changed only through the hub's scripts |
| Install | the program folder, a Start menu shortcut and an uninstall entry under `HKEY_CURRENT_USER` |
| Jobs, logs, Live tests ticks, check results | memory only; gone when the window closes |

## Code map

In reading order; the entry point is `src/main.rs`. Each file opens with a comment that says what it does.

| File | What |
|---|---|
| `src/main.rs` | the flags, the config layers, the window icon, opening the window |
| `src/app.rs` | the console's state and actions: jobs and their events, live tests, the live site, seed data, versions and commands, the `--smoke` report |
| `src/app/keys.rs` | the keyboard controls from `controls.ini` |
| `src/app/views.rs` | each frame's panels, the view tabs, the Run bar, the job tabs and the log |
| `src/app/views/sidebar.rs` | the program list, Test all, desktop shortcut buttons, text size, warnings, About |
| `src/app/views/versions.rs` | the Versions & commands view |
| `src/app/views/seed.rs` | the Seed data view |
| `src/app/views/production.rs` | the live-production view |
| `src/config.rs` | the config fileset and its layers |
| `src/registry.rs` | `programs.ini` as programs, and the command each action runs |
| `src/jobs.rs` | child processes and their streamed output |
| `src/live.rs` | the file polling behind Live tests |
| `src/versions.rs` | finding and changing version lines |
| `src/seed.rs` | the CRUD Hub's seed commands, row counts and dated backups |
| `src/production.rs` | the live-production checks |
| `src/desktop.rs` | desktop shortcuts |
| `src/install.rs` | per-user install and uninstall |
| `src/win.rs` | Windows plumbing: the no-console-window flag and PowerShell quoting |
| `build.rs` | links `icon/app.res` into the exe |

Tests sit at the end of each file in a `#[cfg(test)] mod tests`: the flag parser and the real version
files (`main.rs`), the shipped `programs.ini`, word splitting and each action's command (`registry.rs`),
config layers (`config.rs`), jobs, live polling, version lines, seed commands, check judging, desktop and
install plans in sandbox folders, PowerShell quoting, the key text (`app/keys.rs`), the view keys
(`app/views/production.rs`), and the two slow live-site tests (`app.rs`, `production.rs`).

## Developing

From `tools/dev_console`:

| Task | Command |
|---|---|
| Run | `cargo run --release` |
| Test | `cargo test` |
| Slow tests too | `cargo test -- --ignored` (the Journal's production command started on a free port, checked and stopped, once through `production.rs` and once through the view's own Start and Stop; needs Go) |
| Version | `cargo run --release -- --version` |
| Smoke check | `cargo run --release -- --smoke $env:TEMP\console-smoke.json` (PowerShell), then read that file: expect `"root_found": true` and `"warnings": 0` |
| Build | `cargo build --release` gives `target/release/generic-company-console.exe` |
| Install | `target/release/generic-company-console.exe --install` |

Where to add things:

- **A program**: add its section to `config/programs.ini` and its key to `[programs] order`. No code
  changes; `cargo test` then checks that every `version_files` entry holds a valid version line.
- **A keyboard control**: add the key to `config/controls.ini` and handle it in `App::keys`
  (`src/app/keys.rs`); show it on the button with `App::hint`.
- **A view**: add it to `View` and `View::ALL` in `src/app.rs` (label, `controls.ini` key, help), a
  `view_...` line in `config/controls.ini`, and its drawing as a new file under `src/app/views/`.
- **A command field**: add it to `FIELDS` and `Program` in `src/registry.rs` (with `field`, `field_mut`
  and `load`), and to the key list above.

The console has no twin: no file here is kept identical to another program's copy.

Traps the code comments warn about:

- **Version lines.** `versions.rs` changes only the first version line in each file (JSON `"version"`,
  Python `__version__`, Go `Version =`, TOML `version =`), so `Cargo.toml`'s `[package]` version must
  stay above any dependency's `version = "..."`. Apply version restamps the changed source files but not
  `setup.json`.
- **Stamps.** Every source file ends with a stamp line; after editing one, run
  `python tools/stamp.py --restamp <path>` from the portfolio root.
- **Generated files.** `icon/` is written by `tools/pixel_icons.py`; do not edit it by hand.
  `Cargo.lock` is written by Cargo.
- **Baked-in defaults.** `config/*.ini` is compiled into the exe, so an edit there needs a rebuild to
  change the built-in layer, and the tests read the shipped `programs.ini`.
- **Saving drops comments.** **Save commands** rewrites `programs.ini` from `registry::render` with a short
  header; comments added by hand are lost.
- **Action order.** `Action::ALL` in `registry.rs` is indexed by number in `app.rs`, so its order matters,
  and each action's `controls.ini` key is its button label in lower case.
- **Console windows.** A release build is a GUI program; every child process must be started with
  `win::CREATE_NO_WINDOW`, and every path spliced into a PowerShell script must go through `win::ps_quote`.
