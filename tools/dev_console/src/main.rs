// ==== Generic Company Inc. portfolio ====================================
// Project: dev_console | File: src/main.rs
// About: Generic Company Dev Console: one window that builds, tests, runs and smoke-checks every...
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
// ========================================================================

//! The Dev Console's entry point: command-line flags, start-up and opening the window.
//!
//! Generic Company Dev Console is one window that builds, tests, runs and smoke-checks every portfolio
//! program. This file is the command line (`--version`, `--smoke FILE`, `--install`, `--uninstall`,
//! `--root DIR`, `--quiet`) and the start-up: find the portfolio root, layer the config, open the window. The
//! window is `app`: its state and actions in app.rs, the keyboard controls in app/keys.rs, and the drawing in
//! app/views.rs and app/views/.
//!
//! `main` in order:
//! 1. Parse the flags; a bad one shows a message box and exits with code 2.
//! 2. `--version` prints the version and stops.
//! 3. `--install` / `--uninstall` hand over to install.rs, report through `tell` and stop (exit code 1 on
//!    failure).
//! 4. Otherwise find the portfolio root (the folder with RULES.md) from the current folder, then from the
//!    exe's folder.
//! 5. Load the config layers (config.rs) and open the eframe window with `App::new`.
//!
//! Defines `Args`. Start reading at `main`.

// A release build is a GUI program (no console window opens with it); test builds stay console programs so
// `cargo test` can print.
#![cfg_attr(not(test), windows_subsystem = "windows")]

/// The window: state and actions (app.rs), keys and views (app/).
mod app;
/// The config fileset (controls.ini, programs.ini, settings.ini) and its layers.
mod config;
/// Desktop shortcuts: build every program, then place a shortcut per program.
mod desktop;
/// Per-user install and uninstall.
mod install;
/// Child processes and their streamed output.
mod jobs;
/// The file polling behind Live tests.
mod live;
/// The live-production checks.
mod production;
/// programs.ini as programs, and the command each action runs.
mod registry;
/// The CRUD Hub's seed database: commands, counts and backups.
mod seed;
/// Finding and changing version lines.
mod versions;
/// Windows plumbing: the no-console-window flag and PowerShell quoting.
mod win;

use std::path::{Path, PathBuf};

use app::App;
use eframe::egui;

/// The console's version, from Cargo.toml at build time; `--version` prints it.
const VERSION: &str = env!("CARGO_PKG_VERSION");
/// The window title. `concat!` needs literals, so it repeats `env!` instead of using VERSION.
const TITLE: &str = concat!("Generic Company Inc. — Dev Console ", env!("CARGO_PKG_VERSION"));

/// The 32 px Silk icon from icon/app-32.rgba (8-byte little-endian width/height header, then RGBA).
///
/// The file is baked into the exe with `include_bytes!`, so the window has its icon even when installed
/// alone. It holds width and height as two little-endian u32, then width * height * 4 bytes of RGBA pixels
/// row by row, as tools/pixel_icons.py writes it.
fn window_icon() -> egui::IconData {
    const RAW: &[u8] = include_bytes!("../icon/app-32.rgba");
    let dim = |i: usize| u32::from_le_bytes(RAW[i..i + 4].try_into().unwrap());
    egui::IconData {
        rgba: RAW[8..].to_vec(),
        width: dim(0),
        height: dim(4),
    }
}

/// The command line, as parse_args reads it.
struct Args {
    /// `--install`: install for this user and exit.
    install: bool,
    /// `--uninstall`: uninstall and exit (Apps & features runs this).
    uninstall: bool,
    /// `--version`: print the version and exit.
    version: bool,
    /// `--quiet`: no message box for install results or errors; the exit code still tells.
    quiet: bool,
    /// `--root DIR`: install into or uninstall from a sandbox folder instead of the real places.
    root: Option<PathBuf>,
    /// `--smoke FILE`: open the window, write a JSON report to FILE and close (the portfolio's smoke check).
    smoke: Option<PathBuf>,
}

/// Leading dashes are not counted: `--install`, `-install` and `install` are the same flag.
///
/// `args` excludes the program name. Err names an unknown option or a `--root` / `--smoke` with no value
/// after it. Flags combine freely; `main` decides which wins.
fn parse_args(args: &[String]) -> Result<Args, String> {
    let mut a = Args {
        install: false,
        uninstall: false,
        version: false,
        quiet: false,
        root: None,
        smoke: None,
    };
    let mut it = args.iter();
    while let Some(x) = it.next() {
        match x.trim_start_matches('-') {
            "install" => a.install = true,
            "uninstall" => a.uninstall = true,
            "version" => a.version = true,
            "quiet" => a.quiet = true,
            "root" => a.root = Some(it.next().ok_or("--root needs a folder")?.into()),
            "smoke" => a.smoke = Some(it.next().ok_or("--smoke needs a file")?.into()),
            _ => return Err(format!("unknown option {x}")),
        }
    }
    Ok(a)
}

/// Show a result: a message box normally, nothing with --quiet (the exit code still tells).
///
/// A GUI-subsystem exe has no console to print to, so the box comes from PowerShell's
/// System.Windows.Forms.MessageBox. `error` picks the Error icon instead of Information. Blocks until the
/// box is closed; a failure to start PowerShell is ignored.
fn tell(quiet: bool, text: &str, error: bool) {
    if !quiet {
        // `text` goes into a single-quoted PowerShell string, so its quotes are doubled (the ps_quote rule)
        let icon = if error { "Error" } else { "Information" };
        let script = format!(
            "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('{}', '{}', 'OK', '{icon}') | Out-Null",
            text.replace('\'', "''"),
            install::NAME
        );
        let _ = std::process::Command::new("powershell")
            .args(["-NoProfile", "-Command", &script])
            .status();
    }
}

/// Start the console: run a command-line action, or open the window.
///
/// Exit codes: 0 done, 1 install/uninstall or window failure, 2 bad command line. See the file doc for
/// the order of the steps.
fn main() {
    let argv: Vec<String> = std::env::args().skip(1).collect();
    let args = match parse_args(&argv) {
        Ok(a) => a,
        Err(e) => {
            tell(false, &e, true);
            std::process::exit(2);
        }
    };
    if args.version {
        println!("{VERSION}");
        return;
    }
    let exe = std::env::current_exe().unwrap_or_default();
    let exe_dir = exe.parent().map(Path::to_path_buf).unwrap_or_default();
    // ---- install / uninstall ----
    if args.install || args.uninstall {
        let env = |k: &str| std::env::var(k).ok();
        let result = install::plan(&env, args.root.as_deref()).and_then(|p| {
            if args.install {
                // the config/ beside the exe (an installed or copied build), else the source tree's own
                // (a `cargo run` build, whose exe sits in target/); CARGO_MANIFEST_DIR is fixed at compile time
                let config = [
                    exe_dir.join("config"),
                    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("config"),
                ]
                .into_iter()
                .find(|d| d.is_dir());
                install::install(&p, &exe, config.as_deref(), VERSION)
                    .map(|_| format!("{} {VERSION} is installed in {}.", install::NAME, p.dir.display()))
            } else {
                install::uninstall(&p, &exe)
                    .map(|_| format!("{} is uninstalled. Your settings are kept.", install::NAME))
            }
        });
        match result {
            Ok(msg) => tell(args.quiet, &msg, false),
            Err(e) => {
                tell(args.quiet, &e, true);
                std::process::exit(1);
            }
        }
        return;
    }

    // ---- the window ----
    // the root may be missing (an installed console started outside the portfolio); the window then shows
    // that and runs nothing
    let root = std::env::current_dir()
        .ok()
        .and_then(|d| registry::find_root(&d))
        .or_else(|| registry::find_root(&exe_dir));
    // layers lowest first: the project's config/, then the one beside the exe; the user's own folder is
    // added on top by config::load
    let mut layers = vec![exe_dir.join("config")];
    if let Some(r) = &root {
        layers.insert(0, r.join("tools").join("dev_console").join("config"));
    }
    let local = std::env::var_os("LOCALAPPDATA").map(PathBuf::from);
    let cfg = config::load(&layers, config::user_dir(local.as_deref()));

    let opts = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_title(TITLE)
            .with_inner_size([1100.0, 720.0])
            .with_icon(window_icon()),
        ..Default::default()
    };
    let smoke = args.smoke;
    if let Err(e) = eframe::run_native(TITLE, opts, Box::new(move |_| Ok(Box::new(App::new(cfg, root, smoke))))) {
        tell(args.quiet, &e.to_string(), true);
        std::process::exit(1);
    }
}

/// Unit tests: the flag parser, the baked-in icon, and the version files programs.ini names.
#[cfg(test)]
mod tests {
    use super::*;

    // The &str list as the owned argument list parse_args takes.
    fn v(a: &[&str]) -> Vec<String> {
        a.iter().map(|s| s.to_string()).collect()
    }

    // One- and two-dash spellings both work, values follow their flag, and a missing value or unknown flag fails.
    #[test]
    fn args_parse_both_dash_styles() {
        let a = parse_args(&v(&["--install", "-root", "X", "--quiet"])).unwrap();
        assert!(a.install && a.quiet && !a.uninstall);
        assert_eq!(a.root.as_deref(), Some(Path::new("X")));
        assert_eq!(
            parse_args(&v(&["--smoke", "r.json"])).unwrap().smoke.as_deref(),
            Some(Path::new("r.json"))
        );
        assert!(parse_args(&v(&["--root"])).is_err());
        assert!(parse_args(&v(&["--bogus"])).is_err());
    }

    // The icon header says 32 x 32 and the pixel data is exactly 32 * 32 * 4 bytes, so the file is not cut off.
    #[test]
    fn window_icon_is_32px_rgba() {
        let icon = window_icon();
        assert_eq!((icon.width, icon.height), (32, 32));
        assert_eq!(icon.rgba.len(), 32 * 32 * 4);
    }

    // Every version file in the default programs.ini, read from the real portfolio, holds a valid version line,
    // so the Versions view never opens on a missing or malformed one.
    #[test]
    fn default_version_files_all_have_a_version() {
        let root = registry::find_root(Path::new(env!("CARGO_MANIFEST_DIR"))).unwrap();
        let (programs, _) = registry::load(&config::parse(include_str!("../config/programs.ini")));
        for p in &programs {
            for f in &p.version_files {
                let s = versions::find_in(&root.join(&p.dir).join(f)).unwrap();
                assert!(versions::valid(&s.value), "{}/{f}: {}", p.dir, s.value);
            }
        }
    }
}

// ==== stamp v1 | author=kjFriday | hmac-sha256=cff5ca0bf3a1c83a577d3cd086044176cde7387b4440452590ab7ba6a7dad027 ====
