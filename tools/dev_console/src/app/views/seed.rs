// ==== Generic Company Inc. portfolio ====================================
// Project: dev_console | File: src/app/views/seed.rs
// About: The Seed data view: the shared database, its row counts, backups and seed buttons.
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
// ========================================================================

//! The Seed data view: the shared database, its row counts, backups and seed buttons.
//!
//! Every portfolio program reads one shared SQLite file. This view shows which file is in use, how many rows
//! each table holds and the dated backups beside it, and runs the CRUD Hub's own seed scripts on it (the
//! console never writes the database itself). The frame loop in app/views.rs draws it when its tab is picked;
//! the buttons call `seed_click` and `refresh_seed` in app.rs, and seed.rs builds the commands.
//!
//! What the view shows, top to bottom:
//! 1. The Database box with Default and Open folder, then the file's size and age.
//! 2. A button per op: Refresh counts, Back up now, Reseed, Rebuild fresh, Export mock snapshots. The
//!    destructive ones ask for a second click.
//! 3. Two columns: rows per table on the left, the backups with Restore selected on the right.

use std::path::Path;

use eframe::egui::{self, Key, RichText};

use super::RED;
use crate::app::App;
use crate::seed;

// The view's body, drawn as part of App.
impl App {
    /// Draw the Seed data view; `ctx` is passed on to the seed jobs the buttons start.
    ///
    /// Steps:
    /// 1. On first show, read the backups and start a Counts job, so the view is not empty.
    /// 2. The Database box reloads on Enter. egui has no "submitted" event for a single-line box: the box loses
    ///    focus when Enter is pressed, so `lost_focus` plus Enter this frame means submitted, while a click
    ///    elsewhere (focus lost without Enter) does not reload.
    /// 3. Default goes back to the shared database. Open folder runs `explorer /select,<file>`, which opens
    ///    the folder with the file highlighted, or just the folder when the file does not exist yet.
    /// 4. The op buttons, all disabled while any seed job runs. An armed button turns red and reads
    ///    "Click again: ..."; its tip says it asks for a second click.
    /// 5. `ui.columns(2)` splits the rest in two equal halves. Left: a striped grid of tables and counts with a
    ///    total, or why there are none. Right: the backups in a scroll area capped at 180 px (so a long list
    ///    does not push Restore off screen), each selectable, then the Restore button, which needs a pick.
    pub(super) fn seed_view(&mut self, ui: &mut egui::Ui, ctx: &egui::Context) {
        if !self.seed.loaded {
            self.refresh_seed(ctx);
        }
        ui.heading("CRUD Hub seed data").on_hover_text("The shared SQLite file every program reads. All changes go through the CRUD Hub's own seed.py and export_mock.py.");
        ui.horizontal_wrapped(|ui| {
            ui.label("Database").on_hover_text("The file to work on. Defaults to GENERIC_COMPANY_DB, or the shared file under %LOCALAPPDATA%\\Generic Company Inc.");
            let r = ui.add(egui::TextEdit::singleline(&mut self.seed.db).desired_width(420.0)).on_hover_text("Path to the database file. Press Enter to reload.");
            if r.lost_focus() && ui.input(|i| i.key_pressed(Key::Enter)) {
                self.refresh_seed(ctx);
            }
            if ui.button("Default").on_hover_text("Go back to the shared database the programs use by default.").clicked() {
                let env = |k: &str| std::env::var(k).ok();
                self.seed.db = seed::default_db(&env).map(|p| p.display().to_string()).unwrap_or_default();
                self.refresh_seed(ctx);
            }
            if ui.button("Open folder").on_hover_text("Show the database's folder in Explorer.").clicked() {
                let db = self.db_path();
                let _ = if db.is_file() {
                    std::process::Command::new("explorer").arg(format!("/select,{}", db.display())).spawn()
                } else {
                    std::process::Command::new("explorer").arg(db.parent().unwrap_or(Path::new("."))).spawn()
                };
            }
        });
        ui.weak(seed::describe(&self.db_path()))
            .on_hover_text("Size of the file and when it last changed.");
        ui.add_space(6.0);

        ui.horizontal_wrapped(|ui| {
            let busy = self.seed_busy();
            for op in [
                seed::Op::Counts,
                seed::Op::Backup,
                seed::Op::Reseed,
                seed::Op::Fresh,
                seed::Op::Export,
            ] {
                let armed = self.seed.armed.map(|(o, _)| o) == Some(op);
                let label = if armed {
                    RichText::new(format!("Click again: {}", op.label())).color(RED)
                } else {
                    RichText::new(op.label())
                };
                let tip = if op.needs_confirm() {
                    format!("{}\n\nAsks for a second click.", op.help())
                } else {
                    op.help().to_string()
                };
                if ui
                    .add_enabled(!busy, egui::Button::new(label))
                    .on_hover_text(tip)
                    .on_disabled_hover_text("Waiting for the running seed job.")
                    .clicked()
                {
                    self.seed_click(ctx, op);
                }
            }
        });
        ui.add_space(6.0);

        ui.columns(2, |cols| {
            cols[0]
                .strong("Rows per table")
                .on_hover_text("Read from the database; refreshed after every seed job.");
            match (&self.seed.counts, &self.seed.counts_error) {
                (Some(c), _) if !c.is_empty() => {
                    egui::Grid::new("counts")
                        .num_columns(2)
                        .striped(true)
                        .show(&mut cols[0], |ui| {
                            let total: u64 = c.iter().map(|(_, n)| n).sum();
                            for (t, n) in c {
                                ui.monospace(t);
                                ui.monospace(n.to_string());
                                ui.end_row();
                            }
                            ui.strong("total");
                            ui.strong(total.to_string());
                            ui.end_row();
                        });
                }
                (Some(_), _) => {
                    cols[0].weak("The file has no tables yet.");
                }
                (None, Some(e)) => {
                    cols[0]
                        .colored_label(RED, e)
                        .on_hover_text("Could not read the file. Is it a database?");
                }
                (None, None) => {
                    cols[0].weak(if self.db_path().is_file() {
                        "Reading…"
                    } else {
                        "No database file yet."
                    });
                }
            }

            cols[1].strong("Backups").on_hover_text(
                "Dated copies beside the database (made by Reseed, Back up now and Restore). Pick one to restore it.",
            );
            if self.seed.backups.is_empty() {
                cols[1].weak("None yet.");
            }
            egui::ScrollArea::vertical()
                .id_salt("backups")
                .max_height(180.0)
                .show(&mut cols[1], |ui| {
                    for (i, b) in self.seed.backups.iter().enumerate() {
                        let text = format!("{}   {}", b.when, seed::size(b.size));
                        if ui
                            .selectable_label(self.seed.pick == Some(i), text)
                            .on_hover_text(b.path.display().to_string())
                            .clicked()
                        {
                            self.seed.pick = Some(i);
                        }
                    }
                });
            let op = seed::Op::Restore;
            let armed = self.seed.armed.map(|(o, _)| o) == Some(op);
            let label = if armed {
                RichText::new("Click again: Restore").color(RED)
            } else {
                RichText::new("Restore selected")
            };
            let can = self.seed.pick.is_some() && !self.seed_busy();
            if cols[1]
                .add_enabled(can, egui::Button::new(label))
                .on_hover_text(format!("{}\n\nAsks for a second click.", op.help()))
                .on_disabled_hover_text("Pick a backup first.")
                .clicked()
            {
                self.seed_click(ctx, op);
            }
        });
    }
}

// ==== stamp v1 | author=kjFriday | hmac-sha256=1af276ea77a61f43edceab7d1e23f20ee0d74e70d70c70b436b1cee168a79d4c ====
