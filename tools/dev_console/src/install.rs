// ==== Generic Company Inc. portfolio ====================================
// Project: dev_console | File: src/install.rs
// About: Per-user install and uninstall: program folder, Start menu shortcut and uninstall entry.
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
// ========================================================================

//! Per-user install and uninstall: program folder, Start menu shortcut and uninstall entry.
//!
//! main.rs calls this for `--install` and `--uninstall`. Install copies the program and its config/ folder,
//! adds a Start menu shortcut and an Apps & features entry. `--root DIR` does all of it inside DIR (the
//! registry entry becomes a file there), which is how the tests run it without touching the real machine.
//!
//! Everything is per user, so no administrator rights are needed:
//! - the program goes to `%LOCALAPPDATA%\Programs\Generic Company Inc\Generic Company Dev Console`;
//! - the shortcut goes to the user's own Start menu folder under `%APPDATA%`;
//! - the uninstall entry goes under `HKEY_CURRENT_USER`, where Apps & features also looks.
//!
//! Flow:
//! 1. `plan` works out the three places from the environment (or the sandbox root).
//! 2. `install` copies the files, then writes the shortcut and the uninstall entry in one PowerShell script.
//! 3. `uninstall` (started from Apps & features through the entry's UninstallString) removes all three;
//!    when it runs from inside the program folder, a delayed PowerShell deletes the folder after it exits.
//!
//! Defines `Plan`. Start reading at `install`.

use std::path::{Path, PathBuf};

use crate::win::ps_quote;

/// The program's display name: the install folder, the shortcut and the Apps & features entry use it.
pub const NAME: &str = "Generic Company Dev Console";
/// The company folder the program folder and the Start menu shortcut sit in.
pub const GROUP: &str = "Generic Company Inc";
/// The file name of the installed program.
pub const EXE: &str = "generic-company-console.exe";

/// Where an install puts things, worked out once by `plan` and used by both install and uninstall.
pub struct Plan {
    /// The program folder: the exe and its config/ folder.
    pub dir: PathBuf,
    /// The Start menu folder (`GROUP`) that holds the shortcut.
    pub start_menu: PathBuf,
    /// Some(file) in a sandbox: the Apps & features entry is written there instead of the registry.
    pub registry_file: Option<PathBuf>,
}

/// Where everything goes. `env` reads environment variables (so tests can supply their own).
///
/// With `root` (the `--root DIR` sandbox) every place is inside it, the shortcut and registry entry
/// become plain files, and no environment variable is read. Otherwise Err names a missing LOCALAPPDATA or
/// APPDATA.
pub fn plan(env: &dyn Fn(&str) -> Option<String>, root: Option<&Path>) -> Result<Plan, String> {
    if let Some(r) = root {
        return Ok(Plan {
            dir: r.join("Programs").join(GROUP).join(NAME),
            start_menu: r.join("Start Menu").join(GROUP),
            registry_file: Some(r.join("registry").join(format!("{}.ini", crate::config::APP_ID))),
        });
    }
    let local = env("LOCALAPPDATA").ok_or("LOCALAPPDATA is not set")?;
    let roaming = env("APPDATA").ok_or("APPDATA is not set")?;
    Ok(Plan {
        dir: Path::new(&local).join("Programs").join(GROUP).join(NAME),
        start_menu: Path::new(&roaming)
            .join("Microsoft")
            .join("Windows")
            .join("Start Menu")
            .join("Programs")
            .join(GROUP),
        registry_file: None,
    })
}

/// Run `script` with `powershell -Command` and wait; Err holds what it wrote on stderr.
///
/// `-NoProfile` keeps the user's profile script out of it (faster, and nothing in it can change the result);
/// `-NonInteractive` makes any prompt fail instead of waiting forever for an answer no one can give.
fn powershell(script: &str) -> Result<(), String> {
    let mut c = std::process::Command::new("powershell");
    c.args(["-NoProfile", "-NonInteractive", "-Command", script]);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        c.creation_flags(crate::win::CREATE_NO_WINDOW);
    }
    let out = c.output().map_err(|e| e.to_string())?;
    if out.status.success() {
        Ok(())
    } else {
        Err(String::from_utf8_lossy(&out.stderr).trim().to_string())
    }
}

/// The program's uninstall key, in PowerShell's registry drive form (`HKCU:\...`).
///
/// Apps & features lists every subkey of `...\CurrentVersion\Uninstall` in HKEY_LOCAL_MACHINE and
/// HKEY_CURRENT_USER; the subkey name (here the config APP_ID) only has to be unique.
fn reg_key() -> String {
    format!(
        r"HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{}",
        crate::config::APP_ID
    )
}

/// Copy `exe` and the `config` folder beside it (if any) into place and register the program.
///
/// `config_src` is the config folder to copy (main.rs picks the one beside the exe, else the source tree's);
/// `version` is shown in Apps & features. Running it again over an existing install updates it in place.
///
/// Steps:
/// 1. Copy the exe into `p.dir`, unless it is already the installed copy.
/// 2. Copy the files (not subfolders) of `config_src` into `p.dir\config`, overwriting older ones.
/// 3. Sandbox: write the shortcut and the uninstall entry as text files.
/// 4. Otherwise one PowerShell script makes the `.lnk` through the WScript.Shell COM object and writes the
///    uninstall key's values.
pub fn install(p: &Plan, exe: &Path, config_src: Option<&Path>, version: &str) -> Result<(), String> {
    let io = |e: std::io::Error| e.to_string();
    std::fs::create_dir_all(&p.dir).map_err(io)?;
    let target = p.dir.join(EXE);
    // the installed exe run with --install again would otherwise copy itself onto itself, which fails while
    // it is running
    if !same(exe, &target) {
        std::fs::copy(exe, &target).map_err(io)?;
    }
    if let Some(src) = config_src.filter(|s| s.is_dir()) {
        let dst = p.dir.join("config");
        std::fs::create_dir_all(&dst).map_err(io)?;
        for e in std::fs::read_dir(src).map_err(io)?.flatten() {
            if e.path().is_file() {
                std::fs::copy(e.path(), dst.join(e.file_name())).map_err(io)?;
            }
        }
    }
    std::fs::create_dir_all(&p.start_menu).map_err(io)?;
    let lnk = p.start_menu.join(format!("{NAME}.lnk"));
    // the command Apps & features runs for Uninstall: the installed exe, path quoted for its spaces
    let uninstall = format!("\"{}\" --uninstall", target.display());
    match &p.registry_file {
        Some(file) => {
            // Sandbox: a plain-text stand-in for the shortcut and the registry entry.
            std::fs::write(&lnk, target.display().to_string()).map_err(io)?;
            std::fs::create_dir_all(file.parent().unwrap()).map_err(io)?;
            let entry = format!(
                "DisplayName = {NAME}\nDisplayVersion = {version}\nPublisher = Generic Company Inc. (fictional)\nInstallLocation = {}\nUninstallString = {uninstall}\n",
                p.dir.display()
            );
            std::fs::write(file, entry).map_err(io)?;
        }
        None => {
            // The script, in order:
            // - WScript.Shell's CreateShortcut opens (or makes) a .lnk; setting TargetPath and WorkingDirectory and
            //   calling Save writes it. It is the COM shell-link object Windows Script Host offers to scripts.
            // - New-Item -Force makes the uninstall key (or keeps it); Set-ItemProperty writes the string values
            //   Apps & features reads: the name, version, publisher, icon, folder and the command its Uninstall
            //   button runs.
            // - NoModify and NoRepair (DWORD 1) hide the Modify and Repair buttons, which this program lacks.
            let script = format!(
                "$s=(New-Object -ComObject WScript.Shell).CreateShortcut({lnk}); $s.TargetPath={t}; $s.WorkingDirectory={d}; $s.Save();\
                 $k={k}; New-Item -Path $k -Force | Out-Null;\
                 Set-ItemProperty $k DisplayName {n}; Set-ItemProperty $k DisplayVersion {v};\
                 Set-ItemProperty $k Publisher 'Generic Company Inc. (fictional)'; Set-ItemProperty $k DisplayIcon {t};\
                 Set-ItemProperty $k InstallLocation {d}; Set-ItemProperty $k UninstallString {u};\
                 Set-ItemProperty $k NoModify 1 -Type DWord; Set-ItemProperty $k NoRepair 1 -Type DWord",
                lnk = ps_quote(&lnk.to_string_lossy()),
                t = ps_quote(&target.to_string_lossy()),
                d = ps_quote(&p.dir.to_string_lossy()),
                k = ps_quote(&reg_key()),
                n = ps_quote(NAME),
                v = ps_quote(version),
                u = ps_quote(&uninstall),
            );
            powershell(&script)?;
        }
    }
    Ok(())
}

/// Remove the shortcut, the Apps & features entry and the program folder. The user's settings under
/// %LOCALAPPDATA%\Generic Company Inc are kept. When the running exe is inside the folder, the folder is
/// deleted a moment after this process exits; returns true in that case.
///
/// `running` is the path of the exe doing the uninstall. Pieces that are already gone are not errors, so
/// running it twice is safe.
///
/// Steps:
/// 1. Delete the shortcut, then the GROUP Start menu folder if that left it empty (other company
///    programs may keep shortcuts there).
/// 2. Delete the uninstall entry (the sandbox file, or the registry key).
/// 3. Delete the program folder: at once, or, when the running exe is inside it (Windows cannot delete a
///    running exe), through a hidden PowerShell that waits 2 s for this process to exit first.
pub fn uninstall(p: &Plan, running: &Path) -> Result<bool, String> {
    let _ = std::fs::remove_file(p.start_menu.join(format!("{NAME}.lnk")));
    if std::fs::read_dir(&p.start_menu)
        .map(|mut d| d.next().is_none())
        .unwrap_or(false)
    {
        let _ = std::fs::remove_dir(&p.start_menu);
    }
    match &p.registry_file {
        Some(f) => {
            let _ = std::fs::remove_file(f);
        }
        None => powershell(&format!(
            "Remove-Item -Path {} -Recurse -ErrorAction SilentlyContinue",
            ps_quote(&reg_key())
        ))?,
    }
    if !p.dir.exists() {
        return Ok(false);
    }
    if running.starts_with(&p.dir) {
        // spawned, not waited for: the script must outlive this process. Known limitation: if this process is
        // still running after the 2 s, the delete fails and the folder stays.
        let script = format!(
            "Start-Sleep -Seconds 2; Remove-Item -LiteralPath {} -Recurse -Force",
            ps_quote(&p.dir.to_string_lossy())
        );
        let mut c = std::process::Command::new("powershell");
        c.args(["-NoProfile", "-WindowStyle", "Hidden", "-Command", &script]);
        c.spawn().map_err(|e| e.to_string())?;
        return Ok(true);
    }
    std::fs::remove_dir_all(&p.dir).map_err(|e| e.to_string())?;
    Ok(false)
}

/// Whether `a` and `b` name the same existing file; false when either does not exist.
///
/// Compares canonical paths, so `.\x.exe`, a different letter case or a `..` step do not hide a match.
fn same(a: &Path, b: &Path) -> bool {
    match (a.canonicalize(), b.canonicalize()) {
        (Ok(x), Ok(y)) => x == y,
        _ => false,
    }
}

/// Unit tests: the real plan from fake environment variables, and a full install and uninstall in a sandbox.
#[cfg(test)]
mod tests {
    use super::*;

    // LOCALAPPDATA and APPDATA decide the folders, no registry file is used, and a missing variable is an error.
    #[test]
    fn real_plan_uses_per_user_folders() {
        let env = |k: &str| match k {
            "LOCALAPPDATA" => Some(r"C:\U\Local".to_string()),
            "APPDATA" => Some(r"C:\U\Roaming".to_string()),
            _ => None,
        };
        let p = plan(&env, None).unwrap();
        assert!(
            p.dir
                .ends_with(r"Programs\Generic Company Inc\Generic Company Dev Console")
        );
        assert!(
            p.start_menu
                .starts_with(r"C:\U\Roaming\Microsoft\Windows\Start Menu\Programs")
        );
        assert!(p.registry_file.is_none());
        assert!(plan(&|_| None, None).is_err());
    }

    // Install into a temp sandbox writes the exe, config, shortcut and entry (with the version); uninstall run
    // from outside the folder removes them all at once and returns false.
    #[test]
    fn sandbox_round_trip() {
        let root = std::env::temp_dir().join(format!("gc-console-install-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        let src = root.join("build");
        std::fs::create_dir_all(src.join("config")).unwrap();
        std::fs::write(src.join("fake.exe"), "exe").unwrap();
        std::fs::write(src.join("config").join("controls.ini"), "[controls]\n").unwrap();
        let sandbox = root.join("box");
        let p = plan(&|_| None, Some(&sandbox)).unwrap();
        install(&p, &src.join("fake.exe"), Some(&src.join("config")), "9.9.9").unwrap();
        assert!(p.dir.join(EXE).is_file());
        assert!(p.dir.join("config").join("controls.ini").is_file());
        assert!(p.start_menu.join(format!("{NAME}.lnk")).is_file());
        let entry = std::fs::read_to_string(p.registry_file.as_ref().unwrap()).unwrap();
        assert!(entry.contains("DisplayVersion = 9.9.9"));
        assert!(!uninstall(&p, &src.join("fake.exe")).unwrap());
        assert!(!p.dir.exists());
        assert!(!p.start_menu.exists());
        assert!(!p.registry_file.as_ref().unwrap().exists());
        std::fs::remove_dir_all(&root).unwrap();
    }
}

// ==== stamp v1 | author=kjFriday | hmac-sha256=7f5a258a75aecde34d27e94d776fa6010e8f36d4e2f7d563af84b44dc72ae8e8 ====
