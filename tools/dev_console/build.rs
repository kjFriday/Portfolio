// ==== Generic Company Inc. portfolio ====================================
// Project: dev_console | File: build.rs
// About: Links icon/app.res (the pixel icon as resource 1, plus a DPI-aware manifest) into the exe.
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
// ========================================================================

//! Links icon/app.res (the pixel icon as resource 1, plus a DPI-aware manifest) into the exe.
//!
//! Cargo runs this build script before it compiles the console itself. Explorer, the taskbar and Alt+Tab take
//! an exe's icon from its resource section, not from the window, so the icon has to be linked in; the
//! manifest in the same .res file tells Windows the program scales its own text, so it is not drawn blurry on
//! a high-DPI screen. icon/app.res is made ahead of time by tools/pixel_icons.py and checked in, so building
//! needs no resource compiler.
//!
//! Flow:
//! 1. Tell Cargo to run this script again only when icon/app.res changes.
//! 2. When the target is Windows, pass the .res file to the linker for the binaries (not the tests or
//!    libraries), which accepts a compiled resource file like an object file.

/// Cargo's entry point for the build script; prints the `cargo:` lines that link the resource file.
///
/// Side effects: prints instructions on stdout, which Cargo reads; writes no files.
///
/// Steps:
/// 1. `rerun-if-changed` limits reruns to edits of icon/app.res.
/// 2. `CARGO_CFG_TARGET_OS` is the target (not the host) system, so a cross build to another system skips the
///    link argument.
/// 3. The path is built from `CARGO_MANIFEST_DIR`, so it holds wherever the crate is checked out.
/// 4. `rustc-link-arg-bins` hands the path to the linker for the exe only.
fn main() {
    println!("cargo:rerun-if-changed=icon/app.res");
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows") {
        let res = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("icon")
            .join("app.res");
        println!("cargo:rustc-link-arg-bins={}", res.display());
    }
}

// ==== stamp v1 | author=kjFriday | hmac-sha256=327022f1251903bc9502ee47dac36efb26da0e29e6205da84553051f1d7e8733 ====
