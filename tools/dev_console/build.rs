// ==== Generic Company Inc. portfolio ====================================
// Project: dev_console | File: build.rs
// About: Links icon/app.res (the pixel icon as resource 1, plus a DPI-aware manifest) into the exe.
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
// ========================================================================

// Links icon/app.res (the pixel icon as resource 1, plus a DPI-aware manifest) into the exe.
fn main() {
    println!("cargo:rerun-if-changed=icon/app.res");
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows") {
        let res = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("icon")
            .join("app.res");
        println!("cargo:rustc-link-arg-bins={}", res.display());
    }
}

// ==== stamp v1 | author=kjFriday | hmac-sha256=ac485da0fd3bceb7923a6a5c7c602db1df3014d195d46f36257347caf1b00f23 ====
