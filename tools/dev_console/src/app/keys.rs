// ==== Generic Company Inc. portfolio ====================================
// Project: dev_console | File: src/app/keys.rs
// About: Keyboard controls: the shortcuts named in controls.ini, and the key text that buttons and...
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
// ========================================================================

//! Keyboard controls: the shortcuts named in controls.ini, and the key text that buttons and hover tips show.

use eframe::egui::{self, Key, KeyboardShortcut};

use super::{App, TEST, View};
use crate::registry::Action;

impl App {
    /// True once per press of the control named `action` in controls.ini.
    fn pressed(&self, ctx: &egui::Context, action: &str) -> bool {
        let Some(sc) = self.cfg.controls.get(action) else {
            return false;
        };
        // Ctrl+Plus arrives as Ctrl+= on most keyboards; accept both.
        let alt = (sc.logical_key == Key::Plus).then(|| KeyboardShortcut::new(sc.modifiers, Key::Equals));
        ctx.input_mut(|i| i.consume_shortcut(sc) || alt.is_some_and(|a| i.consume_shortcut(&a)))
    }

    /// Apply the controls pressed this frame.
    pub(super) fn keys(&mut self, ctx: &egui::Context) {
        let step = self.cfg.number("view", "zoom_step", 0.1);
        if self.pressed(ctx, "zoom_in") {
            self.set_zoom(ctx, self.zoom + step);
        }
        if self.pressed(ctx, "zoom_out") {
            self.set_zoom(ctx, self.zoom - step);
        }
        if self.pressed(ctx, "zoom_reset") {
            self.set_zoom(ctx, 1.0);
        }
        for (v, _, key, _) in View::ALL {
            if self.pressed(ctx, key) {
                self.view = v;
            }
        }
        if self.pressed(ctx, "test_all") {
            (0..self.programs.len()).for_each(|p| self.start(ctx, p, TEST));
        }
        if self.pressed(ctx, "desktop_shortcuts") {
            self.desktop_job(ctx, true);
        }
        let n = self.programs.len().max(1);
        if self.pressed(ctx, "next") {
            self.selected = (self.selected + 1) % n;
        }
        if self.pressed(ctx, "previous") {
            self.selected = (self.selected + n - 1) % n;
        }
        if self.pressed(ctx, "toggle_live") && !self.programs.is_empty() {
            let p = self.selected;
            self.set_live(p, !self.is_live(p));
        }
        for (a, act) in Action::ALL.iter().enumerate() {
            if self.pressed(ctx, &act.label().to_lowercase()) {
                self.start(ctx, self.selected, a);
            }
        }
    }

    /// " (Ctrl+L)" for a control, or "".
    pub(super) fn hint(&self, action: &str) -> String {
        self.cfg
            .controls
            .get(action)
            .map(|sc| format!(" ({})", sc_text(sc)))
            .unwrap_or_default()
    }

    /// Hover text with the control's keys on a line of its own.
    pub(super) fn tip(&self, text: &str, action: &str) -> String {
        match self.cfg.controls.get(action) {
            Some(sc) => format!("{text}\nKeys: {} (change them in controls.ini)", sc_text(sc)),
            None => text.to_string(),
        }
    }
}

/// A shortcut as text, such as `Ctrl+Shift+T` or `F5`.
pub(super) fn sc_text(sc: &KeyboardShortcut) -> String {
    let mut s = String::new();
    if sc.modifiers.ctrl || sc.modifiers.command {
        s.push_str("Ctrl+");
    }
    if sc.modifiers.alt {
        s.push_str("Alt+");
    }
    if sc.modifiers.shift {
        s.push_str("Shift+");
    }
    s.push_str(sc.logical_key.name());
    s
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config;

    #[test]
    fn shortcut_text_reads_back() {
        let sc = config::shortcut("Ctrl+Shift+T").unwrap().unwrap();
        assert_eq!(sc_text(&sc), "Ctrl+Shift+T");
        assert_eq!(sc_text(&config::shortcut("F5").unwrap().unwrap()), "F5");
    }
}

// ==== stamp v1 | author=kjFriday | hmac-sha256=61cfe3537d97347a1c815c6250838d64b19ab46882c9b5e61ffd7d7590603e6e ====
