// ==== Generic Company Inc. portfolio ====================================
// Project: dev_console | File: src/app/views/versions.rs
// About: The Versions & commands view: the selected program's version lines and its commands.
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
// ========================================================================

//! The Versions & commands view: the selected program's version lines and its commands.
//!
//! The top half shows the program's version in each of its version files, with the bump and Apply buttons;
//! the bottom half edits the commands the console runs for it, saved to programs.ini. The frame loop in
//! app/views.rs draws it when its tab is picked, for the program selected in the sidebar. The work is in
//! app.rs (`load_versions`, `apply_version`, `save_commands`) and versions.rs.
//!
//! Top to bottom:
//! 1. A grid of version files and their values; values that disagree are yellow.
//! 2. The New version box, Patch/Minor/Major +1, Apply version and Reload.
//! 3. A grid of every command field, each an editable box; a changed one is marked with *.
//! 4. Save commands, Revert, and "unsaved changes".
//! 5. The last note from a save or a version change.

use eframe::egui::{self, Color32, RichText};

use super::{GREEN, RED};
use crate::app::App;
use crate::{registry, versions};

// The view's body, drawn as part of App.
impl App {
    /// The newest note in green or red, with a button that clears them all.
    ///
    /// Only the last note shows, so the line does not grow with every save; nothing is drawn when there are no
    /// notes.
    fn notes_ui(&mut self, ui: &mut egui::Ui) {
        if self.notes.is_empty() {
            return;
        }
        ui.horizontal(|ui| {
            let (ok, text) = self.notes.last().unwrap().clone();
            ui.colored_label(if ok { GREEN } else { RED }, text);
            if ui.small_button("✕").on_hover_text("Clear these messages.").clicked() {
                self.notes.clear();
            }
        });
    }

    /// Draw the Versions & commands view for the selected program; `ctx` is passed to Apply's restamp job.
    ///
    /// Steps:
    /// 1. Reread the version spots when another program was picked since the last read.
    /// 2. The version grid: each file's path relative to the root (hover for the line number) and its value.
    ///    All values are compared; when they differ they turn yellow, since Apply exists to make them agree.
    ///    A file with no version line shows its error in red, with an empty second cell to keep the grid's
    ///    rows whole.
    /// 3. The New version box (90 px, enough for a version) and the bump buttons, which bump the first value
    ///    found. Apply version is enabled only for a valid version and a found root.
    /// 4. The commands grid: one row per field in registry::FIELDS, label then box. A label turns yellow with
    ///    * when the field differs from the saved programs. The box fills the row (`f32::INFINITY` width) in
    ///    the code-editor style (monospace), and its tip shows how the console splits the text into words,
    ///    each in brackets (desktop_build as its steps joined by "then"), so quoting mistakes show before
    ///    saving.
    /// 5. Save commands and Revert, enabled only with unsaved changes; Revert copies the programs back over
    ///    the edits.
    /// 6. The notes line.
    pub(super) fn versions_view(&mut self, ui: &mut egui::Ui, ctx: &egui::Context) {
        if self.ver.for_program != Some(self.selected) {
            self.load_versions();
        }
        let p = self.selected;
        let name = self.programs[p].name.clone();
        ui.heading(format!("{name} — version"))
            .on_hover_text("Where this program's version is written, from version_files in programs.ini.");
        let values: Vec<String> = self.ver.spots.iter().flatten().map(|s| s.value.clone()).collect();
        let agree = values.windows(2).all(|w| w[0] == w[1]);
        egui::Grid::new("spots").num_columns(2).striped(true).show(ui, |ui| {
            for s in &self.ver.spots {
                match s {
                    Ok(s) => {
                        let rel = self
                            .root
                            .as_ref()
                            .and_then(|r| s.file.strip_prefix(r).ok())
                            .unwrap_or(&s.file);
                        ui.monospace(rel.display().to_string())
                            .on_hover_text(format!("Line {} of this file", s.line + 1));
                        let text = RichText::new(&s.value).monospace();
                        ui.label(if agree { text } else { text.color(Color32::YELLOW) })
                            .on_hover_text(if agree {
                                "Matches the other files."
                            } else {
                                "Differs from another file: Apply sets them all to the same version."
                            });
                    }
                    Err(e) => {
                        ui.colored_label(RED, e)
                            .on_hover_text("Fix version_files in programs.ini, or add a version line to the file.");
                        ui.label("");
                    }
                }
                ui.end_row();
            }
        });
        ui.horizontal_wrapped(|ui| {
            ui.label("New version").on_hover_text("Numbers separated by dots, such as 0.3.0.");
            ui.add(egui::TextEdit::singleline(&mut self.ver.new_version).desired_width(90.0))
                .on_hover_text("Type a version, or use the buttons to bump the current one.");
            let base = values.first().cloned().unwrap_or_default();
            for (part, label, help) in [(2, "Patch +1", "0.2.0 → 0.2.1: fixes only"), (1, "Minor +1", "0.2.0 → 0.3.0: new features"), (0, "Major +1", "0.2.0 → 1.0.0: breaking changes")] {
                if ui.button(label).on_hover_text(help).clicked() {
                    if let Some(v) = versions::bump(&base, part) {
                        self.ver.new_version = v;
                    }
                }
            }
            let valid = versions::valid(self.ver.new_version.trim());
            if ui
                .add_enabled(valid && self.root.is_some(), egui::Button::new("Apply version"))
                .on_hover_text("Write this version into every file above, then renew the stamps of the source files you changed (tools/stamp.py --restamp). Nothing is committed.")
                .on_disabled_hover_text("Enter a version like 1.2.3 first.")
                .clicked()
            {
                self.apply_version(ctx);
            }
            if ui.small_button("Reload").on_hover_text("Read the version files again (after editing them elsewhere).").clicked() {
                self.load_versions();
            }
        });
        ui.add_space(10.0);
        ui.heading(format!("{name} — commands"))
            .on_hover_text("What the console runs for this program. Saved to config/programs.ini.");
        egui::Grid::new("commands").num_columns(2).striped(true).show(ui, |ui| {
            for (key, label, help) in registry::FIELDS {
                let changed = self.ver.edit[p].field(key) != self.programs[p].field(key);
                let text = if changed {
                    RichText::new(format!("{label} *")).color(Color32::YELLOW)
                } else {
                    RichText::new(label)
                };
                ui.label(text).on_hover_text(help);
                let words = if key == "desktop_build" {
                    registry::steps(self.ver.edit[p].field(key))
                        .iter()
                        .map(|s| format!("[{}]", s.join("] [")))
                        .collect::<Vec<_>>()
                        .join("\nthen ")
                } else {
                    format!("[{}]", registry::split_args(self.ver.edit[p].field(key)).join("] ["))
                };
                if let Some(v) = self.ver.edit[p].field_mut(key) {
                    ui.add(egui::TextEdit::singleline(v).desired_width(f32::INFINITY).code_editor())
                        .on_hover_text(format!("{help}\n\nAs the console splits it:\n{words}"));
                }
                ui.end_row();
            }
        });
        ui.horizontal(|ui| {
            let dirty = self.commands_dirty();
            let file = self
                .cfg
                .programs_file
                .as_ref()
                .map(|f| f.display().to_string())
                .unwrap_or_default();
            if ui
                .add_enabled(dirty, egui::Button::new("Save commands"))
                .on_hover_text(format!("Write every program's commands to {file}."))
                .clicked()
            {
                self.save_commands();
            }
            if ui
                .add_enabled(dirty, egui::Button::new("Revert"))
                .on_hover_text("Throw away unsaved command changes.")
                .clicked()
            {
                self.ver.edit = self.programs.clone();
            }
            if dirty {
                ui.colored_label(Color32::YELLOW, "unsaved changes")
                    .on_hover_text("Fields marked * differ from the saved programs.ini.");
            }
        });
        self.notes_ui(ui);
    }
}

// ==== stamp v1 | author=kjFriday | hmac-sha256=7aaa751613d75243c54daf44ff5ea6b69795344ffab31518b313420f31123c22 ====
