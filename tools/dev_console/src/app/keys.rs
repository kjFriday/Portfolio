// ==== Generic Company Inc. portfolio ====================================
// Project: dev_console | File: src/app/keys.rs
// About: Keyboard controls: the shortcuts named in controls.ini, and the key text that tips show.
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
// ========================================================================

//! Keyboard controls: the shortcuts named in controls.ini, and the key text that tips show.
//!
//! Every key the console answers to is named in controls.ini (built in, then the copy beside the program,
//! then the user's own), so none is hard-coded here: this file maps control names such as `zoom_in` or
//! `view_seed` to actions. The frame loop in app/views.rs calls `keys` once per frame, after the job events
//! and before the panels; the views call `hint` and `tip` to show each button's keys.
//!
//! Flow of one key press:
//! 1. egui collects the frame's key events.
//! 2. `keys` asks `pressed` about each control in turn.
//! 3. `pressed` consumes a matching shortcut, so the same press is not seen again later in the frame.
//! 4. `keys` runs the action: zoom, switch view, Test all, desktop shortcuts, pick the next or previous
//!    program, toggle Live tests, or one of the Run actions on the selected program.

use eframe::egui::{self, Key, KeyboardShortcut};

use super::{App, TEST, View};
use crate::registry::Action;

// The control lookups and the per-frame key handler.
impl App {
    /// True once per press of the control named `action` in controls.ini.
    ///
    /// False when controls.ini gives the control no keys. `consume_shortcut` removes the matching event, so
    /// a press counts once even though `keys` asks about many controls in the same frame.
    fn pressed(&self, ctx: &egui::Context, action: &str) -> bool {
        let Some(sc) = self.cfg.controls.get(action) else {
            return false;
        };
        // Ctrl+Plus arrives as Ctrl+= on most keyboards; accept both.
        let alt = (sc.logical_key == Key::Plus).then(|| KeyboardShortcut::new(sc.modifiers, Key::Equals));
        ctx.input_mut(|i| i.consume_shortcut(sc) || alt.is_some_and(|a| i.consume_shortcut(&a)))
    }

    /// Apply the controls pressed this frame.
    ///
    /// Called once per frame by the frame loop. Each control is checked even when an earlier one fired, so
    /// two different shortcuts pressed in the same frame both act.
    ///
    /// Steps:
    /// 1. zoom_in, zoom_out and zoom_reset change the text size by `zoom_step` (settings.ini) or back to 100%.
    /// 2. Each view's key (view_run, view_versions, ...) switches to that view.
    /// 3. test_all starts every program's tests; desktop_shortcuts builds and places the shortcuts.
    /// 4. next and previous move the selection, wrapping around the list (`max(1)` avoids a division by
    ///    zero with no programs; adding n - 1 instead of subtracting 1 keeps the unsigned index from going
    ///    below zero).
    /// 5. toggle_live flips Live tests for the selected program.
    /// 6. Each Run action has a control named after its label in lower case (build, test, run, ...), which
    ///    starts it on the selected program.
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
    ///
    /// Appended to a button's label, so the keys are visible without hovering; empty when the control has no
    /// keys, so the label stays clean.
    pub(super) fn hint(&self, action: &str) -> String {
        self.cfg
            .controls
            .get(action)
            .map(|sc| format!(" ({})", sc_text(sc)))
            .unwrap_or_default()
    }

    /// Hover text with the control's keys on a line of its own.
    ///
    /// `text` is the help; `action` the control name. The extra line also says where to change the keys. A
    /// control with no keys gets the help alone.
    pub(super) fn tip(&self, text: &str, action: &str) -> String {
        match self.cfg.controls.get(action) {
            Some(sc) => format!("{text}\nKeys: {} (change them in controls.ini)", sc_text(sc)),
            None => text.to_string(),
        }
    }
}

/// A shortcut as text, such as `Ctrl+Shift+T` or `F5`.
///
/// The modifiers come in a fixed order (Ctrl, Alt, Shift) and use the names config::shortcut accepts, so the
/// text parses back to the same shortcut. config.rs sets both `ctrl` and `command` for Ctrl, so either one prints
/// as Ctrl; the key's name comes from egui.
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

/// Tests for the key text.
#[cfg(test)]
mod tests {
    use super::*;
    use crate::config;

    /// A shortcut parsed from text prints back as the same text, with and without modifiers.
    #[test]
    fn shortcut_text_reads_back() {
        let sc = config::shortcut("Ctrl+Shift+T").unwrap().unwrap();
        assert_eq!(sc_text(&sc), "Ctrl+Shift+T");
        assert_eq!(sc_text(&config::shortcut("F5").unwrap().unwrap()), "F5");
    }
}

// ==== stamp v1 | author=kjFriday | hmac-sha256=88791ce6f07774cf7f6e1f162c93a6ccb7a725be2fd162b796c79e833217b4ad ====
