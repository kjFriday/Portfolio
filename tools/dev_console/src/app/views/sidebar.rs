// ==== Generic Company Inc. portfolio ====================================
// Project: dev_console | File: src/app/views/sidebar.rs
// About: The left panel: every program with its last test mark, Test all, the desktop shortcut...
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
// ========================================================================

//! The left panel: every program with its last test mark, Test all, the desktop shortcut buttons, the text
//! size, config warnings, About and the portfolio root.

use eframe::egui::{self, Color32};

use super::{GREEN, badge, status_text};
use crate::app::{App, Kind, TEST};
use crate::{VERSION, install};

impl App {
    pub(super) fn sidebar(&mut self, ui: &mut egui::Ui, ctx: &egui::Context) {
        ui.heading("Programs")
            .on_hover_text("Every program in config/programs.ini. Pick one to work on it.");
        ui.separator();
        for i in 0..self.programs.len() {
            let p = self.programs[i].clone();
            ui.horizontal(|ui| {
                let (mark, col) = badge(&self.last[i][TEST]);
                ui.colored_label(col, mark).on_hover_text(match &self.last[i][TEST] {
                    None => "Tests not run yet".to_string(),
                    Some(s) => format!("Last test run: {}", status_text(s)),
                });
                if ui
                    .selectable_label(self.selected == i, &p.name)
                    .on_hover_text(format!("{}\nFolder: {}\n{} program", p.name, p.dir, p.lang.label()))
                    .clicked()
                {
                    self.selected = i;
                }
                ui.weak(p.lang.label());
                if self.is_live(i) {
                    ui.colored_label(GREEN, "live")
                        .on_hover_text("Live tests are on: saving a file in this program's folder runs its tests.");
                }
            });
        }
        ui.separator();
        if ui
            .button(format!("Test all{}", self.hint("test_all")))
            .on_hover_text("Run every program's tests at once. Each result shows as a mark beside its name.")
            .clicked()
        {
            (0..self.programs.len()).for_each(|p| self.start(ctx, p, TEST));
        }
        ui.add_space(8.0);
        let can = self.root.is_some() && self.cfg.user_dir.is_some() && !self.busy(Kind::Desktop);
        if ui
            .add_enabled(can, egui::Button::new(format!("Desktop shortcuts{}", self.hint("desktop_shortcuts"))))
            .on_hover_text("Build every program from source, then put a versioned shortcut to each build and to each source folder on the desktop.")
            .clicked()
        {
            self.desktop_job(ctx, true);
        }
        if ui
            .add_enabled(can, egui::Button::new("Remove desktop shortcuts"))
            .on_hover_text("Delete every desktop shortcut the console placed. Nothing else on the desktop is touched.")
            .clicked()
        {
            self.desktop_job(ctx, false);
        }
        ui.add_space(8.0);
        ui.horizontal(|ui| {
            ui.weak(format!("Text {:.0}%", self.zoom * 100.0))
                .on_hover_text("Text and UI size. It is saved between runs.");
            let step = self.cfg.number("view", "zoom_step", 0.1);
            if ui
                .small_button("−")
                .on_hover_text(self.tip("Smaller text", "zoom_out"))
                .clicked()
            {
                self.set_zoom(ctx, self.zoom - step);
            }
            if ui
                .small_button("+")
                .on_hover_text(self.tip("Larger text", "zoom_in"))
                .clicked()
            {
                self.set_zoom(ctx, self.zoom + step);
            }
            if ui
                .small_button("100%")
                .on_hover_text(self.tip("Normal text size", "zoom_reset"))
                .clicked()
            {
                self.set_zoom(ctx, 1.0);
            }
        });
        for w in &self.cfg.warnings {
            ui.colored_label(Color32::YELLOW, w)
                .on_hover_text("A problem in the config files; the rest still works.");
        }
        ui.add_space(8.0);
        ui.collapsing("About", |ui| {
            ui.label(format!("{} {VERSION}", install::NAME));
            ui.weak("Generic Company Inc. is fictional. AGPL-3.0.");
            ui.weak("Icon: application_xp_terminal.png from the Silk icon set by Mark James, CC BY 2.5; enlarged by whole pixels.");
            ui.hyperlink_to("CC BY 2.5", "http://creativecommons.org/licenses/by/2.5/");
        })
        .header_response
        .on_hover_text("Version, licence and icon credit.");
        if let Some(root) = &self.root {
            ui.add_space(8.0);
            ui.weak(format!("Root: {}", root.display()))
                .on_hover_text("The portfolio folder (found by looking upward for RULES.md).");
        }
    }
}

// ==== stamp v1 | author=kjFriday | hmac-sha256=70539e978d67d0f6e767ee1567c1487b00b40503411adf993c060839dd443c90 ====
