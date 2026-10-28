// ==== Generic Company Inc. portfolio ====================================
// Project: portfolio | File: dev_console/src/registry.rs
// About: The portfolio's programs and the commands that build, test and run each one.
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
// ========================================================================

//! The portfolio's programs and the commands that build, test and run each one.

use std::path::{Path, PathBuf};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Lang {
    Python,
    Go,
    Rust,
}

impl Lang {
    pub fn label(self) -> &'static str {
        match self {
            Lang::Python => "Python",
            Lang::Go => "Go",
            Lang::Rust => "Rust",
        }
    }
}

pub struct Project {
    pub name: &'static str,
    pub dir: &'static str,
    pub lang: Lang,
    /// Program and arguments that start the app; flags such as `--version` are appended.
    pub launch: &'static [&'static str],
    /// Test command, run in `dir`.
    pub test: &'static [&'static str],
}

pub const PROJECTS: &[Project] = &[
    Project {
        name: "CRUD Hub",
        dir: "create_read_update_delete_simple_io_data_base",
        lang: Lang::Python,
        launch: &["python", "main.py"],
        test: &["python", "-m", "unittest", "discover", "-p", "test_*.py"],
    },
    Project {
        name: "Doc Pipeline",
        dir: "document_mover_and_changer",
        lang: Lang::Python,
        launch: &["python", "-m", "docpipe"],
        test: &["python", "-m", "unittest", "discover", "-s", "tests"],
    },
    Project {
        name: "Journal",
        dir: "content_management_system",
        lang: Lang::Go,
        launch: &["go", "run", "."],
        test: &["go", "test", "./..."],
    },
    Project {
        name: "Notify Hub",
        dir: "notification_and_message_hub",
        lang: Lang::Go,
        launch: &["go", "run", "./cmd/notify"],
        test: &["go", "test", "./..."],
    },
    Project {
        name: "Ticket Tracker",
        dir: "simple_ticket_tracker",
        lang: Lang::Rust,
        launch: &["cargo", "run", "--release", "--features", "desktop", "--"],
        test: &["cargo", "test"],
    },
    Project {
        name: "Data Dash",
        dir: "data_dash",
        lang: Lang::Rust,
        launch: &["cargo", "run", "--release", "--features", "desktop", "--"],
        test: &["cargo", "test"],
    },
    Project {
        name: "Wizard Maker",
        dir: "install_wizard_maker",
        lang: Lang::Go,
        launch: &["go", "run", "."],
        test: &["go", "test", "./..."],
    },
];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Action {
    Build,
    Test,
    Run,
    Version,
    Smoke,
}

impl Action {
    pub const ALL: [Action; 5] = [Action::Build, Action::Test, Action::Run, Action::Version, Action::Smoke];

    pub fn label(self) -> &'static str {
        match self {
            Action::Build => "Build",
            Action::Test => "Test",
            Action::Run => "Run",
            Action::Version => "Version",
            Action::Smoke => "Smoke",
        }
    }
}

#[derive(Debug, PartialEq, Eq)]
pub struct Cmd {
    pub program: String,
    pub args: Vec<String>,
    pub cwd: PathBuf,
}

/// The command for `action` on `p`, or None when it does not apply (building a Python program).
/// `smoke` is the report file passed to `--smoke`.
pub fn command(p: &Project, action: Action, root: &Path, smoke: &Path) -> Option<Cmd> {
    let parts: Vec<String> = match action {
        Action::Build => match p.lang {
            Lang::Python => return None,
            Lang::Go => vec!["go".into(), "build".into(), "./...".into()],
            Lang::Rust => ["cargo", "build", "--release", "--features", "desktop"].map(String::from).to_vec(),
        },
        Action::Test => p.test.iter().map(|s| s.to_string()).collect(),
        Action::Run => p.launch.iter().map(|s| s.to_string()).collect(),
        Action::Version => with(p.launch, &["--version"]),
        Action::Smoke => with(p.launch, &["--smoke", &smoke.to_string_lossy()]),
    };
    let (program, args) = parts.split_first()?;
    Some(Cmd { program: program.clone(), args: args.to_vec(), cwd: root.join(p.dir) })
}

fn with(base: &[&str], extra: &[&str]) -> Vec<String> {
    base.iter().chain(extra).map(|s| s.to_string()).collect()
}

/// The portfolio root: the first folder at or above `start` that holds RULES.md.
pub fn find_root(start: &Path) -> Option<PathBuf> {
    start.ancestors().find(|d| d.join("RULES.md").is_file()).map(Path::to_path_buf)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn by_name(n: &str) -> &'static Project {
        PROJECTS.iter().find(|p| p.name == n).unwrap()
    }

    #[test]
    fn python_has_no_build() {
        assert!(command(by_name("CRUD Hub"), Action::Build, Path::new("R"), Path::new("s")).is_none());
    }

    #[test]
    fn version_appends_flag_after_launch() {
        let c = command(by_name("Data Dash"), Action::Version, Path::new("R"), Path::new("s")).unwrap();
        assert_eq!(c.program, "cargo");
        assert_eq!(c.args.last().unwrap(), "--version");
        assert_eq!(c.args[c.args.len() - 2], "--");
        assert_eq!(c.cwd, Path::new("R").join("data_dash"));
    }

    #[test]
    fn smoke_passes_report_path() {
        let c = command(by_name("Notify Hub"), Action::Smoke, Path::new("R"), Path::new("rep.json")).unwrap();
        assert_eq!(&c.args[c.args.len() - 2..], ["--smoke", "rep.json"]);
    }

    #[test]
    fn every_project_has_test_and_run() {
        for p in PROJECTS {
            for a in [Action::Test, Action::Run] {
                assert!(command(p, a, Path::new("R"), Path::new("s")).is_some(), "{} {:?}", p.name, a);
            }
        }
    }

    #[test]
    fn find_root_walks_up() {
        let dir = std::env::temp_dir().join(format!("gc-console-root-{}", std::process::id()));
        let deep = dir.join("a").join("b");
        std::fs::create_dir_all(&deep).unwrap();
        std::fs::write(dir.join("RULES.md"), "x").unwrap();
        assert_eq!(find_root(&deep).as_deref(), Some(dir.as_path()));
        std::fs::remove_dir_all(&dir).unwrap();
    }
}

// ==== stamp v1 | author=kjFriday | hmac-sha256=c2ba96ad9a56f21f5ce6c30ec665d5889d4158df801060571f530cf5d6af3a3a ====
