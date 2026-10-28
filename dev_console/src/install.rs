// ==== Generic Company Inc. portfolio ====================================
// Project: portfolio | File: dev_console/src/install.rs
// About: Per-user install and uninstall: copy the program and its config/ folder, add a Start menu...
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
// ========================================================================

//! Per-user install and uninstall: copy the program and its config/ folder, add a Start menu shortcut and an
//! Apps & features entry. `--root DIR` does all of it inside DIR (the registry entry becomes a file there).

use std::path::{Path, PathBuf};

pub const NAME: &str = "Generic Company Dev Console";
pub const GROUP: &str = "Generic Company Inc";
pub const EXE: &str = "generic-company-console.exe";

pub struct Plan {
    pub dir: PathBuf,
    pub start_menu: PathBuf,
    /// Some(file) in a sandbox: the Apps & features entry is written there instead of the registry.
    pub registry_file: Option<PathBuf>,
}

/// Where everything goes. `env` reads environment variables (so tests can supply their own).
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
        start_menu: Path::new(&roaming).join("Microsoft").join("Windows").join("Start Menu").join("Programs").join(GROUP),
        registry_file: None,
    })
}

fn ps_quote(s: &str) -> String {
    format!("'{}'", s.replace('\'', "''"))
}

fn powershell(script: &str) -> Result<(), String> {
    let mut c = std::process::Command::new("powershell");
    c.args(["-NoProfile", "-NonInteractive", "-Command", script]);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        c.creation_flags(0x0800_0000);
    }
    let out = c.output().map_err(|e| e.to_string())?;
    if out.status.success() {
        Ok(())
    } else {
        Err(String::from_utf8_lossy(&out.stderr).trim().to_string())
    }
}

fn reg_key() -> String {
    format!(r"HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{}", crate::config::APP_ID)
}

/// Copy `exe` and the `config` folder beside it (if any) into place and register the program.
pub fn install(p: &Plan, exe: &Path, config_src: Option<&Path>, version: &str) -> Result<(), String> {
    let io = |e: std::io::Error| e.to_string();
    std::fs::create_dir_all(&p.dir).map_err(io)?;
    let target = p.dir.join(EXE);
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
pub fn uninstall(p: &Plan, running: &Path) -> Result<bool, String> {
    let _ = std::fs::remove_file(p.start_menu.join(format!("{NAME}.lnk")));
    if std::fs::read_dir(&p.start_menu).map(|mut d| d.next().is_none()).unwrap_or(false) {
        let _ = std::fs::remove_dir(&p.start_menu);
    }
    match &p.registry_file {
        Some(f) => {
            let _ = std::fs::remove_file(f);
        }
        None => powershell(&format!("Remove-Item -Path {} -Recurse -ErrorAction SilentlyContinue", ps_quote(&reg_key())))?,
    }
    if !p.dir.exists() {
        return Ok(false);
    }
    if running.starts_with(&p.dir) {
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

fn same(a: &Path, b: &Path) -> bool {
    match (a.canonicalize(), b.canonicalize()) {
        (Ok(x), Ok(y)) => x == y,
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn real_plan_uses_per_user_folders() {
        let env = |k: &str| match k {
            "LOCALAPPDATA" => Some(r"C:\U\Local".to_string()),
            "APPDATA" => Some(r"C:\U\Roaming".to_string()),
            _ => None,
        };
        let p = plan(&env, None).unwrap();
        assert!(p.dir.ends_with(r"Programs\Generic Company Inc\Generic Company Dev Console"));
        assert!(p.start_menu.starts_with(r"C:\U\Roaming\Microsoft\Windows\Start Menu\Programs"));
        assert!(p.registry_file.is_none());
        assert!(plan(&|_| None, None).is_err());
    }

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

// ==== stamp v1 | author=kjFriday | hmac-sha256=5e2714d106d039f8a2646434605bbdf3bbbc0d4aa1be55ab45da45e0532a4323 ====
