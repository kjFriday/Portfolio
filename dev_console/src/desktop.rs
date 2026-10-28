// ==== Generic Company Inc. portfolio ====================================
// Project: portfolio | File: dev_console/src/desktop.rs
// About: Desktop shortcuts: build each program from source, then put a versioned shortcut to that...
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
// ========================================================================

//! Desktop shortcuts: build each program from source, then put a versioned shortcut to that build (with the
//! program's own icon) and a shortcut to its source folder on the desktop. A list of what was placed is kept
//! in the user's config folder, so the next run replaces old versions and Remove takes them all away.

use std::path::{Path, PathBuf};
use std::sync::mpsc::Sender;

use crate::jobs::{self, Event, Status};
use crate::registry::{self, Cmd, Program};

/// The list of shortcuts placed last time, one full path per line.
pub const MANIFEST: &str = "desktop-shortcuts.txt";

/// The string value of `"key": "..."` in a small JSON file (setup.json); enough for name and version.
pub fn json_str(text: &str, key: &str) -> Option<String> {
    let at = text.find(&format!("\"{key}\""))? + key.len() + 2;
    let rest = text[at..].trim_start().strip_prefix(':')?.trim_start().strip_prefix('"')?;
    let end = rest.find('"')?;
    Some(rest[..end].to_string())
}

/// One program's pair of shortcuts.
#[derive(Debug, PartialEq)]
pub struct Shortcut {
    /// "Generic Company Journal 0.2.0"
    pub label: String,
    pub folder: PathBuf,
    pub icon: PathBuf,
    pub target: TargetPath,
}

#[derive(Debug, PartialEq)]
pub enum TargetPath {
    File(PathBuf),
    Pythonw(Vec<String>),
}

/// Name and version from the project's setup.json, and where its shortcut points (`desktop_run`).
pub fn shortcut(root: &Path, p: &Program) -> Result<Shortcut, String> {
    let folder = root.join(&p.dir);
    let setup = std::fs::read_to_string(folder.join("setup.json")).map_err(|e| format!("{}: setup.json: {e}", p.dir))?;
    let name = json_str(&setup, "name").ok_or_else(|| format!("{}: setup.json has no name", p.dir))?;
    let version = json_str(&setup, "version").ok_or_else(|| format!("{}: setup.json has no version", p.dir))?;
    let words = registry::split_args(&p.desktop_run);
    let target = match words.split_first() {
        None => return Err(format!("{}: desktop_run is empty", p.name)),
        Some((first, rest)) if first.eq_ignore_ascii_case("pythonw") => TargetPath::Pythonw(rest.to_vec()),
        Some(_) => TargetPath::File(folder.join(p.desktop_run.trim().trim_matches('"'))),
    };
    Ok(Shortcut { label: format!("{name} {version}"), icon: folder.join("icon").join("app.ico"), folder, target })
}
fn q(s: &str) -> String {
    format!("'{}'", s.replace('\'', "''"))
}

fn qp(p: &Path) -> String {
    q(&p.to_string_lossy())
}

/// PowerShell that removes `old` shortcuts and places `set` on the desktop (or in `desktop`, for tests),
/// printing the full path of every shortcut it made.
pub fn script(set: &[Shortcut], old: &[PathBuf], desktop: Option<&Path>) -> String {
    let mut s = String::from("$ErrorActionPreference='Stop'; $w=New-Object -ComObject WScript.Shell;\n");
    s += &match desktop {
        Some(d) => format!("$d={};\n", qp(d)),
        None => "$d=[Environment]::GetFolderPath('Desktop');\n".into(),
    };
    for o in old {
        s += &format!("Remove-Item -LiteralPath {} -ErrorAction SilentlyContinue;\n", qp(o));
    }
    let place = |file: &str, target: &str, args: &str, cwd: &Path, icon: &str, what: &str| {
        format!(
            "$p=Join-Path $d {}; $k=$w.CreateShortcut($p); $k.TargetPath={target}; $k.Arguments={}; \
             $k.WorkingDirectory={}; {icon}$k.Description={}; $k.Save(); Write-Output $p;\n",
            q(file),
            q(args),
            qp(cwd),
            q(what)
        )
    };
    for sc in set {
        // A program without icon/app.ico keeps the default icon of its target.
        let icon = if sc.icon.is_file() { format!("$k.IconLocation={};", q(&format!("{},0", sc.icon.display()))) } else { String::new() };
        let (target, args) = match &sc.target {
            TargetPath::File(p) => (qp(p), String::new()),
            TargetPath::Pythonw(a) => ("(Get-Command 'pythonw').Source".to_string(), a.join(" ")),
        };
        s += &place(&format!("{}.lnk", sc.label), &target, &args, &sc.folder, &icon, &format!("{} (built from source)", sc.label));
        let folder_name = sc.label.rsplit_once(' ').map_or(sc.label.as_str(), |(n, _)| n);
        s += &place(
            &format!("{folder_name} source.lnk"),
            &qp(&sc.folder),
            "",
            &sc.folder,
            "",
            &format!("{folder_name} source folder"),
        );
    }
    s
}

/// Paths listed in the manifest in `user_dir`.
pub fn placed(user_dir: &Path) -> Vec<PathBuf> {
    std::fs::read_to_string(user_dir.join(MANIFEST))
        .map(|t| t.lines().filter(|l| !l.trim().is_empty()).map(PathBuf::from).collect())
        .unwrap_or_default()
}

fn powershell(id: usize, script: &str, tx: &Sender<Event>, wake: &(impl Fn() + Send + Clone + 'static)) -> (Status, Vec<PathBuf>) {
    let out = std::env::temp_dir().join(format!("gc-console-desktop-{}-{id}.txt", std::process::id()));
    let full = format!("& {{ {script} }} | Set-Content -Encoding utf8 -LiteralPath {}", qp(&out));
    let cmd = Cmd {
        program: "powershell".into(),
        args: ["-NoProfile", "-NonInteractive", "-Command", &full].map(String::from).to_vec(),
        cwd: std::env::temp_dir(),
    };
    let status = jobs::run(id, &cmd, tx, wake);
    let made = std::fs::read_to_string(&out)
        .map(|t| t.trim_start_matches('\u{feff}').lines().filter(|l| !l.is_empty()).map(PathBuf::from).collect())
        .unwrap_or_default();
    let _ = std::fs::remove_file(out);
    (status, made)
}

/// Build every program, then place shortcuts for the ones that built. Runs on its own thread as job `id`.
pub fn make(
    id: usize,
    programs: Vec<Program>,
    root: PathBuf,
    user_dir: PathBuf,
    desktop: Option<PathBuf>,
    tx: Sender<Event>,
    wake: impl Fn() + Send + Clone + 'static,
) {
    std::thread::spawn(move || {
        let say = |l: String| {
            let _ = tx.send(Event::Line(id, l));
            wake();
        };
        let mut set = vec![];
        let mut failed = 0;
        for r in &programs {
            let sc = match shortcut(&root, r) {
                Ok(sc) => sc,
                Err(e) => {
                    say(format!("skip: {e}"));
                    failed += 1;
                    continue;
                }
            };
            say(format!("== {} ==", sc.label));
            let mut ok = true;
            for step in registry::steps(&r.desktop_build) {
                let Some(cmd) = Cmd::new(step, sc.folder.clone()) else { continue };
                say(format!("> {} {}", cmd.program, cmd.args.join(" ")));
                let st = jobs::run(id, &cmd, &tx, &wake);
                if st != Status::Exited(0) {
                    say(format!("build failed ({st:?}); no shortcut for {}", sc.label));
                    ok = false;
                    break;
                }
            }
            if let (true, TargetPath::File(p)) = (ok, &sc.target) {
                if !p.is_file() {
                    say(format!("built, but {} is missing; no shortcut", p.display()));
                    ok = false;
                }
            }
            if ok {
                set.push(sc);
            } else {
                failed += 1;
            }
        }
        say(format!("placing {} program shortcuts and {} folder shortcuts", set.len(), set.len()));
        let (st, made) = powershell(id, &script(&set, &placed(&user_dir), desktop.as_deref()), &tx, &wake);
        let _ = std::fs::create_dir_all(&user_dir);
        let list: String = made.iter().map(|p| format!("{}\n", p.display())).collect();
        let _ = std::fs::write(user_dir.join(MANIFEST), list);
        made.iter().for_each(|p| say(format!("placed {}", p.display())));
        let status = match (st, failed) {
            (Status::Exited(0), 0) => Status::Exited(0),
            (Status::Exited(0), n) => Status::Failed(format!("{n} program(s) did not build")),
            (other, _) => other,
        };
        let _ = tx.send(Event::Done(id, status));
        wake();
    });
}

/// Remove every shortcut listed in the manifest.
pub fn remove(id: usize, user_dir: PathBuf, tx: Sender<Event>, wake: impl Fn() + Send + Clone + 'static) {
    std::thread::spawn(move || {
        let old = placed(&user_dir);
        let mut gone = 0;
        for p in &old {
            if std::fs::remove_file(p).is_ok() {
                gone += 1;
                let _ = tx.send(Event::Line(id, format!("removed {}", p.display())));
            }
        }
        let _ = std::fs::remove_file(user_dir.join(MANIFEST));
        let _ = tx.send(Event::Line(id, format!("{gone} shortcut(s) removed")));
        let _ = tx.send(Event::Done(id, Status::Exited(0)));
        wake();
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::mpsc::channel;

    fn root() -> PathBuf {
        crate::registry::find_root(Path::new(env!("CARGO_MANIFEST_DIR"))).unwrap()
    }

    #[test]
    fn json_str_reads_values() {
        let t = "{\n  \"id\": \"X\",\n  \"name\" : \"Generic Company Journal\",\n  \"version\": \"0.2.0\"\n}";
        assert_eq!(json_str(t, "name").as_deref(), Some("Generic Company Journal"));
        assert_eq!(json_str(t, "version").as_deref(), Some("0.2.0"));
        assert_eq!(json_str(t, "missing"), None);
    }

    #[test]
    fn every_program_has_setup_icon_and_target() {
        let (programs, _) = registry::load(&crate::config::parse(include_str!("../config/programs.ini")));
        for r in &programs {
            let sc = shortcut(&root(), r).unwrap();
            assert!(sc.label.starts_with("Generic Company "), "{}", sc.label);
            assert!(sc.label.chars().last().unwrap().is_ascii_digit(), "{}", sc.label);
        }
    }

    #[test]
    fn script_places_and_replaces_in_a_folder() {
        let dir = std::env::temp_dir().join(format!("gc-console-desk-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let stale = dir.join("Generic Company Journal 0.1.0.lnk");
        std::fs::write(&stale, "old").unwrap();
        let folder = root().join("content_management_system");
        let set = vec![Shortcut {
            label: "Generic Company Journal 0.2.0".into(),
            icon: folder.join("icon").join("app.ico"),
            target: TargetPath::File(folder.join("main.go")),
            folder,
        }];
        let (tx, _rx) = channel();
        let (st, made) = powershell(0, &script(&set, &[stale.clone()], Some(&dir)), &tx, &|| {});
        assert_eq!(st, Status::Exited(0));
        assert!(!stale.exists());
        assert_eq!(made.len(), 2);
        assert!(dir.join("Generic Company Journal 0.2.0.lnk").is_file());
        assert!(dir.join("Generic Company Journal source.lnk").is_file());
        std::fs::remove_dir_all(&dir).unwrap();
    }
}

// ==== stamp v1 | author=kjFriday | hmac-sha256=5a33af3653fc1f91762d47c522856e2223e9ba7297c27c0c11bcad89972f046b ====
