// ==== Generic Company Inc. portfolio ====================================
// Project: portfolio | File: dev_console/src/registry.rs
// About: The portfolio's programs (from config/programs.ini) and the commands that build, test and...
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
// ========================================================================

//! The portfolio's programs (from config/programs.ini) and the commands that build, test and run each one.

use std::path::{Path, PathBuf};

use crate::config::Ini;

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

    fn parse(s: &str) -> Option<Lang> {
        match s.trim().to_lowercase().as_str() {
            "python" => Some(Lang::Python),
            "go" => Some(Lang::Go),
            "rust" => Some(Lang::Rust),
            _ => None,
        }
    }
}

/// The editable command fields, in the order the editor shows them: (key, label, help).
pub const FIELDS: [(&str, &str, &str); 5] = [
    ("launch", "Launch", "Starts the program. Run uses it as is; Version and Smoke add --version / --smoke FILE after it."),
    ("test", "Test", "Runs the program's tests (Test, Test all, live tests)."),
    ("build", "Build", "Builds the program (Build button). Leave empty when there is nothing to build."),
    ("desktop_build", "Desktop build", "Steps the Desktop shortcuts button runs before placing the shortcut, separated by &&."),
    ("desktop_run", "Desktop run", "What the desktop shortcut starts: an exe relative to the project folder, or \"pythonw <args>\"."),
];

#[derive(Clone, Debug, PartialEq)]
pub struct Program {
    /// Section name in programs.ini.
    pub key: String,
    pub name: String,
    pub dir: String,
    pub lang: Lang,
    pub launch: String,
    pub test: String,
    pub build: String,
    pub desktop_build: String,
    pub desktop_run: String,
    pub version_files: Vec<String>,
}

impl Program {
    pub fn field(&self, key: &str) -> &str {
        match key {
            "launch" => &self.launch,
            "test" => &self.test,
            "build" => &self.build,
            "desktop_build" => &self.desktop_build,
            "desktop_run" => &self.desktop_run,
            _ => "",
        }
    }

    pub fn field_mut(&mut self, key: &str) -> Option<&mut String> {
        match key {
            "launch" => Some(&mut self.launch),
            "test" => Some(&mut self.test),
            "build" => Some(&mut self.build),
            "desktop_build" => Some(&mut self.desktop_build),
            "desktop_run" => Some(&mut self.desktop_run),
            _ => None,
        }
    }
}

/// Programs in `[programs] order`, plus warnings for sections that are missing or incomplete.
pub fn load(ini: &Ini) -> (Vec<Program>, Vec<String>) {
    let mut out = vec![];
    let mut warnings = vec![];
    let order = ini.get("programs").and_then(|s| s.get("order")).cloned().unwrap_or_default();
    for key in order.split(',').map(str::trim).filter(|k| !k.is_empty()) {
        let Some(s) = ini.get(key) else {
            warnings.push(format!("programs.ini: no [{key}] section"));
            continue;
        };
        let get = |k: &str| s.get(k).cloned().unwrap_or_default();
        let Some(lang) = Lang::parse(&get("lang")) else {
            warnings.push(format!("programs.ini [{key}]: lang must be Python, Go or Rust"));
            continue;
        };
        if get("dir").is_empty() || get("launch").is_empty() {
            warnings.push(format!("programs.ini [{key}]: dir and launch are required"));
            continue;
        }
        out.push(Program {
            key: key.to_string(),
            name: if get("name").is_empty() { key.to_string() } else { get("name") },
            dir: get("dir"),
            lang,
            launch: get("launch"),
            test: get("test"),
            build: get("build"),
            desktop_build: get("desktop_build"),
            desktop_run: get("desktop_run"),
            version_files: get("version_files").split(',').map(|f| f.trim().to_string()).filter(|f| !f.is_empty()).collect(),
        });
    }
    (out, warnings)
}

/// programs.ini text for `programs`, with a short header.
pub fn render(programs: &[Program]) -> String {
    let mut s = String::from(
        "; Dev Console programs: one section per program, in the order of [programs] order.\n\
         ; Saved by the console's Versions & commands view; see dev_console/README.md for the keys.\n\
         ; Quote an argument that contains spaces with double quotes; separate desktop_build steps with &&.\n\n",
    );
    let order: Vec<&str> = programs.iter().map(|p| p.key.as_str()).collect();
    s += &format!("[programs]\norder = {}\n", order.join(", "));
    for p in programs {
        s += &format!("\n[{}]\nname = {}\ndir = {}\nlang = {}\n", p.key, p.name, p.dir, p.lang.label());
        for (k, _, _) in FIELDS {
            s += &format!("{k} = {}\n", p.field(k));
        }
        s += &format!("version_files = {}\n", p.version_files.join(", "));
    }
    s
}

/// Split a command line into words; double quotes group words and are removed.
pub fn split_args(s: &str) -> Vec<String> {
    let mut out = vec![];
    let mut cur = String::new();
    let (mut quoted, mut any) = (false, false);
    for ch in s.chars() {
        match ch {
            '"' => {
                quoted = !quoted;
                any = true;
            }
            c if c.is_whitespace() && !quoted => {
                if any {
                    out.push(std::mem::take(&mut cur));
                    any = false;
                }
            }
            c => {
                cur.push(c);
                any = true;
            }
        }
    }
    if any {
        out.push(cur);
    }
    out
}

/// `a && b` -> [[a...], [b...]]; empty steps are dropped.
pub fn steps(s: &str) -> Vec<Vec<String>> {
    s.split("&&").map(split_args).filter(|w| !w.is_empty()).collect()
}

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

    pub fn help(self) -> &'static str {
        match self {
            Action::Build => "Build the program with its build command (not needed for Python).",
            Action::Test => "Run the program's tests.",
            Action::Run => "Start the program from source.",
            Action::Version => "Start the program with --version and show what it prints.",
            Action::Smoke => "Open the program with --smoke: it opens its window, writes a JSON report and closes. The report is added to the log.",
        }
    }
}

#[derive(Debug, PartialEq, Eq)]
pub struct Cmd {
    pub program: String,
    pub args: Vec<String>,
    pub cwd: PathBuf,
}

impl Cmd {
    pub fn new(words: Vec<String>, cwd: PathBuf) -> Option<Cmd> {
        let (program, args) = words.split_first()?;
        Some(Cmd { program: program.clone(), args: args.to_vec(), cwd })
    }
}

/// The command for `action` on `p`, or None when it does not apply (an empty build command).
/// `smoke` is the report file passed to `--smoke`.
pub fn command(p: &Program, action: Action, root: &Path, smoke: &Path) -> Option<Cmd> {
    let mut words = match action {
        Action::Build => split_args(&p.build),
        Action::Test => split_args(&p.test),
        Action::Run | Action::Version | Action::Smoke => split_args(&p.launch),
    };
    match action {
        Action::Version => words.push("--version".into()),
        Action::Smoke => words.extend(["--smoke".to_string(), smoke.to_string_lossy().into_owned()]),
        _ => {}
    }
    Cmd::new(words, root.join(&p.dir))
}

/// The portfolio root: the first folder at or above `start` that holds RULES.md.
pub fn find_root(start: &Path) -> Option<PathBuf> {
    start.ancestors().find(|d| d.join("RULES.md").is_file()).map(Path::to_path_buf)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::parse;

    fn defaults() -> Vec<Program> {
        let (p, w) = load(&parse(include_str!("../config/programs.ini")));
        assert!(w.is_empty(), "{w:?}");
        p
    }

    fn by_name(ps: &[Program], n: &str) -> Program {
        ps.iter().find(|p| p.name == n).unwrap().clone()
    }

    #[test]
    fn defaults_list_existing_programs() {
        let ps = defaults();
        assert!(ps.len() >= 7);
        let root = find_root(Path::new(env!("CARGO_MANIFEST_DIR"))).unwrap();
        for p in &ps {
            assert!(root.join(&p.dir).is_dir(), "{}", p.dir);
            for f in &p.version_files {
                assert!(root.join(&p.dir).join(f).is_file(), "{}/{f}", p.dir);
            }
        }
    }

    #[test]
    fn split_args_keeps_quoted_words() {
        assert_eq!(split_args(r#"go build -ldflags "-H windowsgui" -o x.exe ."#), ["go", "build", "-ldflags", "-H windowsgui", "-o", "x.exe", "."]);
        assert_eq!(split_args(r#"  a   "" b "#), ["a", "", "b"]);
        assert!(split_args("   ").is_empty());
    }

    #[test]
    fn steps_split_on_and() {
        assert_eq!(steps("a b && c && "), vec![vec!["a".to_string(), "b".into()], vec!["c".to_string()]]);
    }

    #[test]
    fn render_round_trips() {
        let ps = defaults();
        let (again, w) = load(&parse(&render(&ps)));
        assert!(w.is_empty());
        assert_eq!(again, ps);
    }

    #[test]
    fn load_reports_bad_sections() {
        let (ps, w) = load(&parse("[programs]\norder = a, b, c\n[a]\nlang = Cobol\n[b]\nlang = Go\n"));
        assert!(ps.is_empty());
        assert_eq!(w.len(), 3);
    }

    #[test]
    fn python_has_no_build() {
        let ps = defaults();
        assert!(command(&by_name(&ps, "CRUD Hub"), Action::Build, Path::new("R"), Path::new("s")).is_none());
    }

    #[test]
    fn version_appends_flag_after_launch() {
        let ps = defaults();
        let c = command(&by_name(&ps, "Data Dash"), Action::Version, Path::new("R"), Path::new("s")).unwrap();
        assert_eq!(c.program, "cargo");
        assert_eq!(c.args.last().unwrap(), "--version");
        assert_eq!(c.args[c.args.len() - 2], "--");
        assert_eq!(c.cwd, Path::new("R").join("data_dash"));
    }

    #[test]
    fn smoke_passes_report_path() {
        let ps = defaults();
        let c = command(&by_name(&ps, "Notify Hub"), Action::Smoke, Path::new("R"), Path::new("rep.json")).unwrap();
        assert_eq!(&c.args[c.args.len() - 2..], ["--smoke", "rep.json"]);
    }

    #[test]
    fn crud_test_pattern_loses_its_quotes() {
        let ps = defaults();
        let c = command(&by_name(&ps, "CRUD Hub"), Action::Test, Path::new("R"), Path::new("s")).unwrap();
        assert_eq!(c.args.last().unwrap(), "test_*.py");
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

// ==== stamp v1 | author=kjFriday | hmac-sha256=4ef2f2939af740802b9469d1565194b810b7e99fbbcde8dac8bdfbfa149c9574 ====
