// ==== Generic Company Inc. portfolio ====================================
// Project: portfolio | File: dev_console/src/live.rs
// About: Live mode: notice when a file in a project folder is saved, so its tests can run again.
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
// ========================================================================

//! Live mode: notice when a file in a project folder is saved, so its tests can run again.

use std::path::Path;
use std::time::SystemTime;

/// The newest modification time of any file under `dir`, skipping folders named in `skip`.
pub fn newest(dir: &Path, skip: &[String]) -> Option<SystemTime> {
    let mut best: Option<SystemTime> = None;
    let mut stack = vec![dir.to_path_buf()];
    while let Some(d) = stack.pop() {
        let Ok(entries) = std::fs::read_dir(&d) else { continue };
        for e in entries.flatten() {
            let Ok(ft) = e.file_type() else { continue };
            if ft.is_dir() {
                if !skip.iter().any(|s| e.file_name().to_string_lossy().eq_ignore_ascii_case(s)) {
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
#[derive(Default)]
pub struct Watch {
    seen: Option<SystemTime>,
}

impl Watch {
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    #[test]
    fn watch_fires_only_on_newer() {
        let t = SystemTime::UNIX_EPOCH + Duration::from_secs(100);
        let mut w = Watch::default();
        assert!(!w.changed(Some(t)));
        assert!(!w.changed(Some(t)));
        assert!(w.changed(Some(t + Duration::from_secs(1))));
        assert!(!w.changed(None));
    }

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

// ==== stamp v1 | author=kjFriday | hmac-sha256=51a7bb68ab446d906b6ef1e6f51f3aea41b9042eb46e778a2e01aa1cebaf9ef2 ====
