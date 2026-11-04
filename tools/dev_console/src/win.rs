// ==== Generic Company Inc. portfolio ====================================
// Project: dev_console | File: src/win.rs
// About: Windows plumbing shared by the console: the no-console-window flag and PowerShell quoting.
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
// ========================================================================

//! Windows plumbing shared by the console: the no-console-window flag and PowerShell quoting.
//!
//! The console is a GUI program (`windows_subsystem = "windows"` in main.rs), so every console tool it
//! starts (cargo, go, python, curl.exe, taskkill, powershell) would open a black console window of its own
//! unless the child is created with `CREATE_NO_WINDOW`. jobs.rs (every job, so also desktop.rs builds),
//! production.rs (curl.exe) and install.rs (its PowerShell scripts) set it on the `Command` they build.
//!
//! The Start menu shortcut, the Apps & features entry and the desktop shortcuts are made by handing a short
//! PowerShell script to `powershell -Command`. install.rs and desktop.rs pass every path or name spliced into
//! such a script through `ps_quote`, so a folder name holding `$`, a backtick or a quote stays text.

/// Process creation flag: start a console program without a console window, so child tools do not flash one.
///
/// The value is `CREATE_NO_WINDOW` from the Win32 process creation flags (WinBase.h), passed to
/// `CreateProcess` through `std::os::windows::process::CommandExt::creation_flags`. It applies only to console
/// programs; a GUI program started with it still shows its own windows.
#[cfg(windows)]
pub const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// `it's` -> `'it''s'`: a PowerShell single-quoted string, which takes everything else literally.
///
/// Inside single quotes PowerShell expands no `$variables`, no `$(...)` and no backtick escapes; the only
/// special character is the single quote itself, which is written twice. That makes this the one quoting rule
/// needed for any path or text placed in a generated script. The result includes the surrounding quotes.
pub fn ps_quote(s: &str) -> String {
    format!("'{}'", s.replace('\'', "''"))
}

/// Unit tests for the quoting rule.
#[cfg(test)]
mod tests {
    use super::*;

    // A path with a quote and a `$` keeps both literally, the quote doubled; the empty string is `''`.
    #[test]
    fn ps_quote_doubles_single_quotes() {
        assert_eq!(ps_quote(r"C:\Users\o'brien\x $y.lnk"), r"'C:\Users\o''brien\x $y.lnk'");
        assert_eq!(ps_quote(""), "''");
    }
}

// ==== stamp v1 | author=kjFriday | hmac-sha256=1d2cb910a36e2576d453ea4824950ee9fe3e03e1a08a2b0b0ba9542fb7d6665f ====
