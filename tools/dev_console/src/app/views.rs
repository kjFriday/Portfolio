// ==== Generic Company Inc. portfolio ====================================
// Project: dev_console | File: src/app/views.rs
// About: Drawing: the panels of each frame, the view tabs, the Run bar, the job tabs and the log.
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
// ========================================================================

//! Drawing: the panels of each frame, the view tabs, the Run bar, the job tabs and the log.
//!
//! eframe calls `ui` (the `eframe::App` trait) for every frame; that is the console's frame loop. egui is an
//! immediate-mode library: nothing on screen is kept between frames, so each frame draws the whole window
//! again from `App`'s state, and a button's `clicked()` is checked right where it is drawn. The views' own
//! bodies are in views/: sidebar.rs (the program list on the left), versions.rs, seed.rs and production.rs.
//!
//! Layout of one frame, in the order egui needs it (side and top panels first, so the central panel gets
//! what is left):
//! 1. Left panel: the sidebar.
//! 2. Top panel "actions": the view tabs, then the Run bar or a one-line note for the other views.
//! 3. Top panel "jobs": one tab per job, newest first.
//! 4. Central panel: the view's body (scrolling, at most 60% of the height) above the shown job's log.

/// The live-production view.
mod production;
/// The Seed data view.
mod seed;
/// The program list and the controls on the left.
mod sidebar;
/// The Versions & commands view.
mod versions;

use std::path::{Path, PathBuf};
use std::time::Duration;

use eframe::egui::{self, Color32, RichText};

use super::{App, Kind, View};
use crate::jobs::Status;
use crate::registry::{self, Action};

/// Passed, finished, running fine. Softer than pure green, so it reads on egui's dark and light themes.
const GREEN: Color32 = Color32::from_rgb(90, 190, 110);
/// Failed, or a destructive button waiting for its second click. Softer than pure red for the same reason.
const RED: Color32 = Color32::from_rgb(220, 90, 80);

// The frame loop eframe calls.
impl eframe::App for App {
    /// One frame: first_frame once, then the events, the keys and the panels; with `--smoke`, the report.
    ///
    /// `ui` is the window's root area. The `Context` is cloned out of it first, because the panel closures
    /// borrow `ui` while the actions still need the context.
    ///
    /// Steps:
    /// 1. On the first frame, `first_frame`; then take in the job events and check results, then the keys.
    /// 2. While a live site runs or Keep checking is on, ask for a repaint in a second even without input, so
    ///    the uptime counts up and the check timer in `tick` fires.
    /// 3. The left panel: fixed at 260 px (not resizable, so a drag cannot hide the names), scrolling when
    ///    there are many programs.
    /// 4. The "actions" top panel: the tabs, then the Run bar for Run, or a note naming what the other views
    ///    work on (or a warning when there are no programs).
    /// 5. The "jobs" top panel: the job tabs.
    /// 6. The central panel: a warning and nothing else without a root; otherwise the view's body in its own
    ///    scroll area, capped at 60% of the height so the log below always keeps room, then the log. Each
    ///    scroll area has its own `id_salt`, so egui keeps a separate scroll position per view.
    /// 7. With `--smoke`, write the report and close.
    fn ui(&mut self, ui: &mut egui::Ui, _: &mut eframe::Frame) {
        let ctx = &ui.ctx().clone();
        if !self.started {
            self.first_frame(ctx);
        }
        self.drain(ctx);
        self.keys(ctx);
        let site_up = self
            .kind
            .iter()
            .zip(&self.jobs)
            .any(|(k, j)| matches!(k, Kind::Production(_)) && j.status == Status::Running);
        if site_up || self.prod.keep_checking {
            ctx.request_repaint_after(Duration::from_secs(1)); // uptime and the check timer
        }

        egui::Panel::left("projects")
            .resizable(false)
            .min_size(260.0)
            .show(ui, |ui| {
                egui::ScrollArea::vertical().show(ui, |ui| self.sidebar(ui, ctx));
            });

        egui::Panel::top("actions").show(ui, |ui| {
            self.tabs(ui);
            ui.separator();
            if self.programs.is_empty() {
                ui.colored_label(Color32::YELLOW, "No programs: check config/programs.ini.");
            } else if self.view == View::Run {
                self.run_bar(ui, ctx);
            } else if self.view == View::Versions {
                ui.weak(format!(
                    "Editing {}. Pick another program on the left.",
                    self.programs[self.selected].name
                ));
            } else if self.view == View::Seed {
                ui.weak("Seed data for the shared database (CRUD Hub).");
            } else {
                ui.weak("The live site: started from its production command, opened, and checked.");
            }
            ui.add_space(4.0);
        });

        egui::Panel::top("jobs").show(ui, |ui| self.job_tabs(ui));

        egui::CentralPanel::default().show(ui, |ui| {
            if self.root.is_none() {
                ui.colored_label(
                    Color32::YELLOW,
                    "Portfolio root not found: start the console inside the portfolio folder.",
                );
                return;
            }
            match self.view {
                View::Run => {}
                View::Versions if !self.programs.is_empty() => {
                    egui::ScrollArea::vertical()
                        .id_salt("versions")
                        .max_height(ui.available_height() * 0.6)
                        .show(ui, |ui| self.versions_view(ui, ctx));
                    ui.separator();
                }
                View::Seed => {
                    egui::ScrollArea::vertical()
                        .id_salt("seed")
                        .max_height(ui.available_height() * 0.6)
                        .show(ui, |ui| self.seed_view(ui, ctx));
                    ui.separator();
                }
                View::Production => {
                    egui::ScrollArea::vertical()
                        .id_salt("production")
                        .max_height(ui.available_height() * 0.6)
                        .show(ui, |ui| self.production_view(ui, ctx));
                    ui.separator();
                }
                _ => {}
            }
            self.log(ui);
        });

        self.write_self_smoke(ctx);
    }
}

// The pieces of the frame that every view shares.
impl App {
    /// The view tabs, in a row, with each view's help and keys on hover.
    ///
    /// `selectable_value` writes the clicked view straight into `self.view`, so no click handling is needed.
    fn tabs(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            for (v, label, key, help) in View::ALL {
                let tip = self.tip(help, key);
                ui.selectable_value(&mut self.view, v, RichText::new(label).strong())
                    .on_hover_text(tip);
            }
        });
    }

    /// The Run view's bar: the selected program's name and folder, a button per action, and Live tests.
    ///
    /// The program is cloned, because the buttons call `start`, which needs `self` mutably while the loop reads
    /// the program.
    ///
    /// Steps:
    /// 1. The name, and the folder its commands run in.
    /// 2. Per action: ask registry.rs for the command (with a placeholder report path, only to show it), and
    ///    enable the button when there is a command, a root, and no run of it going.
    /// 3. The button's label carries its keys; hovering shows the help and the exact command line, or why
    ///    there is none. `on_disabled_hover_text` gives a greyed-out button the same help, so the user can
    ///    see why it is disabled.
    /// 4. Beside each button, the mark of its last run.
    /// 5. The Live tests box for the selected program.
    ///
    /// `horizontal_wrapped` lets the buttons flow onto a second line when the window is narrow.
    fn run_bar(&mut self, ui: &mut egui::Ui, ctx: &egui::Context) {
        let p = self.selected;
        let prog = self.programs[p].clone();
        ui.horizontal(|ui| {
            ui.strong(&prog.name);
            ui.weak(&prog.dir).on_hover_text("Project folder; commands run here.");
        });
        ui.horizontal_wrapped(|ui| {
            let root = self.root.clone().unwrap_or_else(|| PathBuf::from("."));
            for (a, act) in Action::ALL.iter().enumerate() {
                let cmd = registry::command(&prog, *act, &root, Path::new("REPORT.json"));
                let (mark, col) = badge(&self.last[p][a]);
                let enabled = cmd.is_some() && self.root.is_some() && !self.busy(Kind::Program(p, a));
                let key = act.label().to_lowercase();
                let label = format!("{}{}", act.label(), self.hint(&key));
                let what = match &cmd {
                    Some(c) => format!("{}\n\nRuns: {} {}", act.help(), c.program, c.args.join(" ")),
                    None => format!("{}\n\n{} has no {} command.", act.help(), prog.name, key),
                };
                if ui
                    .add_enabled(enabled, egui::Button::new(label))
                    .on_hover_text(self.tip(&what, &key))
                    .on_disabled_hover_text(what)
                    .clicked()
                {
                    self.start(ctx, p, a);
                }
                ui.colored_label(col, mark).on_hover_text(match &self.last[p][a] {
                    None => "Not run yet".to_string(),
                    Some(s) => format!("Last {}: {}", key, status_text(s)),
                });
            }
            let mut on = self.is_live(p);
            let tip = self.tip(
                "Run this program's tests again whenever a file in its folder is saved.",
                "toggle_live",
            );
            if ui
                .checkbox(&mut on, format!("Live tests{}", self.hint("toggle_live")))
                .on_hover_text(tip)
                .changed()
            {
                self.set_live(p, on);
            }
        });
    }

    /// One tab per job, newest first, each with its status mark; clicking one shows its log.
    ///
    /// The row scrolls sideways, since jobs are never removed and a long session makes many. With no jobs yet,
    /// a hint says what the row is for.
    fn job_tabs(&mut self, ui: &mut egui::Ui) {
        egui::ScrollArea::horizontal().show(ui, |ui| {
            ui.horizontal(|ui| {
                if self.jobs.is_empty() {
                    ui.weak("No jobs yet")
                        .on_hover_text("Each action you start gets a tab here with its output.");
                }
                for id in (0..self.jobs.len()).rev() {
                    let (mark, col) = badge(&Some(self.jobs[id].status.clone()));
                    ui.colored_label(col, mark);
                    let tip = format!(
                        "{}: {}\nClick to show its output.",
                        self.jobs[id].title,
                        status_text(&self.jobs[id].status)
                    );
                    if ui
                        .selectable_label(self.shown == Some(id), &self.jobs[id].title)
                        .on_hover_text(tip)
                        .clicked()
                    {
                        self.shown = Some(id);
                    }
                }
            });
        });
    }

    /// The shown job's log: its title, status and Copy button, then every line in a monospace font.
    ///
    /// `stick_to_bottom` follows new output while the view is at the bottom, but stays put once the user
    /// scrolls up to read. `auto_shrink(false)` makes the area fill the rest of the panel even when the log is
    /// short. Copy puts the whole log on the clipboard, not only the visible part.
    fn log(&self, ui: &mut egui::Ui) {
        let Some(job) = self.shown.and_then(|i| self.jobs.get(i)) else {
            ui.weak("Pick a program and an action. Output appears here.");
            return;
        };
        ui.horizontal(|ui| {
            ui.strong(&job.title);
            match &job.status {
                Status::Running => ui.label("running…"),
                Status::Exited(0) => ui.colored_label(GREEN, "finished"),
                Status::Exited(c) => ui.colored_label(RED, format!("exited with code {c}")),
                Status::Failed(e) => ui.colored_label(RED, e.to_string()),
                Status::Stopped => ui.weak("stopped"),
            };
            if ui
                .small_button("Copy")
                .on_hover_text("Copy this job's whole output to the clipboard.")
                .clicked()
            {
                ui.ctx().copy_text(job.lines.join("\n"));
            }
        });
        ui.separator();
        egui::ScrollArea::vertical()
            .id_salt("log")
            .stick_to_bottom(true)
            .auto_shrink(false)
            .show(ui, |ui| {
                for l in &job.lines {
                    ui.monospace(l);
                }
            });
    }
}

/// A status in words, for hover texts: such as "passed / finished" or "failed (exit code 1)".
///
/// Exit code 0 reads "passed / finished" because it means passed for Test and finished for Build or Run.
fn status_text(s: &Status) -> String {
    match s {
        Status::Running => "running".into(),
        Status::Exited(0) => "passed / finished".into(),
        Status::Exited(c) => format!("failed (exit code {c})"),
        Status::Failed(e) => format!("could not start: {e}"),
        Status::Stopped => "stopped from the console".into(),
    }
}

/// The mark and its colour for a last-run status: a grey dot for never run, blue dots while running, a green
/// tick, a grey square for stopped, a red cross for anything else.
///
/// A mark plus a colour, rather than colour alone, keeps the states apart for colour-blind users.
fn badge(s: &Option<Status>) -> (&'static str, Color32) {
    match s {
        None => ("·", Color32::GRAY),
        Some(Status::Running) => ("…", Color32::LIGHT_BLUE),
        Some(Status::Exited(0)) => ("✔", GREEN),
        Some(Status::Stopped) => ("■", Color32::GRAY),
        Some(_) => ("✖", RED),
    }
}

// ==== stamp v1 | author=kjFriday | hmac-sha256=ff17435009cec7e992f5703e3dd437cf3293512c4e9f190e54cb5fd8185ba58d ====
