// ==== Generic Company Inc. portfolio ====================================
// Project: dev_console | File: src/live.rs
// About: Live mode: notice when a file in a project folder is saved, so its tests can run again.
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
// ========================================================================

//! Live mode: notice when a file in a project folder is saved, so its tests can run again.
//!
//! Live tests work by polling, not by OS change notifications: a background thread started in
//! `App::first_frame` (app.rs) wakes every `[live] interval_ms` (settings.ini), asks `newest` for the latest
//! modification time under each program folder whose Live tests box is ticked, and feeds it to that folder's
//! `Watch`. When `Watch::changed` says yes, the thread sends the program's index to the window, which starts
//! the program's Test action.
//!
//! Polling keeps the code to the standard library and behaves the same on every file system; the cost is one
//! directory walk per ticked program per interval, which the `[live] skip` list keeps small by leaving out
//! build output such as `target`.
//!
//! Defines `Watch`, the per-folder memory of the last time seen.

use std::path::Path;
use std::time::SystemTime;

/// The newest modification time of any file under `dir`, skipping folders named in `skip`.
///
/// `skip` holds bare folder names (not paths), compared without regard to ASCII case, and applies at every
/// depth. Folders themselves do not count, only files. Returns None when `dir` holds no readable file
/// (or does not exist). Unreadable folders and entries are passed over silently, since a file being saved
/// can vanish between the listing and the metadata call.
///
/// Steps:
/// 1. Walk the tree depth-first with an explicit stack, so deep trees cannot overflow the call stack.
/// 2. Push each subfolder unless its name is in `skip`.
/// 3. Keep the largest file modification time seen.
pub fn newest(dir: &Path, skip: &[String]) -> Option<SystemTime> {
    let mut best: Option<SystemTime> = None;
    let mut stack = vec![dir.to_path_buf()];
    while let Some(d) = stack.pop() {
        let Ok(entries) = std::fs::read_dir(&d) else { continue };
        for e in entries.flatten() {
            // file_type does not follow symbolic links, so a link to a folder is read as a file and the
            // walk cannot loop
            let Ok(ft) = e.file_type() else { continue };
            if ft.is_dir() {
                if !skip
                    .iter()
                    .any(|s| e.file_name().to_string_lossy().eq_ignore_ascii_case(s))
                {
                    stack.push(e.path());
                }
            } else if let Ok(m) = e.metadata().and_then(|m| m.modified()) {
                best = Some(best.map_or(m, |b| b.max(m)));
            }
        }
    }
    best
}

/// Tracks one folder; `changed` is true when something newer than the last look appeared.
///
/// The watcher thread keeps one per program and replaces it with a fresh `Watch::default()` while that
/// program's Live tests box is off, so turning the box on never fires for saves made while it was off.
#[derive(Default)]
pub struct Watch {
    /// The newest modification time seen so far; None until the first look that found a file.
    seen: Option<SystemTime>,
}

// The one decision a Watch makes.
impl Watch {
    /// Whether `now` (the folder's current `newest` time) is later than the time seen at the last look;
    /// then remembers `now`.
    ///
    /// The first look only records the time and returns false, so opening Live tests does not start a test
    /// run at once. A look that found no file (None) returns false and keeps the old time, so a folder that is
    /// briefly unreadable does not fire when it comes back unchanged.
    pub fn changed(&mut self, now: Option<SystemTime>) -> bool {
        let fresh = match (self.seen, now) {
            (Some(a), Some(b)) => b > a,
            (None, _) => false, // first look only records the time
            (Some(_), None) => false,
        };
        if now.is_some() {
            self.seen = now;
        }
        fresh
    }
}

/// Unit tests for the watch rule and the folder walk.
#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    // The first look and a repeat of the same time stay quiet, a later time fires, and None never fires.
    #[test]
    fn watch_fires_only_on_newer() {
        let t = SystemTime::UNIX_EPOCH + Duration::from_secs(100);
        let mut w = Watch::default();
        assert!(!w.changed(Some(t)));
        assert!(!w.changed(Some(t)));
        assert!(w.changed(Some(t + Duration::from_secs(1))));
        assert!(!w.changed(None));
    }

    // A file written later inside a skipped `target` folder leaves the result unchanged, but counts once the
    // skip list is empty; the 30 ms sleep makes the second file's time strictly later on NTFS.
    #[test]
    fn newest_skips_named_folders() {
        let dir = std::env::temp_dir().join(format!("gc-console-live-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(dir.join("src")).unwrap();
        std::fs::create_dir_all(dir.join("target")).unwrap();
        std::fs::write(dir.join("src").join("a.rs"), "a").unwrap();
        let before = newest(&dir, &["target".into()]).unwrap();
        std::thread::sleep(Duration::from_millis(30));
        std::fs::write(dir.join("target").join("b.o"), "b").unwrap();
        assert_eq!(newest(&dir, &["target".into()]), Some(before));
        assert!(newest(&dir, &[]).unwrap() > before);
        std::fs::remove_dir_all(&dir).unwrap();
    }
}

// ==== stamp v1 | author=kjFriday | hmac-sha256=543bd9adcd5b2efcbc842fc04ea84ae1a177bf42efa4a4bacc9fbdeef712c7a4 ====
