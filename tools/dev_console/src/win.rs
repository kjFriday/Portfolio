// ==== Generic Company Inc. portfolio ====================================
// Project: dev_console | File: src/win.rs
// About: Windows plumbing used across the console: the flag that keeps child processes from...
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
// ========================================================================

//! Windows plumbing used across the console: the flag that keeps child processes from opening a console window,
//! and PowerShell quoting.

/// Process creation flag: start a console program without a console window, so child tools do not flash one.
#[cfg(windows)]
pub const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// `it's` -> `'it''s'`: a PowerShell single-quoted string, which takes everything else literally.
pub fn ps_quote(s: &str) -> String {
    format!("'{}'", s.replace('\'', "''"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ps_quote_doubles_single_quotes() {
        assert_eq!(ps_quote(r"C:\Users\o'brien\x $y.lnk"), r"'C:\Users\o''brien\x $y.lnk'");
        assert_eq!(ps_quote(""), "''");
    }
}

// ==== stamp v1 | author=kjFriday | hmac-sha256=745a814abb4fa29dc99370a6b749b243aed7fef4c33d26867041803df164fa51 ====
