// ==== Generic Company Inc. portfolio ====================================
// Project: dev_console | File: src/app/views/production.rs
// About: The live-production view: a program's live site, started and stopped from its production...
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
// ========================================================================

//! The live-production view: start, stop, open and check a program's live site.
//!
//! A program has a live site when programs.ini gives it a `production` command, a `production_url`, or both.
//! The frame loop in app/views.rs draws this view in the central panel when its tab is picked. The buttons
//! call the actions in app.rs (`start_production`, `stop_job`, `check_production`); the checks themselves
//! are in production.rs.
//!
//! What the view shows, top to bottom:
//! 1. A row of program names to pick from, when more than one has a site.
//! 2. A grid: program, command, address, and the server's state (starting, running with uptime and PID, or
//!    how its last run ended).
//! 3. Start, Stop, Open in browser, Check now and the Keep checking box.
//! 4. A note, such as a port already in use.
//! 5. The checks: how many passed, how long ago and at which URL, then one row per check.

use std::time::Duration;

use eframe::egui::{self, Color32};

use super::{GREEN, RED, status_text};
use crate::app::App;
use crate::production;

// The view's body, drawn as part of App.
impl App {
    /// Draw the live-production view; `ctx` is passed on to the actions the buttons start.
    ///
    /// Steps:
    /// 1. List the programs with a site; with none, say how to add one and stop.
    /// 2. Keep the picked program if it still has a site, else take the first, and store the choice so the
    ///    timer in `tick` checks the same one.
    /// 3. The grid's labels and values sit in two columns (`egui::Grid`), so the values line up whatever the
    ///    label widths. The Server row reads `waiting` and the job's process to say whether it is starting,
    ///    running (uptime and PID) or not running.
    /// 4. Start is enabled with a command, a root, and no site running; Stop only once the job has a process
    ///    id to kill. Open in browser and Check now need a URL; Check now also waits for a running check.
    /// 5. The note, in green or red.
    /// 6. The Checks heading with a spinner while a check runs, then the summary and a striped four-column
    ///    grid (mark, check, detail, time); striping helps the eye follow a row across.
    pub(super) fn production_view(&mut self, ui: &mut egui::Ui, ctx: &egui::Context) {
        let sites: Vec<usize> = (0..self.programs.len())
            .filter(|&i| self.programs[i].has_production())
            .collect();
        ui.heading("live-production")
            .on_hover_text("Programs with a production command or URL in programs.ini: their live site, started from here, and what it answers.");
        let Some(&first) = sites.first() else {
            ui.weak("No program has a live site yet: give one production, production_url and production_checks (Versions & commands).");
            return;
        };
        let p = self.prod.pick.filter(|p| sites.contains(p)).unwrap_or(first);
        self.prod.pick = Some(p);
        if sites.len() > 1 {
            ui.horizontal(|ui| {
                for &i in &sites {
                    if ui.selectable_label(i == p, &self.programs[i].name).clicked() {
                        self.prod.pick = Some(i);
                    }
                }
            });
        }
        let prog = self.programs[p].clone();
        let running = self.production_job(p);
        egui::Grid::new("site").num_columns(2).show(ui, |ui| {
            ui.label("Program");
            ui.strong(&prog.name);
            ui.end_row();
            ui.label("Command")
                .on_hover_text("production in programs.ini; it runs in the program's folder.");
            ui.monospace(if prog.production.is_empty() {
                "(none: checks only)"
            } else {
                prog.production.as_str()
            });
            ui.end_row();
            ui.label("Address")
                .on_hover_text("production_url in programs.ini: where the checks go.");
            ui.monospace(if prog.production_url.is_empty() {
                "(no production_url)"
            } else {
                prog.production_url.as_str()
            });
            ui.end_row();
            ui.label("Server");
            match (running, &self.prod.waiting) {
                (Some(_), Some(addr)) => {
                    ui.colored_label(Color32::LIGHT_BLUE, format!("starting: waiting for {addr} to answer"));
                }
                (Some(id), None) => {
                    let up = self.procs[id].started.map(|t| ago(t.elapsed())).unwrap_or_default();
                    let pid = self.procs[id].pid.map(|n| format!(" (PID {n})")).unwrap_or_default();
                    ui.colored_label(GREEN, format!("running for {up}{pid}"));
                }
                (None, _) => match self.last_production_job(p) {
                    Some(id) => {
                        ui.weak(status_text(&self.jobs[id].status));
                    }
                    None => {
                        ui.weak("not started from the console");
                    }
                },
            }
            ui.end_row();
        });
        ui.horizontal_wrapped(|ui| {
            let can_start = running.is_none() && !prog.production.trim().is_empty() && self.root.is_some();
            if ui
                .add_enabled(can_start, egui::Button::new("Start"))
                .on_hover_text(format!(
                    "Run {} in {}, then check the site once it answers.",
                    prog.production, prog.dir
                ))
                .on_disabled_hover_text(if running.is_some() {
                    "It is running already."
                } else {
                    "This program has no production command."
                })
                .clicked()
            {
                self.start_production(ctx, p);
            }
            let can_stop = running.is_some_and(|id| self.procs[id].pid.is_some());
            if ui
                .add_enabled(can_stop, egui::Button::new("Stop"))
                .on_hover_text("End the live site and every process it started.")
                .clicked()
            {
                if let Some(id) = running {
                    self.stop_job(id);
                }
            }
            let has_url = !prog.production_url.trim().is_empty();
            if ui
                .add_enabled(has_url, egui::Button::new("Open in browser"))
                .on_hover_text(format!("Open {} in your browser.", prog.production_url))
                .clicked()
            {
                ctx.open_url(egui::OpenUrl::new_tab(prog.production_url.trim()));
            }
            if ui
                .add_enabled(has_url && !self.prod.checking, egui::Button::new("Check now"))
                .on_hover_text(
                    "Send production_checks to the address now, whether or not the console started the server.",
                )
                .clicked()
            {
                self.check_production(ctx, p, None);
            }
            let every = self.cfg.number("production", "interval_s", 30.0).max(5.0);
            ui.checkbox(
                &mut self.prod.keep_checking,
                format!("Keep checking every {every:.0} s"),
            )
            .on_hover_text("Run the checks again on a timer while this is ticked (interval_s in settings.ini).");
        });
        if let Some((ok, text)) = &self.prod.note {
            ui.colored_label(if *ok { GREEN } else { RED }, text);
        }
        ui.add_space(6.0);
        ui.horizontal(|ui| {
            ui.strong("Checks").on_hover_text(format!(
                "Each production_checks entry, then the {} security headers on every 200 answer, and that no answer shows your user folder or the portfolio folder.",
                production::HEADERS.len()
            ));
            if self.prod.checking {
                ui.spinner();
            }
        });
        match &self.prod.checked {
            None => {
                ui.weak(if self.prod.checking {
                    "Checking…"
                } else {
                    "Not checked yet: Start the site, or Check now."
                });
            }
            Some((when, url)) => {
                let passed = self.prod.outcomes.iter().filter(|o| o.ok).count();
                let n = self.prod.outcomes.len();
                ui.colored_label(
                    if passed == n { GREEN } else { RED },
                    format!("{passed} of {n} passed, {} ago, at {url}", ago(when.elapsed())),
                );
                egui::Grid::new("checks").num_columns(4).striped(true).show(ui, |ui| {
                    for o in &self.prod.outcomes {
                        ui.colored_label(if o.ok { GREEN } else { RED }, if o.ok { "✔" } else { "✖" });
                        ui.monospace(&o.label);
                        ui.label(&o.detail);
                        ui.weak(o.ms.map(|m| format!("{m} ms")).unwrap_or_default());
                        ui.end_row();
                    }
                });
            }
        }
    }
}

/// 75 s -> "1 m 15 s".
///
/// A duration in its two largest units: seconds under a minute, minutes and seconds under an hour, then hours
/// and minutes. Used for the uptime and for how long ago the checks ran.
fn ago(d: Duration) -> String {
    let s = d.as_secs();
    match s {
        0..=59 => format!("{s} s"),
        60..=3599 => format!("{} m {} s", s / 60, s % 60),
        _ => format!("{} h {} m", s / 3600, s % 3600 / 60),
    }
}

/// Tests for the view's table entry, its default key and the time text.
#[cfg(test)]
mod tests {
    use super::*;
    use crate::app::View;
    use crate::app::keys::sc_text;
    use crate::config;

    /// The view is in View::ALL as live-production with the view_production key, which defaults to Ctrl+4,
    /// and `ago` writes seconds, minutes and hours as expected.
    #[test]
    fn live_production_is_a_view_with_keys() {
        let (_, label, key, _) = View::ALL.iter().find(|(v, ..)| *v == View::Production).unwrap();
        assert_eq!((*label, *key), ("live-production", "view_production"));
        let cfg = config::load(&[], None);
        assert_eq!(
            cfg.controls.get("view_production").map(sc_text).as_deref(),
            Some("Ctrl+4")
        );
        assert_eq!(
            (
                ago(Duration::from_secs(9)),
                ago(Duration::from_secs(75)),
                ago(Duration::from_secs(3720))
            ),
            ("9 s".into(), "1 m 15 s".into(), "1 h 2 m".into())
        );
    }
}

// ==== stamp v1 | author=kjFriday | hmac-sha256=684b938499219a1177d9f81650c1f15132c8d63dd03ad3b5f48f5c2e3feccf27 ====
