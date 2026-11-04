// ==== Generic Company Inc. portfolio ====================================
// Project: dev_console | File: src/seed.rs
// About: Seed data: the CRUD Hub's database, its row counts and backups, and the hub's own seed...
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
// ========================================================================

//! Seed data: the CRUD Hub's database, its row counts and backups, and its seed tools.
//!
//! Every change goes through the hub's code (seed.py, export_mock.py, seed.backup), which owns the schema;
//! the console itself only reads. The Seed data view (app/views/seed.rs) shows the database, and app.rs runs
//! each `Op` as an ordinary job built by `command`, in the hub's folder so `import db, seed` finds the hub's
//! modules.
//!
//! Three ops need a few lines of Python that no hub script offers, so they are inline `python -c` scripts
//! here (COUNTS, BACKUP, RESTORE) with the paths passed as arguments, never pasted into the code. Their
//! output lines start with a marker word: `parse_counts` reads the `COUNT` lines back, while `BACKUP` and
//! `RESTORED` are for the job's log.
//!
//! Defines `Op` and `Backup`.

use std::path::{Path, PathBuf};
use std::time::SystemTime;

use crate::registry::Cmd;

/// The CRUD Hub's folder relative to the portfolio root; every seed command runs there.
pub const HUB_DIR: &str = "company/crud_hub";

/// The shared database the programs use when nothing else is chosen: GENERIC_COMPANY_DB, then
/// `<LOCALAPPDATA>\Generic Company Inc\generic_company.db`.
///
/// A blank GENERIC_COMPANY_DB counts as unset. None when neither is available. The path need not exist yet.
pub fn default_db(env: &dyn Fn(&str) -> Option<String>) -> Option<PathBuf> {
    if let Some(p) = env("GENERIC_COMPANY_DB").filter(|p| !p.trim().is_empty()) {
        return Some(PathBuf::from(p));
    }
    env("LOCALAPPDATA").map(|d| Path::new(&d).join("Generic Company Inc").join("generic_company.db"))
}

/// One of the Seed data view's buttons. `help` says what each does.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Op {
    /// Read the row count of every table (read-only).
    Counts,
    /// Make a dated backup now.
    Backup,
    /// Back up, then empty and refill the database in place.
    Reseed,
    /// Delete the file and build it again; no backup.
    Fresh,
    /// Back up, then copy a chosen backup over the database.
    Restore,
    /// Write every program's mock/ snapshot from the database.
    Export,
}

// Button texts and the confirm rule.
impl Op {
    /// The button text.
    pub fn label(self) -> &'static str {
        match self {
            Op::Counts => "Refresh counts",
            Op::Backup => "Back up now",
            Op::Reseed => "Reseed",
            Op::Fresh => "Rebuild fresh",
            Op::Restore => "Restore",
            Op::Export => "Export mock snapshots",
        }
    }

    /// The button's tooltip: what it runs and what it changes.
    pub fn help(self) -> &'static str {
        match self {
            Op::Counts => "Read how many rows each table holds (read-only).",
            Op::Backup => {
                "Copy the database to a dated backup beside it (seed.backup) and check the copy's row counts."
            }
            Op::Reseed => {
                "python seed.py --db PATH: backs the file up, empties it in place and refills it with the deterministic mock data. Programs that have it open keep working."
            }
            Op::Fresh => {
                "python seed.py --fresh --db PATH: deletes the file and builds it again from nothing (byte-identical every run). No backup is made, so close the other programs first."
            }
            Op::Restore => "Back up the current database, then copy the chosen backup over it.",
            Op::Export => {
                "python export_mock.py: write each program's mock/ snapshot from the database, so each runs on its own."
            }
        }
    }

    /// Ops that destroy or replace data ask for a second click.
    ///
    /// app.rs arms the op on the first click and runs it on a second click of the same button before the
    /// confirm time runs out.
    pub fn needs_confirm(self) -> bool {
        matches!(self, Op::Reseed | Op::Fresh | Op::Restore)
    }
}

/// Python for Counts: `python -c COUNTS DB` prints `COUNT <table> <rows>` for every table.
///
/// - The file opens through a `file:` URI with `?mode=ro`, SQLite's read-only mode, so counting can never
///   create a missing database or write to one; `Path.resolve().as_uri()` makes the URI and escapes spaces.
/// - `sqlite_master` is SQLite's catalog; its `type='table'` rows are the tables. Names starting `sqlite_`
///   are SQLite's own internal tables (such as `sqlite_sequence`), left out.
/// - Each name is put in double quotes, SQL's identifier quoting, in case a name is a keyword.
///
/// `parse_counts` reads the output.
const COUNTS: &str = "import sqlite3, sys, pathlib\nc = sqlite3.connect(pathlib.Path(sys.argv[1]).resolve().as_uri() + '?mode=ro', uri=True)\nnames = [r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name\")]\nprint(*[f'COUNT {t} {c.execute(f\"SELECT COUNT(*) FROM \\\"{t}\\\"\").fetchone()[0]}' for t in names], sep='\\n')\n";

/// Python for Backup: `python -c BACKUP DB` points the hub's `db` module at DB and calls `seed.backup()`,
/// which writes the dated copy beside it and checks the copy's row counts; prints `BACKUP <path>`
/// (`BACKUP None` when the database is missing or empty, so there is nothing to keep).
const BACKUP: &str = "import sys, db, seed\ndb.DB_PATH = sys.argv[1]\nprint('BACKUP', seed.backup())\n";

/// Python for Restore: `python -c RESTORE DB FROM` backs DB up first, then copies FROM over it.
///
/// The copy uses SQLite's online backup API (`Connection.backup`), not a file copy: it copies page by page
/// under SQLite's own locking, so it is safe while other programs have the database open, and it replaces
/// the whole content of DB. Prints `BACKUP <path>` and `RESTORED <from>`.
const RESTORE: &str = "import sys, sqlite3, db, seed\n\
db.DB_PATH = sys.argv[1]\n\
print('BACKUP', seed.backup())\n\
src, dst = sqlite3.connect(sys.argv[2]), sqlite3.connect(sys.argv[1])\n\
src.backup(dst)\n\
dst.close(); src.close()\n\
print('RESTORED', sys.argv[2])\n";

/// The command for `op` on `db`, run in the hub's folder. `backup` is the file Restore copies from.
///
/// None only for Restore with no backup chosen. `python` must be on PATH.
///
/// Known limitation: Export takes no path, so export_mock.py reads the database the hub resolves for
/// itself, which is not `db` when another file is chosen in the view.
pub fn command(op: Op, root: &Path, db: &Path, backup: Option<&Path>) -> Option<Cmd> {
    let d = db.to_string_lossy().into_owned();
    let words: Vec<String> = match op {
        Op::Counts => vec!["python".into(), "-c".into(), COUNTS.into(), d],
        Op::Backup => vec!["python".into(), "-c".into(), BACKUP.into(), d],
        Op::Reseed => vec!["python".into(), "seed.py".into(), "--db".into(), d],
        Op::Fresh => vec!["python".into(), "seed.py".into(), "--fresh".into(), "--db".into(), d],
        Op::Restore => vec![
            "python".into(),
            "-c".into(),
            RESTORE.into(),
            d,
            backup?.to_string_lossy().into_owned(),
        ],
        Op::Export => vec!["python".into(), "export_mock.py".into()],
    };
    Cmd::new(words, root.join(HUB_DIR))
}

/// Table counts from a Counts job's output lines (`COUNT table n`).
///
/// Every other line (the job's header line, a warning) is skipped, as is a line whose count is not a
/// number. Known limitation: a table name with a space in it would be cut at the space and skipped.
pub fn parse_counts(lines: &[String]) -> Vec<(String, u64)> {
    lines
        .iter()
        .filter_map(|l| {
            let mut w = l.split_whitespace();
            // `?` on the bool-to-Option turns "not a COUNT line" into None for filter_map
            (w.next()? == "COUNT").then_some(())?;
            Some((w.next()?.to_string(), w.next()?.parse().ok()?))
        })
        .collect()
}

/// One dated backup file beside the database, as the Seed data view lists it.
#[derive(Clone, Debug, PartialEq)]
pub struct Backup {
    /// The backup file.
    pub path: PathBuf,
    /// "2026-10-17 09:30:05", from the file name.
    pub when: String,
    /// File size in bytes (0 when it cannot be read).
    pub size: u64,
}

/// The `<stem>-YYYYMMDD-HHMMSS<ext>` backups beside `db`, newest first.
///
/// The time comes from the name, not the file's dates, since copying a backup changes those. Names that
/// do not match exactly (another stem, `-moved`, a `-wal` file) are ignored. The extension defaults to `.db`
/// when `db` has none. An unreadable folder gives an empty list.
///
/// Steps:
/// 1. Strip `<stem>-` and `<ext>` from each name in the folder.
/// 2. What is left must be 8 digits, `-`, 6 digits.
/// 3. Turn it into `YYYY-MM-DD HH:MM:SS`; that text sorts in time order, so newest first is a reverse sort.
pub fn backups(db: &Path) -> Vec<Backup> {
    let (Some(dir), Some(stem)) = (db.parent(), db.file_stem().map(|s| s.to_string_lossy().into_owned())) else {
        return vec![];
    };
    let ext = db
        .extension()
        .map(|e| format!(".{}", e.to_string_lossy()))
        .unwrap_or_else(|| ".db".into());
    let mut out: Vec<Backup> = std::fs::read_dir(dir)
        .into_iter()
        .flatten()
        .flatten()
        .filter_map(|e| {
            let name = e.file_name().to_string_lossy().into_owned();
            let stamp = name.strip_prefix(&format!("{stem}-"))?.strip_suffix(&ext)?;
            let (d, t) = stamp.split_once('-')?;
            if d.len() != 8 || t.len() != 6 || !(d.chars().chain(t.chars())).all(|c| c.is_ascii_digit()) {
                return None;
            }
            let when = format!(
                "{}-{}-{} {}:{}:{}",
                &d[..4],
                &d[4..6],
                &d[6..],
                &t[..2],
                &t[2..4],
                &t[4..]
            );
            Some(Backup {
                size: e.metadata().map(|m| m.len()).unwrap_or(0),
                path: e.path(),
                when,
            })
        })
        .collect();
    out.sort_by(|a, b| b.when.cmp(&a.when));
    out
}

/// Size and age of the database file, for the status line.
///
/// Such as `1.2 MB, changed 5 min ago`. The age unit grows with the age: seconds under 2 minutes, minutes
/// under 2 hours, hours under 2 days, then days, always rounded down. A missing file says how to make one.
pub fn describe(db: &Path) -> String {
    match std::fs::metadata(db) {
        Err(_) => "not created yet: Reseed or Rebuild fresh makes it".into(),
        Ok(m) => {
            let age = m
                .modified()
                .ok()
                .and_then(|t| SystemTime::now().duration_since(t).ok())
                .map(|d| match d.as_secs() {
                    s if s < 120 => format!("{s} s ago"),
                    s if s < 7200 => format!("{} min ago", s / 60),
                    s if s < 172_800 => format!("{} h ago", s / 3600),
                    s => format!("{} days ago", s / 86_400),
                })
                .unwrap_or_default();
            format!("{}, changed {age}", size(m.len()))
        }
    }
}

/// `n` bytes as text: `512 B`, `1.5 KB`, `3.2 MB` (1 KB = 1024 bytes, one decimal).
pub fn size(n: u64) -> String {
    match n {
        n if n < 1024 => format!("{n} B"),
        n if n < 1024 * 1024 => format!("{:.1} KB", n as f64 / 1024.0),
        n => format!("{:.1} MB", n as f64 / 1024.0 / 1024.0),
    }
}

/// Unit tests: the default path, the commands, count parsing, backup listing, and the hub's real scripts.
#[cfg(test)]
mod tests {
    use super::*;

    // GENERIC_COMPANY_DB wins when set; without it the path is built under LOCALAPPDATA.
    #[test]
    fn default_db_prefers_the_variable() {
        let env = |k: &str| match k {
            "GENERIC_COMPANY_DB" => Some(r"X:\shared.db".to_string()),
            "LOCALAPPDATA" => Some(r"C:\U\Local".to_string()),
            _ => None,
        };
        assert_eq!(default_db(&env), Some(PathBuf::from(r"X:\shared.db")));
        let env = |k: &str| (k == "LOCALAPPDATA").then(|| r"C:\U\Local".to_string());
        assert_eq!(
            default_db(&env),
            Some(PathBuf::from(r"C:\U\Local\Generic Company Inc\generic_company.db"))
        );
    }

    // Rebuild fresh passes its flags and the path and runs in the hub; Restore needs a backup and ends with
    // the database and the backup, in that order.
    #[test]
    fn commands_run_in_the_hub() {
        let c = command(Op::Fresh, Path::new("R"), Path::new("x.db"), None).unwrap();
        assert_eq!(c.args, ["seed.py", "--fresh", "--db", "x.db"]);
        assert_eq!(c.cwd, Path::new("R").join(HUB_DIR));
        assert!(command(Op::Restore, Path::new("R"), Path::new("x.db"), None).is_none());
        let r = command(Op::Restore, Path::new("R"), Path::new("x.db"), Some(Path::new("b.db"))).unwrap();
        assert_eq!(&r.args[r.args.len() - 2..], ["x.db", "b.db"]);
    }

    // Only well-formed COUNT lines count: the header line and a non-numeric count are skipped.
    #[test]
    fn counts_parse() {
        let lines = ["> python", "COUNT customers 40", "COUNT orders 120", "COUNT bad x"].map(String::from);
        assert_eq!(
            parse_counts(&lines),
            [("customers".to_string(), 40), ("orders".to_string(), 120)]
        );
    }

    // Of six files only the two correctly dated ones of this stem are listed, newest first; the database,
    // a `-moved` copy, another stem and the WAL file are not.
    #[test]
    fn backups_are_found_and_sorted() {
        let dir = std::env::temp_dir().join(format!("gc-console-seed-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        for f in [
            "generic_company.db",
            "generic_company-20261017-093005.db",
            "generic_company-20261018-120000.db",
            "generic_company-moved.db",
            "other-20261017-093005.db",
            "generic_company.db-wal",
        ] {
            std::fs::write(dir.join(f), "x").unwrap();
        }
        let b = backups(&dir.join("generic_company.db"));
        assert_eq!(b.len(), 2);
        assert_eq!(b[0].when, "2026-10-18 12:00:00");
        assert_eq!(b[1].when, "2026-10-17 09:30:05");
        std::fs::remove_dir_all(&dir).unwrap();
    }

    // End to end through python and the hub's code: rebuild, count, back up, restore, and the counts match.
    #[test]
    fn hub_scripts_work_on_a_real_database() {
        // Seeds a fresh database in a temp folder with the hub's own seed.py, then counts and backs it up.
        let root = crate::registry::find_root(Path::new(env!("CARGO_MANIFEST_DIR"))).unwrap();
        let dir = std::env::temp_dir().join(format!("gc-console-seeddb-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let db = dir.join("generic_company.db");
        let run = |op: Op, backup: Option<&Path>| {
            let c = command(op, &root, &db, backup).unwrap();
            let out = std::process::Command::new(&c.program)
                .args(&c.args)
                .current_dir(&c.cwd)
                .output()
                .unwrap();
            assert!(out.status.success(), "{op:?}: {}", String::from_utf8_lossy(&out.stderr));
            String::from_utf8_lossy(&out.stdout)
                .lines()
                .map(String::from)
                .collect::<Vec<_>>()
        };
        run(Op::Fresh, None);
        let counts = parse_counts(&run(Op::Counts, None));
        assert!(counts.iter().any(|(t, n)| t == "customers" && *n > 0), "{counts:?}");
        run(Op::Backup, None);
        let b = backups(&db);
        assert_eq!(b.len(), 1);
        run(Op::Restore, Some(&b[0].path));
        assert_eq!(parse_counts(&run(Op::Counts, None)), counts);
        std::fs::remove_dir_all(&dir).unwrap();
    }
}

// ==== stamp v1 | author=kjFriday | hmac-sha256=d0b049dc916852e01d2a402078a90ce55fc52e10a0039a7684d52cd32ea84fcc ====
