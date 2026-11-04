// ==== Generic Company Inc. portfolio ====================================
// Project: dev_console | File: src/desktop.rs
// About: Desktop shortcuts: build each program from source, then put a versioned shortcut to that...
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
// ========================================================================

//! Desktop shortcuts: build each program, then place shortcuts to the build and its source.
//!
//! Each program gets a versioned shortcut to its build (with the program's own icon) and a shortcut to its
//! source folder on the desktop. A list of what was placed (the manifest) is kept in the user's config
//! folder, so the next run replaces old versions and Remove takes them all away, without touching anything
//! else on the desktop. app.rs calls `make` and `remove` from the sidebar's buttons and the
//! desktop_shortcuts key; each runs on its own thread as one job, sending its output like any other job.
//!
//! `make` in order:
//! 1. Per program, read its name and version from setup.json and work out the shortcut target from
//!    desktop_run (`shortcut`).
//! 2. Run each desktop_build step in the program's folder; a failed step, or a target file still missing
//!    afterwards, leaves that program out.
//! 3. Write one PowerShell script (`script`) that deletes the shortcuts in the old manifest and creates the
//!    new ones through the WScript.Shell COM object, which is how Windows scripts make .lnk files.
//! 4. Run it (`powershell`), and write the paths it reports as the new manifest.
//! 5. End the job: success only when every program built and the script succeeded.
//!
//! Defines `Shortcut` and `TargetPath`.

use std::path::{Path, PathBuf};
use std::sync::mpsc::Sender;

use crate::jobs::{self, Event, Status};
use crate::registry::{self, Cmd, Program};
use crate::win::ps_quote;

/// The list of shortcuts placed last time, one full path per line.
pub const MANIFEST: &str = "desktop-shortcuts.txt";

/// The string value of `"key": "..."` in a small JSON file (setup.json); enough for name and version.
///
/// A plain text search instead of a JSON parser keeps the crate free of a JSON dependency. It takes the first
/// `"key"` anywhere in the text, allows spaces around the colon, and stops at the next quote, so it does not
/// handle escaped quotes or nested objects with the same key. None when the key is missing or its value is
/// not a string.
pub fn json_str(text: &str, key: &str) -> Option<String> {
    let at = text.find(&format!("\"{key}\""))? + key.len() + 2;
    let rest = text[at..]
        .trim_start()
        .strip_prefix(':')?
        .trim_start()
        .strip_prefix('"')?;
    let end = rest.find('"')?;
    Some(rest[..end].to_string())
}

/// One program's pair of shortcuts.
#[derive(Debug, PartialEq)]
pub struct Shortcut {
    /// "Generic Company Journal 0.2.0"
    pub label: String,
    /// The program's folder: the source shortcut's target and both shortcuts' working folder.
    pub folder: PathBuf,
    /// icon/app.ico in the program's folder; used only if the file exists.
    pub icon: PathBuf,
    /// What the program shortcut starts.
    pub target: TargetPath,
}

/// What a program shortcut starts: a built file, or pythonw with arguments.
#[derive(Debug, PartialEq)]
pub enum TargetPath {
    /// A file in the program's folder, such as the built exe.
    File(PathBuf),
    /// `pythonw` with these arguments; pythonw runs a Python GUI without opening a console window.
    Pythonw(Vec<String>),
}

/// Name and version from the project's setup.json, and where its shortcut points (`desktop_run`).
///
/// `root` is the portfolio folder; `p` the program. Err names the program and the problem: no setup.json, no
/// name or version in it, or an empty desktop_run.
///
/// Steps:
/// 1. Read setup.json in the program's folder and take its name and version; the label is both.
/// 2. Split desktop_run into words. When the first is pythonw (in any case), the target is pythonw with the
///    rest as arguments; otherwise the whole value (without quotes) is a file path in the program's folder.
/// 3. The icon is the program's icon/app.ico.
pub fn shortcut(root: &Path, p: &Program) -> Result<Shortcut, String> {
    let folder = root.join(&p.dir);
    let setup =
        std::fs::read_to_string(folder.join("setup.json")).map_err(|e| format!("{}: setup.json: {e}", p.dir))?;
    let name = json_str(&setup, "name").ok_or_else(|| format!("{}: setup.json has no name", p.dir))?;
    let version = json_str(&setup, "version").ok_or_else(|| format!("{}: setup.json has no version", p.dir))?;
    let words = registry::split_args(&p.desktop_run);
    let target = match words.split_first() {
        None => return Err(format!("{}: desktop_run is empty", p.name)),
        Some((first, rest)) if first.eq_ignore_ascii_case("pythonw") => TargetPath::Pythonw(rest.to_vec()),
        Some(_) => TargetPath::File(folder.join(p.desktop_run.trim().trim_matches('"'))),
    };
    Ok(Shortcut {
        label: format!("{name} {version}"),
        icon: folder.join("icon").join("app.ico"),
        folder,
        target,
    })
}

/// A path as a PowerShell single-quoted string.
///
/// Single quotes make PowerShell take the text literally (no `$` expansion), which matters for folder names
/// with `$` or backticks in them; win.rs doubles any quote inside.
fn qp(p: &Path) -> String {
    ps_quote(&p.to_string_lossy())
}

/// PowerShell that removes `old` shortcuts and places `set` on the desktop (or in `desktop`, for tests),
/// printing the full path of every shortcut it made.
///
/// Pure: builds text and runs nothing, so tests can read it. `old` comes from the manifest.
///
/// Steps:
/// 1. `$ErrorActionPreference='Stop'` turns any failure into a script error (a non-zero exit), and
///    `$w` is the WScript.Shell COM object, which creates .lnk files.
/// 2. `$d` is the desktop from `[Environment]::GetFolderPath('Desktop')`, which follows a desktop moved to
///    OneDrive or another drive, or the given folder for tests.
/// 3. Delete each old shortcut with `-LiteralPath` (so `[` in a name is not a wildcard), ignoring ones the
///    user already deleted.
/// 4. Per program, two shortcuts through `place`: CreateShortcut, set TargetPath, Arguments,
///    WorkingDirectory, the icon (`file,0`, the first icon in the file) when there is one, and Description,
///    then Save and print the path. A pythonw target is resolved with `Get-Command` when the script runs, so
///    the shortcut holds pythonw's full path.
/// 5. The source shortcut drops the version from the label ("Generic Company Journal source.lnk"), so it
///    keeps the same name across versions.
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
            ps_quote(file),
            ps_quote(args),
            qp(cwd),
            ps_quote(what)
        )
    };
    for sc in set {
        // A program without icon/app.ico keeps the default icon of its target.
        let icon = if sc.icon.is_file() {
            format!("$k.IconLocation={};", ps_quote(&format!("{},0", sc.icon.display())))
        } else {
            String::new()
        };
        let (target, args) = match &sc.target {
            TargetPath::File(p) => (qp(p), String::new()),
            TargetPath::Pythonw(a) => ("(Get-Command 'pythonw').Source".to_string(), a.join(" ")),
        };
        s += &place(
            &format!("{}.lnk", sc.label),
            &target,
            &args,
            &sc.folder,
            &icon,
            &format!("{} (built from source)", sc.label),
        );
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
///
/// Empty when there is no manifest yet; blank lines are skipped.
pub fn placed(user_dir: &Path) -> Vec<PathBuf> {
    std::fs::read_to_string(user_dir.join(MANIFEST))
        .map(|t| t.lines().filter(|l| !l.trim().is_empty()).map(PathBuf::from).collect())
        .unwrap_or_default()
}

/// Run `script` in PowerShell as part of job `id` and return its status and the paths it printed.
///
/// `tx` and `wake` carry the run's events like any job's. Side effects: whatever the script does, plus a
/// temporary file that is removed afterwards.
///
/// Steps:
/// 1. Wrap the script in `& { ... }` and pipe its output into a temporary file with `Set-Content`. The paths
///    go to a file rather than being read from the log because the log also carries errors and any other
///    output, and because Windows PowerShell's console output uses the OEM code page, which mangles names
///    outside it; the file is written as UTF-8.
/// 2. Start `powershell -NoProfile -NonInteractive -Command`: no profile, so the user's profile script cannot
///    change the result or slow it, and non-interactive, so a prompt fails instead of hanging the job.
/// 3. Run it through jobs::run on this thread, so its lines stream into the job's log.
/// 4. Read the file back, dropping the byte order mark that Windows PowerShell's `-Encoding utf8` writes at
///    the start, and keep each non-empty line as a path. Delete the file.
fn powershell(
    id: usize,
    script: &str,
    tx: &Sender<Event>,
    wake: &(impl Fn() + Send + Clone + 'static),
) -> (Status, Vec<PathBuf>) {
    let out = std::env::temp_dir().join(format!("gc-console-desktop-{}-{id}.txt", std::process::id()));
    let full = format!(
        "& {{ {script} }} | Set-Content -Encoding utf8 -LiteralPath {}",
        qp(&out)
    );
    let cmd = Cmd {
        program: "powershell".into(),
        args: ["-NoProfile", "-NonInteractive", "-Command", &full]
            .map(String::from)
            .to_vec(),
        cwd: std::env::temp_dir(),
    };
    let status = jobs::run(id, &cmd, tx, wake);
    let made = std::fs::read_to_string(&out)
        .map(|t| {
            t.trim_start_matches('\u{feff}')
                .lines()
                .filter(|l| !l.is_empty())
                .map(PathBuf::from)
                .collect()
        })
        .unwrap_or_default();
    let _ = std::fs::remove_file(out);
    (status, made)
}

/// Build every program, then place shortcuts for the ones that built. Runs on its own thread as job `id`.
///
/// `programs` and the folders are owned copies, since the thread outlives the call. `user_dir` holds the
/// manifest; `desktop` is None for the real desktop or a folder for tests. Returns at once; the job ends
/// with one `Event::Done`.
///
/// Steps:
/// 1. Per program: get its shortcut (a problem skips it as failed), then run each desktop_build step in its
///    folder, logging each command; the first failed step stops that program's build.
/// 2. A file target must exist after the build, or that program gets no shortcut.
/// 3. Run the script with the old manifest, so the shortcuts placed last time (older versions included)
///    are replaced, not left beside the new ones.
/// 4. Write the new manifest (creating the folder) and log each placed shortcut.
/// 5. The job's status: Exited(0) when everything worked; Failed naming how many programs did not build when
///    only builds failed; otherwise the script's own status.
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
                let Some(cmd) = Cmd::new(step, sc.folder.clone()) else {
                    continue;
                };
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
        say(format!(
            "placing {} program shortcuts and {} folder shortcuts",
            set.len(),
            set.len()
        ));
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
///
/// Runs on its own thread as job `id`. Only files in the manifest are deleted, so nothing else on the
/// desktop is touched. Shortcuts already gone are passed over silently; the manifest is deleted too, and the
/// job always ends as Exited(0) with a count of what it removed.
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

/// Tests for setup.json reading, every shipped program's shortcut, and the script on a temporary folder.
#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::mpsc::channel;

    /// The portfolio root, found upward from this crate's folder.
    fn root() -> PathBuf {
        crate::registry::find_root(Path::new(env!("CARGO_MANIFEST_DIR"))).unwrap()
    }

    /// Values are found with spaces around the colon; a missing key gives None.
    #[test]
    fn json_str_reads_values() {
        let t = "{\n  \"id\": \"X\",\n  \"name\" : \"Generic Company Journal\",\n  \"version\": \"0.2.0\"\n}";
        assert_eq!(json_str(t, "name").as_deref(), Some("Generic Company Journal"));
        assert_eq!(json_str(t, "version").as_deref(), Some("0.2.0"));
        assert_eq!(json_str(t, "missing"), None);
    }

    /// Every program in the shipped programs.ini has a setup.json whose label starts with the company name
    /// and ends with a version.
    #[test]
    fn every_program_has_setup_icon_and_target() {
        let (programs, _) = registry::load(&crate::config::parse(include_str!("../config/programs.ini")));
        for r in &programs {
            let sc = shortcut(&root(), r).unwrap();
            assert!(sc.label.starts_with("Generic Company "), "{}", sc.label);
            assert!(sc.label.chars().last().unwrap().is_ascii_digit(), "{}", sc.label);
        }
    }

    /// Runs the real script in PowerShell on a temporary folder: the stale shortcut from the old manifest is
    /// deleted, and the program and source shortcuts are made and reported.
    #[test]
    fn script_places_and_replaces_in_a_folder() {
        let dir = std::env::temp_dir().join(format!("gc-console-desk-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let stale = dir.join("Generic Company Journal 0.1.0.lnk");
        std::fs::write(&stale, "old").unwrap();
        let folder = root().join("company").join("journal");
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

// ==== stamp v1 | author=kjFriday | hmac-sha256=4003a2f706229c2ff70042e45ee2741d628e9177e3eb276387cb8f6cde5714a6 ====
