// ==== Generic Company Inc. portfolio ====================================
// Project: dev_console | File: src/main.rs
// About: Generic Company Dev Console: one window that builds, tests, runs and smoke-checks every...
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
// ========================================================================

//! Generic Company Dev Console: one window that builds, tests, runs and smoke-checks every portfolio program.
//!
//! This file is the command line (`--version`, `--smoke FILE`, `--install`, `--uninstall`, `--root DIR`,
//! `--quiet`) and the start-up: find the portfolio root, layer the config, open the window. The window is `app`:
//! its state and actions in app.rs, the keyboard controls in app/keys.rs, and the drawing in app/views.rs and
//! app/views/.

#![cfg_attr(not(test), windows_subsystem = "windows")]

mod app;
mod config;
mod desktop;
mod install;
mod jobs;
mod live;
mod production;
mod registry;
mod seed;
mod versions;
mod win;

use std::path::{Path, PathBuf};

use app::App;
use eframe::egui;

const VERSION: &str = env!("CARGO_PKG_VERSION");
const TITLE: &str = concat!("Generic Company Inc. — Dev Console ", env!("CARGO_PKG_VERSION"));

/// The 32 px Silk icon from icon/app-32.rgba (8-byte little-endian width/height header, then RGBA).
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
    install: bool,
    uninstall: bool,
    version: bool,
    quiet: bool,
    root: Option<PathBuf>,
    smoke: Option<PathBuf>,
}

/// Leading dashes are not counted: `--install`, `-install` and `install` are the same flag.
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
fn tell(quiet: bool, text: &str, error: bool) {
    if !quiet {
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
    if args.install || args.uninstall {
        let env = |k: &str| std::env::var(k).ok();
        let result = install::plan(&env, args.root.as_deref()).and_then(|p| {
            if args.install {
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

    let root = std::env::current_dir()
        .ok()
        .and_then(|d| registry::find_root(&d))
        .or_else(|| registry::find_root(&exe_dir));
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

#[cfg(test)]
mod tests {
    use super::*;

    fn v(a: &[&str]) -> Vec<String> {
        a.iter().map(|s| s.to_string()).collect()
    }

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

    #[test]
    fn window_icon_is_32px_rgba() {
        let icon = window_icon();
        assert_eq!((icon.width, icon.height), (32, 32));
        assert_eq!(icon.rgba.len(), 32 * 32 * 4);
    }

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
