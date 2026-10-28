// ==== Generic Company Inc. portfolio ====================================
// Project: portfolio | File: dev_console/src/versions.rs
// About: Program versions: find the version in each of a program's version files and change them...
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
// ========================================================================

//! Program versions: find the version in each of a program's version files and change them together.

use std::path::{Path, PathBuf};

/// One file's version line.
#[derive(Clone, Debug, PartialEq)]
pub struct Spot {
    pub file: PathBuf,
    /// 0-based line index.
    pub line: usize,
    pub value: String,
}

/// The quoted value on a version line (`"version": "x"`, `__version__ = "x"`, `Version = "x"`,
/// `version = "x"`), with the byte range of the value inside the line.
pub fn version_on(line: &str) -> Option<(usize, usize)> {
    let t = line.trim_start();
    let lead = line.len() - t.len();
    let key_len = ["\"version\"", "__version__", "Version", "version"].iter().find(|k| t.starts_with(*k))?.len();
    let rest = &t[key_len..];
    let after = rest.trim_start();
    let sep = after.chars().next()?;
    if sep != '=' && sep != ':' {
        return None;
    }
    let open = lead + key_len + (rest.len() - after.len()) + 1 + after[1..].find('"')? + 1;
    let close = open + line[open..].find('"')?;
    Some((open, close))
}

/// The first version line in `file`.
pub fn find_in(file: &Path) -> Result<Spot, String> {
    let text = std::fs::read_to_string(file).map_err(|e| format!("{}: {e}", file.display()))?;
    for (i, l) in text.lines().enumerate() {
        if let Some((a, b)) = version_on(l) {
            return Ok(Spot { file: file.to_path_buf(), line: i, value: l[a..b].to_string() });
        }
    }
    Err(format!("{}: no version line", file.display()))
}

/// A version the programs can use: numbers separated by dots, 2 to 4 parts.
pub fn valid(v: &str) -> bool {
    let parts: Vec<&str> = v.split('.').collect();
    (2..=4).contains(&parts.len()) && parts.iter().all(|p| !p.is_empty() && p.chars().all(|c| c.is_ascii_digit()))
}

/// Bump the last part: 0.2.0 -> 0.2.1.
pub fn bump(v: &str, part: usize) -> Option<String> {
    if !valid(v) {
        return None;
    }
    let mut n: Vec<u64> = v.split('.').map(|p| p.parse().unwrap()).collect();
    let part = part.min(n.len() - 1);
    n[part] += 1;
    for x in n.iter_mut().skip(part + 1) {
        *x = 0;
    }
    Some(n.iter().map(u64::to_string).collect::<Vec<_>>().join("."))
}

/// Write `new` into every spot, keeping each file's line endings. Returns the files changed.
pub fn set(spots: &[Spot], new: &str) -> Result<Vec<PathBuf>, String> {
    if !valid(new) {
        return Err(format!("'{new}' is not a version like 1.2.3"));
    }
    let mut changed = vec![];
    for s in spots {
        let text = std::fs::read_to_string(&s.file).map_err(|e| e.to_string())?;
        let nl = if text.contains("\r\n") { "\r\n" } else { "\n" };
        let mut lines: Vec<String> = text.split(nl).map(String::from).collect();
        let l = lines.get_mut(s.line).ok_or_else(|| format!("{}: file changed", s.file.display()))?;
        let (a, b) = version_on(l).ok_or_else(|| format!("{}: version line moved; reload", s.file.display()))?;
        if &l[a..b] == new {
            continue;
        }
        l.replace_range(a..b, new);
        std::fs::write(&s.file, lines.join(nl)).map_err(|e| e.to_string())?;
        changed.push(s.file.clone());
    }
    Ok(changed)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn version_lines_of_each_language() {
        for (line, want) in [
            ("  \"version\": \"0.2.0\",", "0.2.0"),
            ("__version__ = \"1.4\"", "1.4"),
            ("\tVersion   = \"0.1.0\"", "0.1.0"),
            ("version = \"3.2.1\"", "3.2.1"),
        ] {
            let (a, b) = version_on(line).unwrap();
            assert_eq!(&line[a..b], want, "{line}");
        }
        assert!(version_on("versions = [1]").is_none());
        assert!(version_on("// Version is set at build time").is_none());
        assert!(version_on("version.workspace = true").is_none());
    }

    #[test]
    fn valid_and_bump() {
        assert!(valid("0.2.0") && valid("1.2") && !valid("1") && !valid("1.x.0") && !valid("1..2"));
        assert_eq!(bump("0.2.9", 2).as_deref(), Some("0.2.10"));
        assert_eq!(bump("0.2.9", 1).as_deref(), Some("0.3.0"));
        assert_eq!(bump("0.2.9", 0).as_deref(), Some("1.0.0"));
        assert_eq!(bump("bad", 0), None);
    }

    #[test]
    fn set_changes_only_the_first_version_line_and_keeps_crlf() {
        let dir = std::env::temp_dir().join(format!("gc-console-ver-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let toml = dir.join("Cargo.toml");
        std::fs::write(&toml, "[package]\r\nname = \"x\"\r\nversion = \"0.2.0\"\r\n\r\n[dependencies]\r\nfoo = { version = \"1\" }\r\n").unwrap();
        let json = dir.join("setup.json");
        std::fs::write(&json, "{\n  \"version\": \"0.2.0\"\n}\n").unwrap();
        let spots = vec![find_in(&toml).unwrap(), find_in(&json).unwrap()];
        assert_eq!(spots[0].value, "0.2.0");
        assert_eq!(set(&spots, "0.3.0").unwrap().len(), 2);
        let t = std::fs::read_to_string(&toml).unwrap();
        assert!(t.contains("version = \"0.3.0\"\r\n") && t.contains("foo = { version = \"1\" }"));
        assert_eq!(find_in(&json).unwrap().value, "0.3.0");
        assert!(set(&spots, "0.3.0").unwrap().is_empty());
        assert!(set(&spots, "nope").is_err());
        std::fs::remove_dir_all(&dir).unwrap();
    }
}

// ==== stamp v1 | author=kjFriday | hmac-sha256=8b10f7dfcbf9ff1a653ddc46e16709ea6f2cc154cb72685a72be8fd641fe8f84 ====
