// ==== Generic Company Inc. portfolio ====================================
// Project: portfolio | File: dev_console/src/seed.rs
// About: Seed data: the CRUD Hub's database, its row counts and backups, and the hub's own seed...
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
// ========================================================================

//! Seed data: the CRUD Hub's database, its row counts and backups, and the hub's own seed tools.
//! Every change goes through the hub's code (seed.py, export_mock.py, seed.backup), which owns the schema;
//! the console itself only reads.

use std::path::{Path, PathBuf};
use std::time::SystemTime;

use crate::registry::Cmd;

pub const HUB_DIR: &str = "create_read_update_delete_simple_io_data_base";

/// The shared database the programs use when nothing else is chosen: GENERIC_COMPANY_DB, then
/// `<LOCALAPPDATA>\Generic Company Inc\generic_company.db`.
pub fn default_db(env: &dyn Fn(&str) -> Option<String>) -> Option<PathBuf> {
    if let Some(p) = env("GENERIC_COMPANY_DB").filter(|p| !p.trim().is_empty()) {
        return Some(PathBuf::from(p));
    }
    env("LOCALAPPDATA").map(|d| Path::new(&d).join("Generic Company Inc").join("generic_company.db"))
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Op {
    Counts,
    Backup,
    Reseed,
    Fresh,
    Restore,
    Export,
}

impl Op {
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

    pub fn help(self) -> &'static str {
        match self {
            Op::Counts => "Read how many rows each table holds (read-only).",
            Op::Backup => "Copy the database to a dated backup beside it (seed.backup) and check the copy's row counts.",
            Op::Reseed => "python seed.py --db PATH: backs the file up, empties it in place and refills it with the deterministic mock data. Programs that have it open keep working.",
            Op::Fresh => "python seed.py --fresh --db PATH: deletes the file and builds it again from nothing (byte-identical every run). No backup is made, so close the other programs first.",
            Op::Restore => "Back up the current database, then copy the chosen backup over it.",
            Op::Export => "python export_mock.py: write each program's mock/ snapshot from the database, so each runs on its own.",
        }
    }

    /// Ops that destroy or replace data ask for a second click.
    pub fn needs_confirm(self) -> bool {
        matches!(self, Op::Reseed | Op::Fresh | Op::Restore)
    }
}

const COUNTS: &str = "import sqlite3, sys, pathlib\nc = sqlite3.connect(pathlib.Path(sys.argv[1]).resolve().as_uri() + '?mode=ro', uri=True)\nnames = [r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name\")]\nprint(*[f'COUNT {t} {c.execute(f\"SELECT COUNT(*) FROM \\\"{t}\\\"\").fetchone()[0]}' for t in names], sep='\\n')\n";

const BACKUP: &str = "import sys, db, seed\ndb.DB_PATH = sys.argv[1]\nprint('BACKUP', seed.backup())\n";

const RESTORE: &str = "import sys, sqlite3, db, seed\n\
db.DB_PATH = sys.argv[1]\n\
print('BACKUP', seed.backup())\n\
src, dst = sqlite3.connect(sys.argv[2]), sqlite3.connect(sys.argv[1])\n\
src.backup(dst)\n\
dst.close(); src.close()\n\
print('RESTORED', sys.argv[2])\n";

/// The command for `op` on `db`, run in the hub's folder. `backup` is the file Restore copies from.
pub fn command(op: Op, root: &Path, db: &Path, backup: Option<&Path>) -> Option<Cmd> {
    let d = db.to_string_lossy().into_owned();
    let words: Vec<String> = match op {
        Op::Counts => vec!["python".into(), "-c".into(), COUNTS.into(), d],
        Op::Backup => vec!["python".into(), "-c".into(), BACKUP.into(), d],
        Op::Reseed => vec!["python".into(), "seed.py".into(), "--db".into(), d],
        Op::Fresh => vec!["python".into(), "seed.py".into(), "--fresh".into(), "--db".into(), d],
        Op::Restore => vec!["python".into(), "-c".into(), RESTORE.into(), d, backup?.to_string_lossy().into_owned()],
        Op::Export => vec!["python".into(), "export_mock.py".into()],
    };
    Cmd::new(words, root.join(HUB_DIR))
}

/// Table counts from a Counts job's output lines (`COUNT table n`).
pub fn parse_counts(lines: &[String]) -> Vec<(String, u64)> {
    lines
        .iter()
        .filter_map(|l| {
            let mut w = l.split_whitespace();
            (w.next()? == "COUNT").then_some(())?;
            Some((w.next()?.to_string(), w.next()?.parse().ok()?))
        })
        .collect()
}

#[derive(Clone, Debug, PartialEq)]
pub struct Backup {
    pub path: PathBuf,
    /// "2026-10-17 09:30:05", from the file name.
    pub when: String,
    pub size: u64,
}

/// The `<stem>-YYYYMMDD-HHMMSS<ext>` backups beside `db`, newest first.
pub fn backups(db: &Path) -> Vec<Backup> {
    let (Some(dir), Some(stem)) = (db.parent(), db.file_stem().map(|s| s.to_string_lossy().into_owned())) else {
        return vec![];
    };
    let ext = db.extension().map(|e| format!(".{}", e.to_string_lossy())).unwrap_or_else(|| ".db".into());
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
            let when = format!("{}-{}-{} {}:{}:{}", &d[..4], &d[4..6], &d[6..], &t[..2], &t[2..4], &t[4..]);
            Some(Backup { size: e.metadata().map(|m| m.len()).unwrap_or(0), path: e.path(), when })
        })
        .collect();
    out.sort_by(|a, b| b.when.cmp(&a.when));
    out
}

/// Size and age of the database file, for the status line.
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

pub fn size(n: u64) -> String {
    match n {
        n if n < 1024 => format!("{n} B"),
        n if n < 1024 * 1024 => format!("{:.1} KB", n as f64 / 1024.0),
        n => format!("{:.1} MB", n as f64 / 1024.0 / 1024.0),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_db_prefers_the_variable() {
        let env = |k: &str| match k {
            "GENERIC_COMPANY_DB" => Some(r"X:\shared.db".to_string()),
            "LOCALAPPDATA" => Some(r"C:\U\Local".to_string()),
            _ => None,
        };
        assert_eq!(default_db(&env), Some(PathBuf::from(r"X:\shared.db")));
        let env = |k: &str| (k == "LOCALAPPDATA").then(|| r"C:\U\Local".to_string());
        assert_eq!(default_db(&env), Some(PathBuf::from(r"C:\U\Local\Generic Company Inc\generic_company.db")));
    }

    #[test]
    fn commands_run_in_the_hub() {
        let c = command(Op::Fresh, Path::new("R"), Path::new("x.db"), None).unwrap();
        assert_eq!(c.args, ["seed.py", "--fresh", "--db", "x.db"]);
        assert_eq!(c.cwd, Path::new("R").join(HUB_DIR));
        assert!(command(Op::Restore, Path::new("R"), Path::new("x.db"), None).is_none());
        let r = command(Op::Restore, Path::new("R"), Path::new("x.db"), Some(Path::new("b.db"))).unwrap();
        assert_eq!(&r.args[r.args.len() - 2..], ["x.db", "b.db"]);
    }

    #[test]
    fn counts_parse() {
        let lines = ["> python", "COUNT customers 40", "COUNT orders 120", "COUNT bad x"].map(String::from);
        assert_eq!(parse_counts(&lines), [("customers".to_string(), 40), ("orders".to_string(), 120)]);
    }

    #[test]
    fn backups_are_found_and_sorted() {
        let dir = std::env::temp_dir().join(format!("gc-console-seed-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        for f in ["generic_company.db", "generic_company-20261017-093005.db", "generic_company-20261018-120000.db",
                  "generic_company-moved.db", "other-20261017-093005.db", "generic_company.db-wal"] {
            std::fs::write(dir.join(f), "x").unwrap();
        }
        let b = backups(&dir.join("generic_company.db"));
        assert_eq!(b.len(), 2);
        assert_eq!(b[0].when, "2026-10-18 12:00:00");
        assert_eq!(b[1].when, "2026-10-17 09:30:05");
        std::fs::remove_dir_all(&dir).unwrap();
    }

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
            let out = std::process::Command::new(&c.program).args(&c.args).current_dir(&c.cwd).output().unwrap();
            assert!(out.status.success(), "{op:?}: {}", String::from_utf8_lossy(&out.stderr));
            String::from_utf8_lossy(&out.stdout).lines().map(String::from).collect::<Vec<_>>()
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

// ==== stamp v1 | author=kjFriday | hmac-sha256=6e83b126469fb99d00479e7084102a547369fcc5f1cfc445ed28ff1555ab2523 ====
