// ==== Generic Company Inc. portfolio ====================================
// Project: dev_console | File: src/registry.rs
// About: The portfolio's programs (from config/programs.ini) and the commands that build, test and...
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
// ========================================================================

//! The portfolio's programs (from config/programs.ini) and the commands that run each one.
//!
//! Each program has a section in programs.ini with its folder, language and command lines (launch, test,
//! build, desktop build and run, production). `load` turns the parsed INI into `Program`s, and `command`
//! turns a program plus an `Action` button into a `Cmd` that jobs.rs can start. The Versions & commands view
//! edits the programs and `render` writes them back.
//!
//! Commands are never handed to a shell: `split_args` splits a command line into words itself, so `&&`, `|`
//! and `>` have no special meaning in launch or test. Only desktop_build is split into steps on `&&`, by
//! `steps`, and desktop.rs runs those one by one.
//!
//! Defines `Lang`, `Program`, `Action` and `Cmd`; `find_root` locates the portfolio.

use std::path::{Path, PathBuf};

use crate::config::Ini;

/// A program's language, from its `lang` key. Shown in the program list; the commands themselves come
/// from the program's own keys, not from the language.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Lang {
    /// A Python program (usually no build command).
    Python,
    /// A Go program.
    Go,
    /// A Rust program.
    Rust,
}

// Text in and out.
impl Lang {
    /// The name as written in programs.ini and shown in the window.
    pub fn label(self) -> &'static str {
        match self {
            Lang::Python => "Python",
            Lang::Go => "Go",
            Lang::Rust => "Rust",
        }
    }

    /// The language named by `s`, ignoring case and surrounding space; None for any other text.
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
///
/// The key is the programs.ini key and the `Program` field of the same name (see `Program::field`), the
/// label is the editor's row title, and the help is its tooltip. `render` writes the keys in this order.
pub const FIELDS: [(&str, &str, &str); 8] = [
    (
        "launch",
        "Launch",
        "Starts the program. Run uses it as is; Version and Smoke add --version / --smoke FILE after it.",
    ),
    ("test", "Test", "Runs the program's tests (Test, Test all, live tests)."),
    (
        "build",
        "Build",
        "Builds the program (Build button). Leave empty when there is nothing to build.",
    ),
    (
        "desktop_build",
        "Desktop build",
        "Steps the Desktop shortcuts button runs before placing the shortcut, separated by &&.",
    ),
    (
        "desktop_run",
        "Desktop run",
        "What the desktop shortcut starts: an exe relative to the project folder, or \"pythonw <args>\".",
    ),
    (
        "production",
        "Production",
        "Serves the live site (live-production view, Start). Leave empty for a program with no site.",
    ),
    (
        "production_url",
        "Production URL",
        "Where the live site answers, such as http://127.0.0.1:8722 or a deployed https:// address.",
    ),
    (
        "production_checks",
        "Production checks",
        "What live-production checks: METHOD /path STATUS, separated by commas, such as GET / 200, POST /about 405.",
    ),
];

/// One program as programs.ini describes it. Command fields hold the command line as typed; empty means
/// the program has no such command.
#[derive(Clone, Debug, PartialEq)]
pub struct Program {
    /// Section name in programs.ini.
    pub key: String,
    /// The display name; the section name when `name` is not set.
    pub name: String,
    /// The program's folder relative to the portfolio root, with `/`; commands run there.
    pub dir: String,
    /// The language label.
    pub lang: Lang,
    /// Starts the program (Run; Version and Smoke add their flag after it). Required.
    pub launch: String,
    /// Runs its tests.
    pub test: String,
    /// Builds it; empty for Python.
    pub build: String,
    /// The Desktop shortcuts build steps, separated by `&&`.
    pub desktop_build: String,
    /// What the desktop shortcut starts.
    pub desktop_run: String,
    /// Serves the live site.
    pub production: String,
    /// Where the live site answers.
    pub production_url: String,
    /// The live-production checks, `METHOD /path STATUS` separated by commas.
    pub production_checks: String,
    /// Files, relative to `dir`, that each hold a version line to keep in step.
    pub version_files: Vec<String>,
}

// Field access by programs.ini key, for the command editor.
impl Program {
    /// The command field named `key` (one of the FIELDS keys); empty text for any other key.
    pub fn field(&self, key: &str) -> &str {
        match key {
            "launch" => &self.launch,
            "test" => &self.test,
            "build" => &self.build,
            "desktop_build" => &self.desktop_build,
            "desktop_run" => &self.desktop_run,
            "production" => &self.production,
            "production_url" => &self.production_url,
            "production_checks" => &self.production_checks,
            _ => "",
        }
    }

    /// The command field named `key`, to edit in place; None for a key that is not in FIELDS.
    pub fn field_mut(&mut self, key: &str) -> Option<&mut String> {
        match key {
            "launch" => Some(&mut self.launch),
            "test" => Some(&mut self.test),
            "build" => Some(&mut self.build),
            "desktop_build" => Some(&mut self.desktop_build),
            "desktop_run" => Some(&mut self.desktop_run),
            "production" => Some(&mut self.production),
            "production_url" => Some(&mut self.production_url),
            "production_checks" => Some(&mut self.production_checks),
            _ => None,
        }
    }

    /// Whether the live-production view lists this program: it has a site to start or to check.
    pub fn has_production(&self) -> bool {
        !self.production.trim().is_empty() || !self.production_url.trim().is_empty()
    }
}

/// Programs in `[programs] order`, plus warnings for sections that are missing or incomplete.
///
/// A section that is not listed in `order` is ignored. A listed section is skipped, with a warning the
/// sidebar shows, when it does not exist, its `lang` is not Python, Go or Rust, or it lacks `dir` or
/// `launch`. Missing optional keys read as empty. `version_files` is a comma-separated list.
pub fn load(ini: &Ini) -> (Vec<Program>, Vec<String>) {
    let mut out = vec![];
    let mut warnings = vec![];
    let order = ini
        .get("programs")
        .and_then(|s| s.get("order"))
        .cloned()
        .unwrap_or_default();
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
            name: if get("name").is_empty() {
                key.to_string()
            } else {
                get("name")
            },
            dir: get("dir"),
            lang,
            launch: get("launch"),
            test: get("test"),
            build: get("build"),
            desktop_build: get("desktop_build"),
            desktop_run: get("desktop_run"),
            production: get("production"),
            production_url: get("production_url"),
            production_checks: get("production_checks"),
            version_files: get("version_files")
                .split(',')
                .map(|f| f.trim().to_string())
                .filter(|f| !f.is_empty())
                .collect(),
        });
    }
    (out, warnings)
}

/// programs.ini text for `programs`, with a short header.
///
/// The inverse of `load`: `load(&parse(&render(ps)))` gives `ps` back (pinned by a test). Before Save
/// commands writes the file, app.rs loads the text again and refuses when that reports a problem or loses
/// a program. Comments a user added to the file by hand are not kept.
pub fn render(programs: &[Program]) -> String {
    let mut s = String::from(
        "; Dev Console programs: one section per program, in the order of [programs] order.\n\
         ; Saved by the console's Versions & commands view; see tools/dev_console/README.md for the keys.\n\
         ; Quote an argument that contains spaces with double quotes; separate desktop_build steps with &&.\n\n",
    );
    let order: Vec<&str> = programs.iter().map(|p| p.key.as_str()).collect();
    s += &format!("[programs]\norder = {}\n", order.join(", "));
    for p in programs {
        s += &format!(
            "\n[{}]\nname = {}\ndir = {}\nlang = {}\n",
            p.key,
            p.name,
            p.dir,
            p.lang.label()
        );
        for (k, _, _) in FIELDS {
            s += &format!("{k} = {}\n", p.field(k));
        }
        s += &format!("version_files = {}\n", p.version_files.join(", "));
    }
    s
}

/// Split a command line into words; double quotes group words and are removed.
///
/// `go build -ldflags "-H windowsgui"` -> `go`, `build`, `-ldflags`, `-H windowsgui`. A quote may start or
/// end inside a word (`a"b c"d` is one word `ab cd`), and `""` makes an empty word. There is no escape
/// character, so a word cannot hold a literal `"`. An unclosed quote runs to the end of the text.
///
/// The words then go to the program unchanged as separate arguments; Rust's Command quotes each again as
/// Windows needs, so a word with spaces arrives whole.
pub fn split_args(s: &str) -> Vec<String> {
    let mut out = vec![];
    let mut cur = String::new();
    // `any` marks that a word has started, even an empty one from `""`, so it is kept at the next space
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
///
/// Used for desktop_build, whose steps desktop.rs runs one after another, stopping at the first that fails
/// (as `&&` does in a shell). The split is plain text, so a `&&` inside quotes splits too.
pub fn steps(s: &str) -> Vec<Vec<String>> {
    s.split("&&").map(split_args).filter(|w| !w.is_empty()).collect()
}

/// One of the Run view's per-program buttons (keys F4 to F8 by default).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Action {
    /// Run the build command.
    Build,
    /// Run the test command.
    Test,
    /// Run the launch command as is.
    Run,
    /// Run launch with `--version` added.
    Version,
    /// Run launch with `--smoke FILE` added; the program writes a JSON report there and exits.
    Smoke,
}

// The button list and its texts.
impl Action {
    /// Every action in button order. app.rs refers to an action by its index here (the TEST index, the
    /// per-program last-run marks), so the order matters.
    pub const ALL: [Action; 5] = [Action::Build, Action::Test, Action::Run, Action::Version, Action::Smoke];

    /// The button text.
    pub fn label(self) -> &'static str {
        match self {
            Action::Build => "Build",
            Action::Test => "Test",
            Action::Run => "Run",
            Action::Version => "Version",
            Action::Smoke => "Smoke",
        }
    }

    /// The button's tooltip; the view adds the exact command below it.
    pub fn help(self) -> &'static str {
        match self {
            Action::Build => "Build the program with its build command (not needed for Python).",
            Action::Test => "Run the program's tests.",
            Action::Run => "Start the program from source.",
            Action::Version => "Start the program with --version and show what it prints.",
            Action::Smoke => {
                "Open the program with --smoke: it opens its window, writes a JSON report and closes. The report is added to the log."
            }
        }
    }
}

/// A command ready to start: what jobs.rs runs.
#[derive(Debug, PartialEq, Eq)]
pub struct Cmd {
    /// The program to start, found on PATH when it is a bare name (`cargo`, `go`, `python`).
    pub program: String,
    /// The arguments, each passed as one argument.
    pub args: Vec<String>,
    /// The working folder.
    pub cwd: PathBuf,
}

// Building a Cmd from words.
impl Cmd {
    /// The first word is the program, the rest its arguments; None when `words` is empty (a blank command).
    pub fn new(words: Vec<String>, cwd: PathBuf) -> Option<Cmd> {
        let (program, args) = words.split_first()?;
        Some(Cmd {
            program: program.clone(),
            args: args.to_vec(),
            cwd,
        })
    }
}

/// The command for `action` on `p`, or None when it does not apply (an empty build command).
/// `smoke` is the report file passed to `--smoke`.
///
/// The command runs in `root` joined with the program's `dir`. Version and Smoke append their flags at the
/// end, so a cargo launch must end with `--` for them to reach the program instead of cargo (the Data Dash
/// test pins this).
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
///
/// RULES.md marks the root because the portfolio keeps exactly one, at the top. `start` should be absolute
/// (main.rs passes the current folder and the exe's folder); a relative path only walks its own parts.
pub fn find_root(start: &Path) -> Option<PathBuf> {
    start
        .ancestors()
        .find(|d| d.join("RULES.md").is_file())
        .map(Path::to_path_buf)
}

/// Unit tests: the shipped programs.ini, word splitting, rendering and the command for each action.
#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::parse;

    // The programs of the default programs.ini, which must load without a warning.
    fn defaults() -> Vec<Program> {
        let (p, w) = load(&parse(include_str!("../config/programs.ini")));
        assert!(w.is_empty(), "{w:?}");
        p
    }

    // The program with display name `n`; panics when there is none.
    fn by_name(ps: &[Program], n: &str) -> Program {
        ps.iter().find(|p| p.name == n).unwrap().clone()
    }

    // Every default program's folder and version files exist in the real portfolio, so a moved folder fails here.
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

    // A quoted ldflags value stays one word without its quotes, `""` is an empty word, and blanks give nothing.
    #[test]
    fn split_args_keeps_quoted_words() {
        assert_eq!(
            split_args(r#"go build -ldflags "-H windowsgui" -o x.exe ."#),
            ["go", "build", "-ldflags", "-H windowsgui", "-o", "x.exe", "."]
        );
        assert_eq!(split_args(r#"  a   "" b "#), ["a", "", "b"]);
        assert!(split_args("   ").is_empty());
    }

    // Two steps split on `&&`; the empty step after the trailing `&&` is dropped.
    #[test]
    fn steps_split_on_and() {
        assert_eq!(
            steps("a b && c && "),
            vec![vec!["a".to_string(), "b".into()], vec!["c".to_string()]]
        );
    }

    // Rendering the defaults and loading the text again gives the same programs, so Save loses nothing.
    #[test]
    fn render_round_trips() {
        let ps = defaults();
        let (again, w) = load(&parse(&render(&ps)));
        assert!(w.is_empty());
        assert_eq!(again, ps);
    }

    // One warning each for an unknown language, a missing dir and launch, and a missing section.
    #[test]
    fn load_reports_bad_sections() {
        let (ps, w) = load(&parse(
            "[programs]\norder = a, b, c\n[a]\nlang = Cobol\n[b]\nlang = Go\n",
        ));
        assert!(ps.is_empty());
        assert_eq!(w.len(), 3);
    }

    // The CRUD Hub (Python) has an empty build command, so Build has no command for it.
    #[test]
    fn python_has_no_build() {
        let ps = defaults();
        assert!(command(&by_name(&ps, "CRUD Hub"), Action::Build, Path::new("R"), Path::new("s")).is_none());
    }

    // Data Dash's cargo launch ends with `--`, so `--version` lands after it, and the command runs in its folder.
    #[test]
    fn version_appends_flag_after_launch() {
        let ps = defaults();
        let c = command(
            &by_name(&ps, "Data Dash"),
            Action::Version,
            Path::new("R"),
            Path::new("s"),
        )
        .unwrap();
        assert_eq!(c.program, "cargo");
        assert_eq!(c.args.last().unwrap(), "--version");
        assert_eq!(c.args[c.args.len() - 2], "--");
        assert_eq!(c.cwd, Path::new("R").join("company").join("data_dash"));
    }

    // Smoke ends the launch command with `--smoke` and the report path.
    #[test]
    fn smoke_passes_report_path() {
        let ps = defaults();
        let c = command(
            &by_name(&ps, "Notify Hub"),
            Action::Smoke,
            Path::new("R"),
            Path::new("rep.json"),
        )
        .unwrap();
        assert_eq!(&c.args[c.args.len() - 2..], ["--smoke", "rep.json"]);
    }

    // The CRUD Hub's quoted `test_*.py` pattern reaches unittest without quotes (no shell would strip them).
    #[test]
    fn crud_test_pattern_loses_its_quotes() {
        let ps = defaults();
        let c = command(&by_name(&ps, "CRUD Hub"), Action::Test, Path::new("R"), Path::new("s")).unwrap();
        assert_eq!(c.args.last().unwrap(), "test_*.py");
    }

    // The Journal has a public local site with at least five valid checks; Data Dash has no site.
    #[test]
    fn journal_has_a_live_site() {
        let ps = defaults();
        let j = by_name(&ps, "Journal");
        assert!(j.has_production());
        assert!(j.production.contains("-public"), "{}", j.production);
        assert!(
            j.production_url.starts_with("http://127.0.0.1:"),
            "{}",
            j.production_url
        );
        assert!(crate::production::parse_checks(&j.production_checks).unwrap().len() >= 5);
        assert!(!by_name(&ps, "Data Dash").has_production());
    }

    // A RULES.md two folders up is found from the deep folder.
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

// ==== stamp v1 | author=kjFriday | hmac-sha256=c0ba4dd2afe5ecc3d4ecacd2493a99bf7fb09280c92c0f97f9c786f47af9f645 ====
