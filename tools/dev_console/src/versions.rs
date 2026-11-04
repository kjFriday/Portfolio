// ==== Generic Company Inc. portfolio ====================================
// Project: dev_console | File: src/versions.rs
// About: Program versions: find the version in each of a program's version files and change them...
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
// ========================================================================

//! Program versions: find a program's version in each version file and change them together.
//!
//! A program states its version in several files at once (setup.json, plus the source file its own version
//! comes from: a Python module, internal/app/app.go or Cargo.toml). programs.ini lists them as
//! `version_files`. The Versions & commands view shows each file's version (`find_in`), flags files that
//! disagree, offers `bump`, and Apply version writes one value into all of them (`set`). app.rs then runs
//! stamp.py --restamp on the changed source files.
//!
//! The parser is line-based and knows four spellings: JSON (`"version": "x"`), Python (`__version__ = "x"`),
//! Go (`Version = "x"`) and TOML (`version = "x"`). The first such line in a file is its version line, which
//! is why Cargo.toml's `[package]` version wins over a dependency's `version = "1"` further down.
//!
//! Defines `Spot`.

use std::path::{Path, PathBuf};

/// One file's version line.
#[derive(Clone, Debug, PartialEq)]
pub struct Spot {
    /// The version file, as found (root + program dir + file name).
    pub file: PathBuf,
    /// 0-based line index.
    pub line: usize,
    /// The version text between the quotes, as read.
    pub value: String,
}

/// The quoted value on a version line (`"version": "x"`, `__version__ = "x"`, `Version = "x"`,
/// `version = "x"`), with the byte range of the value inside the line.
///
/// The range is (first byte after the opening quote, byte of the closing quote), so `&line[a..b]` is the
/// value and `replace_range(a..b, new)` swaps it. None when the line does not start (after indentation)
/// with one of the keys followed by `=` or `:`, or has no quoted value after it. Words that only begin
/// with a key, such as `versions = [1]` or `version.workspace`, are refused because the next character is
/// not `=` or `:`.
///
/// Steps:
/// 1. Skip leading space; note its length (`lead`).
/// 2. Match a key; the list puts `"version"` (JSON) first, and only the exact case listed matches.
/// 3. Skip space; the next character must be `=` or `:`.
/// 4. The value starts after the next `"` and ends at the following `"`.
pub fn version_on(line: &str) -> Option<(usize, usize)> {
    let t = line.trim_start();
    let lead = line.len() - t.len();
    let key_len = ["\"version\"", "__version__", "Version", "version"]
        .iter()
        .find(|k| t.starts_with(*k))?
        .len();
    let rest = &t[key_len..];
    let after = rest.trim_start();
    let sep = after.chars().next()?;
    if sep != '=' && sep != ':' {
        return None;
    }
    // byte offsets in `line`: indentation + key + space before the separator + the 1-byte separator, then
    // up to and past the opening quote
    let open = lead + key_len + (rest.len() - after.len()) + 1 + after[1..].find('"')? + 1;
    let close = open + line[open..].find('"')?;
    Some((open, close))
}

/// The first version line in `file`.
///
/// Err, naming the file, when it cannot be read as UTF-8 text or holds no version line. The value is not
/// checked here; only a new version is, by `valid`, before `set` writes it.
pub fn find_in(file: &Path) -> Result<Spot, String> {
    let text = std::fs::read_to_string(file).map_err(|e| format!("{}: {e}", file.display()))?;
    for (i, l) in text.lines().enumerate() {
        if let Some((a, b)) = version_on(l) {
            return Ok(Spot {
                file: file.to_path_buf(),
                line: i,
                value: l[a..b].to_string(),
            });
        }
    }
    Err(format!("{}: no version line", file.display()))
}

/// A version the programs can use: numbers separated by dots, 2 to 4 parts.
///
/// ASCII digits only, so no sign, space or pre-release suffix such as `-beta`. Four parts fit a Windows file
/// version (major.minor.build.revision); two cover `1.4`.
pub fn valid(v: &str) -> bool {
    let parts: Vec<&str> = v.split('.').collect();
    (2..=4).contains(&parts.len())
        && parts
            .iter()
            .all(|p| !p.is_empty() && p.chars().all(|c| c.is_ascii_digit()))
}

/// Bump part `part` (0-based: 0 major, 1 minor, 2 patch) and zero the parts after it: 0.2.9 -> 0.3.0.
///
/// A `part` past the last one bumps the last. None when `v` is not `valid`. The view's patch, minor and
/// major buttons call this with 2, 1 and 0.
pub fn bump(v: &str, part: usize) -> Option<String> {
    if !valid(v) {
        return None;
    }
    // valid() allows only digits, so parse can fail only on a part too large for u64
    // Known limitation: such a part (over 20 digits) panics here
    let mut n: Vec<u64> = v.split('.').map(|p| p.parse().unwrap()).collect();
    let part = part.min(n.len() - 1);
    n[part] += 1;
    for x in n.iter_mut().skip(part + 1) {
        *x = 0;
    }
    Some(n.iter().map(u64::to_string).collect::<Vec<_>>().join("."))
}

/// Write `new` into every spot, keeping each file's line endings. Returns the files changed.
///
/// A file already at `new` is left untouched (not rewritten, not listed). Each file is re-read, and its
/// line is checked to still be a version line, so an edit made since `find_in` is noticed instead of
/// overwritten. Err stops at the first problem; files written before it stay written.
///
/// Steps:
/// 1. Refuse a `new` that is not `valid`.
/// 2. Per spot: read the file, split it into lines on its own line ending.
/// 3. Find the version range again on the remembered line; Err when the line is gone or no longer one.
/// 4. Replace just that range and write the lines back joined with the same ending.
pub fn set(spots: &[Spot], new: &str) -> Result<Vec<PathBuf>, String> {
    if !valid(new) {
        return Err(format!("'{new}' is not a version like 1.2.3"));
    }
    let mut changed = vec![];
    for s in spots {
        let text = std::fs::read_to_string(&s.file).map_err(|e| e.to_string())?;
        // a file with any CRLF is taken as CRLF throughout; splitting and joining on the same text keeps
        // every other byte, the final line ending included
        let nl = if text.contains("\r\n") { "\r\n" } else { "\n" };
        let mut lines: Vec<String> = text.split(nl).map(String::from).collect();
        let l = lines
            .get_mut(s.line)
            .ok_or_else(|| format!("{}: file changed", s.file.display()))?;
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

/// Unit tests: the four line spellings, the version rules, and a real two-file write.
#[cfg(test)]
mod tests {
    use super::*;

    // One line per spelling, indented with spaces or a tab, and three near misses that must not match.
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

    // Two to four numeric parts are valid; a patch bump of 0.2.9 gives 0.2.10 (no carry), and a minor or
    // major bump zeroes the later parts.
    #[test]
    fn valid_and_bump() {
        assert!(valid("0.2.0") && valid("1.2") && !valid("1") && !valid("1.x.0") && !valid("1..2"));
        assert_eq!(bump("0.2.9", 2).as_deref(), Some("0.2.10"));
        assert_eq!(bump("0.2.9", 1).as_deref(), Some("0.3.0"));
        assert_eq!(bump("0.2.9", 0).as_deref(), Some("1.0.0"));
        assert_eq!(bump("bad", 0), None);
    }

    // A CRLF Cargo.toml (with a dependency `version` below the package one) and an LF JSON file both change,
    // only on their version line and with their own endings; a second identical set changes nothing, and an
    // invalid version is refused.
    #[test]
    fn set_changes_only_the_first_version_line_and_keeps_crlf() {
        let dir = std::env::temp_dir().join(format!("gc-console-ver-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let toml = dir.join("Cargo.toml");
        std::fs::write(
            &toml,
            "[package]\r\nname = \"x\"\r\nversion = \"0.2.0\"\r\n\r\n[dependencies]\r\nfoo = { version = \"1\" }\r\n",
        )
        .unwrap();
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

// ==== stamp v1 | author=kjFriday | hmac-sha256=30fda3bcb7dc5b15513c2580c10ca7dd51d62001057c78234e79b206c03b0904 ====
