// ==== Generic Company Inc. portfolio ====================================
// Project: portfolio | File: dev_console/src/main.rs
// About: Generic Company Dev Console: one window that builds, tests, runs and smoke-checks every...
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
// ========================================================================

//! Generic Company Dev Console: one window that builds, tests, runs and smoke-checks every portfolio program.

#![cfg_attr(not(test), windows_subsystem = "windows")]

mod config;
mod desktop;
mod install;
mod jobs;
mod live;
mod registry;
mod seed;
mod versions;

use std::path::{Path, PathBuf};
use std::sync::mpsc::{channel, Receiver, Sender};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use eframe::egui::{self, Color32, Key, KeyboardShortcut, RichText};
use jobs::{Event, Job, Status};
use registry::{Action, Program};

const VERSION: &str = env!("CARGO_PKG_VERSION");
const TITLE: &str = concat!("Generic Company Inc. — Dev Console ", env!("CARGO_PKG_VERSION"));
const TEST: usize = 1; // index of Action::Test in Action::ALL
const GREEN: Color32 = Color32::from_rgb(90, 190, 110);
const RED: Color32 = Color32::from_rgb(220, 90, 80);
const CONFIRM_FOR: Duration = Duration::from_secs(5);

#[derive(Clone, Copy, PartialEq, Eq)]
enum View {
    Run,
    Versions,
    Seed,
}

impl View {
    const ALL: [(View, &'static str, &'static str, &'static str); 3] = [
        (View::Run, "Run", "view_run", "Build, test, run and smoke-check the selected program, and read its output."),
        (View::Versions, "Versions & commands", "view_versions", "Change the selected program's version (in every file that holds it) and the commands the console runs for it."),
        (View::Seed, "Seed data", "view_seed", "The CRUD Hub's shared database: row counts, backups, reseeding and mock snapshots."),
    ];
}

/// What a job belongs to.
#[derive(Clone, Copy, PartialEq, Eq)]
enum Kind {
    Program(usize, usize),
    Desktop,
    Seed(seed::Op),
    Stamp,
}

struct App {
    root: Option<PathBuf>,
    cfg: config::Config,
    programs: Vec<Program>,
    zoom: f32,
    view: View,
    selected: usize,
    jobs: Vec<Job>,
    /// Smoke report file per job, read when the job ends.
    smoke: Vec<Option<PathBuf>>,
    kind: Vec<Kind>,
    shown: Option<usize>,
    /// Last finished status per (program, action).
    last: Vec<[Option<Status>; Action::ALL.len()]>,
    tx: Sender<Event>,
    rx: Receiver<Event>,
    live: Arc<Mutex<Vec<bool>>>,
    live_rx: Option<Receiver<usize>>,
    /// `--smoke FILE`: write a report after the first frame, then close.
    self_smoke: Option<PathBuf>,
    started: bool,
    /// Messages from the last save or version change, shown in the Versions view.
    notes: Vec<(bool, String)>,
    ver: Versions,
    seed: SeedView,
}

/// Versions & commands editor state.
struct Versions {
    /// Program the spots were read for.
    for_program: Option<usize>,
    spots: Vec<Result<versions::Spot, String>>,
    new_version: String,
    /// Commands being edited; saved to programs.ini on Save.
    edit: Vec<Program>,
}

/// Seed data view state.
struct SeedView {
    db: String,
    counts: Option<Vec<(String, u64)>>,
    counts_error: Option<String>,
    backups: Vec<seed::Backup>,
    pick: Option<usize>,
    armed: Option<(seed::Op, Instant)>,
    loaded: bool,
}

impl App {
    fn new(cfg: config::Config, root: Option<PathBuf>, self_smoke: Option<PathBuf>) -> Self {
        let (tx, rx) = channel();
        let zoom = cfg.number("view", "zoom", 1.0);
        let (programs, problems) = registry::load(&cfg.programs);
        let mut cfg = cfg;
        cfg.warnings.extend(problems);
        let n = programs.len();
        let env = |k: &str| std::env::var(k).ok();
        let db = seed::default_db(&env).map(|p| p.display().to_string()).unwrap_or_default();
        App {
            root,
            cfg,
            zoom,
            view: View::Run,
            selected: 0,
            jobs: vec![],
            smoke: vec![],
            kind: vec![],
            shown: None,
            last: vec![Default::default(); n],
            tx,
            rx,
            live: Arc::new(Mutex::new(vec![false; n])),
            live_rx: None,
            self_smoke,
            started: false,
            notes: vec![],
            ver: Versions { for_program: None, spots: vec![], new_version: String::new(), edit: programs.clone() },
            seed: SeedView { db, counts: None, counts_error: None, backups: vec![], pick: None, armed: None, loaded: false },
            programs,
        }
    }

    fn first_frame(&mut self, ctx: &egui::Context) {
        self.started = true;
        ctx.options_mut(|o| o.zoom_with_keyboard = false); // zoom keys come from controls.ini instead
        ctx.set_zoom_factor(self.zoom);
        if let Some(root) = self.root.clone() {
            let (tx, rx) = channel();
            self.live_rx = Some(rx);
            let flags = self.live.clone();
            let dirs: Vec<PathBuf> = self.programs.iter().map(|p| root.join(&p.dir)).collect();
            let skip = self.cfg.list("live", "skip");
            let every = Duration::from_millis(self.cfg.number("live", "interval_ms", 1000.0).max(200.0) as u64);
            let ctx = ctx.clone();
            std::thread::spawn(move || {
                let mut watches: Vec<live::Watch> = dirs.iter().map(|_| live::Watch::default()).collect();
                loop {
                    let on = flags.lock().unwrap().clone();
                    for (i, dir) in dirs.iter().enumerate() {
                        if !on[i] {
                            watches[i] = live::Watch::default();
                            continue;
                        }
                        if watches[i].changed(live::newest(dir, &skip)) {
                            if tx.send(i).is_err() {
                                return;
                            }
                            ctx.request_repaint();
                        }
                    }
                    std::thread::sleep(every);
                }
            });
        }
    }

    /// Add a job and return its id; `header` is the first log line.
    fn add_job(&mut self, title: String, header: String, kind: Kind, smoke: Option<PathBuf>) -> usize {
        let id = self.jobs.len();
        let mut job = Job { title, lines: vec![], status: Status::Running };
        job.push(header);
        self.jobs.push(job);
        self.smoke.push(smoke);
        self.kind.push(kind);
        self.shown = Some(id);
        id
    }

    fn wake(ctx: &egui::Context) -> impl Fn() + Send + Clone + 'static {
        let ctx = ctx.clone();
        move || ctx.request_repaint()
    }

    fn start(&mut self, ctx: &egui::Context, p: usize, a: usize) {
        let Some(root) = self.root.clone() else { return };
        if p >= self.programs.len() || self.busy(Kind::Program(p, a)) {
            return;
        }
        let report = std::env::temp_dir().join(format!("gc-console-smoke-{}-{}.json", std::process::id(), self.jobs.len()));
        let Some(cmd) = registry::command(&self.programs[p], Action::ALL[a], &root, &report) else { return };
        let title = format!("{} · {}", self.programs[p].name, Action::ALL[a].label());
        let header = format!("> {} {}", cmd.program, cmd.args.join(" "));
        let id = self.add_job(title, header, Kind::Program(p, a), (Action::ALL[a] == Action::Smoke).then_some(report));
        self.last[p][a] = Some(Status::Running);
        jobs::spawn(id, cmd, self.tx.clone(), Self::wake(ctx));
    }

    fn drain(&mut self, ctx: &egui::Context) {
        while let Ok(ev) = self.rx.try_recv() {
            match ev {
                Event::Line(id, l) => self.jobs[id].push(l),
                Event::Done(id, s) => {
                    if let Some(path) = self.smoke[id].take() {
                        match std::fs::read_to_string(&path) {
                            Ok(t) => t.lines().for_each(|l| self.jobs[id].push(format!("report: {l}"))),
                            Err(_) => self.jobs[id].push("report: none written".into()),
                        }
                        let _ = std::fs::remove_file(path);
                    }
                    self.jobs[id].status = s.clone();
                    match self.kind[id] {
                        Kind::Program(p, a) => self.last[p][a] = Some(s),
                        Kind::Seed(seed::Op::Counts) => {
                            if s == Status::Exited(0) {
                                self.seed.counts = Some(seed::parse_counts(&self.jobs[id].lines));
                                self.seed.counts_error = None;
                            } else {
                                self.seed.counts = None;
                                let why = self.jobs[id].lines.iter().rev().find(|l| !l.trim().is_empty()).cloned();
                                self.seed.counts_error = Some(why.unwrap_or_else(|| format!("{s:?}")));
                            }
                        }
                        Kind::Seed(_) => {
                            self.refresh_seed(ctx);
                        }
                        Kind::Stamp => {
                            let ok = s == Status::Exited(0);
                            self.notes.push((ok, if ok { "Stamps renewed.".into() } else { "stamp.py --restamp failed; see its log.".into() }));
                        }
                        Kind::Desktop => {}
                    }
                }
            }
        }
        let changed: Vec<usize> = self.live_rx.as_ref().map(|r| r.try_iter().collect()).unwrap_or_default();
        for p in changed {
            self.start(ctx, p, TEST);
        }
        if self.seed.armed.is_some_and(|(_, t)| t.elapsed() > CONFIRM_FOR) {
            self.seed.armed = None;
        }
    }

    fn busy(&self, kind: Kind) -> bool {
        self.kind.iter().zip(&self.jobs).any(|(&k, j)| k == kind && j.status == Status::Running)
    }

    fn seed_busy(&self) -> bool {
        self.kind.iter().zip(&self.jobs).any(|(k, j)| matches!(k, Kind::Seed(_)) && j.status == Status::Running)
    }

    /// Start a desktop-shortcut job: build and place the set (`make`), or take it away.
    fn desktop_job(&mut self, ctx: &egui::Context, make: bool) {
        let (Some(root), Some(user)) = (self.root.clone(), self.cfg.user_dir.clone()) else { return };
        if self.busy(Kind::Desktop) {
            return;
        }
        let title = if make { "Desktop shortcuts" } else { "Remove desktop shortcuts" };
        let id = self.add_job(title.into(), format!("> {title}"), Kind::Desktop, None);
        if make {
            desktop::make(id, self.programs.clone(), root, user, None, self.tx.clone(), Self::wake(ctx));
        } else {
            desktop::remove(id, user, self.tx.clone(), Self::wake(ctx));
        }
    }

    // ---- seed data ---------------------------------------------------------------------------

    fn db_path(&self) -> PathBuf {
        PathBuf::from(self.seed.db.trim())
    }

    fn seed_job(&mut self, ctx: &egui::Context, op: seed::Op) {
        let Some(root) = self.root.clone() else { return };
        if self.seed_busy() || self.seed.db.trim().is_empty() {
            return;
        }
        let db = self.db_path();
        let backup = self.seed.pick.and_then(|i| self.seed.backups.get(i)).map(|b| b.path.clone());
        let Some(cmd) = seed::command(op, &root, &db, backup.as_deref()) else { return };
        let header = match op {
            seed::Op::Restore => format!("> restore {} from {}", db.display(), backup.unwrap_or_default().display()),
            seed::Op::Counts | seed::Op::Backup => format!("> {} {}", op.label().to_lowercase(), db.display()),
            _ => format!("> {} {}", cmd.program, cmd.args.join(" ")),
        };
        let id = self.add_job(format!("Seed · {}", op.label()), header, Kind::Seed(op), None);
        jobs::spawn(id, cmd, self.tx.clone(), Self::wake(ctx));
    }

    /// Rescan backups and re-read the counts.
    fn refresh_seed(&mut self, ctx: &egui::Context) {
        self.seed.loaded = true;
        let picked = self.seed.pick.and_then(|i| self.seed.backups.get(i)).map(|b| b.path.clone());
        self.seed.backups = seed::backups(&self.db_path());
        self.seed.pick = picked.and_then(|p| self.seed.backups.iter().position(|b| b.path == p));
        if self.db_path().is_file() {
            self.seed_job(ctx, seed::Op::Counts);
        } else {
            self.seed.counts = None;
            self.seed.counts_error = None;
        }
    }

    /// A destructive op runs on the second click within a few seconds.
    fn seed_click(&mut self, ctx: &egui::Context, op: seed::Op) {
        if op.needs_confirm() && self.seed.armed.map(|(o, _)| o) != Some(op) {
            self.seed.armed = Some((op, Instant::now()));
            return;
        }
        self.seed.armed = None;
        self.seed_job(ctx, op);
    }

    // ---- versions & commands -----------------------------------------------------------------

    fn load_versions(&mut self) {
        let Some(root) = &self.root else { return };
        let p = &self.programs[self.selected];
        self.ver.spots = p.version_files.iter().map(|f| versions::find_in(&root.join(&p.dir).join(f))).collect();
        self.ver.for_program = Some(self.selected);
        self.ver.new_version = self.ver.spots.iter().flatten().next().map(|s| s.value.clone()).unwrap_or_default();
    }

    fn apply_version(&mut self, ctx: &egui::Context) {
        let Some(root) = self.root.clone() else { return };
        let spots: Vec<versions::Spot> = self.ver.spots.iter().flatten().cloned().collect();
        let new = self.ver.new_version.trim().to_string();
        let name = self.programs[self.selected].name.clone();
        match versions::set(&spots, &new) {
            Err(e) => self.notes.push((false, e)),
            Ok(changed) if changed.is_empty() => self.notes.push((true, format!("{name} is already {new} everywhere."))),
            Ok(changed) => {
                let rel: Vec<String> = changed
                    .iter()
                    .map(|f| f.strip_prefix(&root).unwrap_or(f).to_string_lossy().replace('\\', "/"))
                    .collect();
                self.notes.push((true, format!("{name} is now {new} in {}.", rel.join(", "))));
                // Stamped sources need a new stamp after an edit; JSON files carry none.
                let stamped: Vec<String> = rel.into_iter().filter(|f| !f.ends_with(".json")).collect();
                if !stamped.is_empty() && root.join("stamp.py").is_file() {
                    let mut words = vec!["python".to_string(), "stamp.py".into(), "--restamp".into()];
                    words.extend(stamped);
                    if let Some(cmd) = registry::Cmd::new(words, root.clone()) {
                        let header = format!("> {} {}", cmd.program, cmd.args.join(" "));
                        let id = self.add_job(format!("{name} · Restamp"), header, Kind::Stamp, None);
                        jobs::spawn(id, cmd, self.tx.clone(), Self::wake(ctx));
                    }
                }
            }
        }
        self.load_versions();
    }

    fn commands_dirty(&self) -> bool {
        self.ver.edit != self.programs
    }

    fn save_commands(&mut self) {
        let Some(path) = self.cfg.programs_file.clone() else {
            self.notes.push((false, "No config folder to save programs.ini in.".into()));
            return;
        };
        let text = registry::render(&self.ver.edit);
        let (check, problems) = registry::load(&config::parse(&text));
        if !problems.is_empty() || check.len() != self.ver.edit.len() {
            self.notes.push((false, format!("Not saved: {}", problems.join("; "))));
            return;
        }
        let result = path.parent().map_or(Ok(()), std::fs::create_dir_all).and_then(|_| std::fs::write(&path, text));
        match result {
            Ok(()) => {
                self.programs = self.ver.edit.clone();
                self.notes.push((true, format!("Saved to {}.", path.display())));
            }
            Err(e) => self.notes.push((false, format!("Could not save {}: {e}", path.display()))),
        }
    }

    // ---- live, zoom, keys --------------------------------------------------------------------

    fn is_live(&self, p: usize) -> bool {
        self.live.lock().unwrap()[p]
    }

    fn set_live(&mut self, p: usize, on: bool) {
        self.live.lock().unwrap()[p] = on;
    }

    fn set_zoom(&mut self, ctx: &egui::Context, z: f32) {
        let (lo, hi) = (self.cfg.number("view", "zoom_min", 0.5), self.cfg.number("view", "zoom_max", 3.0));
        let z = (z.clamp(lo, hi) * 100.0).round() / 100.0;
        if z == self.zoom {
            return;
        }
        self.zoom = z;
        ctx.set_zoom_factor(z);
        if let Err(e) = self.cfg.save("view", "zoom", format!("{z}")) {
            self.cfg.warnings.push(format!("could not save text size: {e}"));
        }
    }

    /// True once per press of the control named `action` in controls.ini.
    fn pressed(&self, ctx: &egui::Context, action: &str) -> bool {
        let Some(sc) = self.cfg.controls.get(action) else { return false };
        // Ctrl+Plus arrives as Ctrl+= on most keyboards; accept both.
        let alt = (sc.logical_key == Key::Plus).then(|| KeyboardShortcut::new(sc.modifiers, Key::Equals));
        ctx.input_mut(|i| i.consume_shortcut(sc) || alt.is_some_and(|a| i.consume_shortcut(&a)))
    }

    fn keys(&mut self, ctx: &egui::Context) {
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
    fn hint(&self, action: &str) -> String {
        self.cfg.controls.get(action).map(|sc| format!(" ({})", sc_text(sc))).unwrap_or_default()
    }

    /// Hover text with the control's keys on a line of its own.
    fn tip(&self, text: &str, action: &str) -> String {
        match self.cfg.controls.get(action) {
            Some(sc) => format!("{text}\nKeys: {} (change them in controls.ini)", sc_text(sc)),
            None => text.to_string(),
        }
    }

    fn write_self_smoke(&mut self, ctx: &egui::Context) {
        let Some(path) = self.self_smoke.take() else { return };
        let report = format!(
            "{{\"title\": \"{}\", \"version\": \"{VERSION}\", \"programs\": {}, \"root_found\": {}, \"controls\": {}, \"warnings\": {}}}\n",
            TITLE,
            self.programs.len(),
            self.root.is_some(),
            self.cfg.controls.len(),
            self.cfg.warnings.len()
        );
        let _ = std::fs::write(path, report);
        ctx.send_viewport_cmd(egui::ViewportCommand::Close);
    }

    // ---- drawing -----------------------------------------------------------------------------

    fn sidebar(&mut self, ui: &mut egui::Ui, ctx: &egui::Context) {
        ui.heading("Programs").on_hover_text("Every program in config/programs.ini. Pick one to work on it.");
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
                    ui.colored_label(GREEN, "live").on_hover_text("Live tests are on: saving a file in this program's folder runs its tests.");
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
            ui.weak(format!("Text {:.0}%", self.zoom * 100.0)).on_hover_text("Text and UI size. It is saved between runs.");
            let step = self.cfg.number("view", "zoom_step", 0.1);
            if ui.small_button("−").on_hover_text(self.tip("Smaller text", "zoom_out")).clicked() {
                self.set_zoom(ctx, self.zoom - step);
            }
            if ui.small_button("+").on_hover_text(self.tip("Larger text", "zoom_in")).clicked() {
                self.set_zoom(ctx, self.zoom + step);
            }
            if ui.small_button("100%").on_hover_text(self.tip("Normal text size", "zoom_reset")).clicked() {
                self.set_zoom(ctx, 1.0);
            }
        });
        for w in &self.cfg.warnings {
            ui.colored_label(Color32::YELLOW, w).on_hover_text("A problem in the config files; the rest still works.");
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
            ui.weak(format!("Root: {}", root.display())).on_hover_text("The portfolio folder (found by looking upward for RULES.md).");
        }
    }

    fn tabs(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            for (v, label, key, help) in View::ALL {
                let tip = self.tip(help, key);
                ui.selectable_value(&mut self.view, v, RichText::new(label).strong()).on_hover_text(tip);
            }
        });
    }

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
                if ui.add_enabled(enabled, egui::Button::new(label)).on_hover_text(self.tip(&what, &key)).on_disabled_hover_text(what).clicked() {
                    self.start(ctx, p, a);
                }
                ui.colored_label(col, mark).on_hover_text(match &self.last[p][a] {
                    None => "Not run yet".to_string(),
                    Some(s) => format!("Last {}: {}", key, status_text(s)),
                });
            }
            let mut on = self.is_live(p);
            let tip = self.tip("Run this program's tests again whenever a file in its folder is saved.", "toggle_live");
            if ui.checkbox(&mut on, format!("Live tests{}", self.hint("toggle_live"))).on_hover_text(tip).changed() {
                self.set_live(p, on);
            }
        });
    }

    fn job_tabs(&mut self, ui: &mut egui::Ui) {
        egui::ScrollArea::horizontal().show(ui, |ui| {
            ui.horizontal(|ui| {
                if self.jobs.is_empty() {
                    ui.weak("No jobs yet").on_hover_text("Each action you start gets a tab here with its output.");
                }
                for id in (0..self.jobs.len()).rev() {
                    let (mark, col) = badge(&Some(self.jobs[id].status.clone()));
                    ui.colored_label(col, mark);
                    let tip = format!("{}: {}\nClick to show its output.", self.jobs[id].title, status_text(&self.jobs[id].status));
                    if ui.selectable_label(self.shown == Some(id), &self.jobs[id].title).on_hover_text(tip).clicked() {
                        self.shown = Some(id);
                    }
                }
            });
        });
    }

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
            };
            if ui.small_button("Copy").on_hover_text("Copy this job's whole output to the clipboard.").clicked() {
                ui.ctx().copy_text(job.lines.join("\n"));
            }
        });
        ui.separator();
        egui::ScrollArea::vertical().id_salt("log").stick_to_bottom(true).auto_shrink(false).show(ui, |ui| {
            for l in &job.lines {
                ui.monospace(l);
            }
        });
    }

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

    fn versions_view(&mut self, ui: &mut egui::Ui, ctx: &egui::Context) {
        if self.ver.for_program != Some(self.selected) {
            self.load_versions();
        }
        let p = self.selected;
        let name = self.programs[p].name.clone();
        ui.heading(format!("{name} — version")).on_hover_text("Where this program's version is written, from version_files in programs.ini.");
        let values: Vec<String> = self.ver.spots.iter().flatten().map(|s| s.value.clone()).collect();
        let agree = values.windows(2).all(|w| w[0] == w[1]);
        egui::Grid::new("spots").num_columns(2).striped(true).show(ui, |ui| {
            for s in &self.ver.spots {
                match s {
                    Ok(s) => {
                        let rel = self.root.as_ref().and_then(|r| s.file.strip_prefix(r).ok()).unwrap_or(&s.file);
                        ui.monospace(rel.display().to_string()).on_hover_text(format!("Line {} of this file", s.line + 1));
                        let text = RichText::new(&s.value).monospace();
                        ui.label(if agree { text } else { text.color(Color32::YELLOW) })
                            .on_hover_text(if agree { "Matches the other files." } else { "Differs from another file: Apply sets them all to the same version." });
                    }
                    Err(e) => {
                        ui.colored_label(RED, e).on_hover_text("Fix version_files in programs.ini, or add a version line to the file.");
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
                .on_hover_text("Write this version into every file above, then renew the stamps of the source files you changed (stamp.py --restamp). Nothing is committed.")
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
        ui.heading(format!("{name} — commands")).on_hover_text("What the console runs for this program. Saved to config/programs.ini.");
        egui::Grid::new("commands").num_columns(2).striped(true).show(ui, |ui| {
            for (key, label, help) in registry::FIELDS {
                let changed = self.ver.edit[p].field(key) != self.programs[p].field(key);
                let text = if changed { RichText::new(format!("{label} *")).color(Color32::YELLOW) } else { RichText::new(label) };
                ui.label(text).on_hover_text(help);
                let words = if key == "desktop_build" {
                    registry::steps(self.ver.edit[p].field(key)).iter().map(|s| format!("[{}]", s.join("] ["))).collect::<Vec<_>>().join("\nthen ")
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
            let file = self.cfg.programs_file.as_ref().map(|f| f.display().to_string()).unwrap_or_default();
            if ui.add_enabled(dirty, egui::Button::new("Save commands")).on_hover_text(format!("Write every program's commands to {file}.")).clicked() {
                self.save_commands();
            }
            if ui.add_enabled(dirty, egui::Button::new("Revert")).on_hover_text("Throw away unsaved command changes.").clicked() {
                self.ver.edit = self.programs.clone();
            }
            if dirty {
                ui.colored_label(Color32::YELLOW, "unsaved changes").on_hover_text("Fields marked * differ from the saved programs.ini.");
            }
        });
        self.notes_ui(ui);
    }

    fn seed_view(&mut self, ui: &mut egui::Ui, ctx: &egui::Context) {
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
        ui.weak(seed::describe(&self.db_path())).on_hover_text("Size of the file and when it last changed.");
        ui.add_space(6.0);

        ui.horizontal_wrapped(|ui| {
            let busy = self.seed_busy();
            for op in [seed::Op::Counts, seed::Op::Backup, seed::Op::Reseed, seed::Op::Fresh, seed::Op::Export] {
                let armed = self.seed.armed.map(|(o, _)| o) == Some(op);
                let label = if armed { RichText::new(format!("Click again: {}", op.label())).color(RED) } else { RichText::new(op.label()) };
                let tip = if op.needs_confirm() { format!("{}\n\nAsks for a second click.", op.help()) } else { op.help().to_string() };
                if ui.add_enabled(!busy, egui::Button::new(label)).on_hover_text(tip).on_disabled_hover_text("Waiting for the running seed job.").clicked() {
                    self.seed_click(ctx, op);
                }
            }
        });
        ui.add_space(6.0);

        ui.columns(2, |cols| {
            cols[0].strong("Rows per table").on_hover_text("Read from the database; refreshed after every seed job.");
            match (&self.seed.counts, &self.seed.counts_error) {
                (Some(c), _) if !c.is_empty() => {
                    egui::Grid::new("counts").num_columns(2).striped(true).show(&mut cols[0], |ui| {
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
                    cols[0].colored_label(RED, e).on_hover_text("Could not read the file. Is it a database?");
                }
                (None, None) => {
                    cols[0].weak(if self.db_path().is_file() { "Reading…" } else { "No database file yet." });
                }
            }

            cols[1].strong("Backups").on_hover_text("Dated copies beside the database (made by Reseed, Back up now and Restore). Pick one to restore it.");
            if self.seed.backups.is_empty() {
                cols[1].weak("None yet.");
            }
            egui::ScrollArea::vertical().id_salt("backups").max_height(180.0).show(&mut cols[1], |ui| {
                for (i, b) in self.seed.backups.iter().enumerate() {
                    let text = format!("{}   {}", b.when, seed::size(b.size));
                    if ui.selectable_label(self.seed.pick == Some(i), text).on_hover_text(b.path.display().to_string()).clicked() {
                        self.seed.pick = Some(i);
                    }
                }
            });
            let op = seed::Op::Restore;
            let armed = self.seed.armed.map(|(o, _)| o) == Some(op);
            let label = if armed { RichText::new("Click again: Restore").color(RED) } else { RichText::new("Restore selected") };
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

fn status_text(s: &Status) -> String {
    match s {
        Status::Running => "running".into(),
        Status::Exited(0) => "passed / finished".into(),
        Status::Exited(c) => format!("failed (exit code {c})"),
        Status::Failed(e) => format!("could not start: {e}"),
    }
}

/// The 32 px Silk icon from icon/app-32.rgba (8-byte little-endian width/height header, then RGBA).
fn window_icon() -> egui::IconData {
    const RAW: &[u8] = include_bytes!("../icon/app-32.rgba");
    let dim = |i: usize| u32::from_le_bytes(RAW[i..i + 4].try_into().unwrap());
    egui::IconData { rgba: RAW[8..].to_vec(), width: dim(0), height: dim(4) }
}

fn sc_text(sc: &KeyboardShortcut) -> String {
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

fn badge(s: &Option<Status>) -> (&'static str, Color32) {
    match s {
        None => ("·", Color32::GRAY),
        Some(Status::Running) => ("…", Color32::LIGHT_BLUE),
        Some(Status::Exited(0)) => ("✔", GREEN),
        Some(_) => ("✖", RED),
    }
}

impl eframe::App for App {
    fn ui(&mut self, ui: &mut egui::Ui, _: &mut eframe::Frame) {
        let ctx = &ui.ctx().clone();
        if !self.started {
            self.first_frame(ctx);
        }
        self.drain(ctx);
        self.keys(ctx);

        egui::Panel::left("projects").resizable(false).min_size(260.0).show(ui, |ui| {
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
                ui.weak(format!("Editing {}. Pick another program on the left.", self.programs[self.selected].name));
            } else {
                ui.weak("Seed data for the shared database (CRUD Hub).");
            }
            ui.add_space(4.0);
        });

        egui::Panel::top("jobs").show(ui, |ui| self.job_tabs(ui));

        egui::CentralPanel::default().show(ui, |ui| {
            if self.root.is_none() {
                ui.colored_label(Color32::YELLOW, "Portfolio root not found: start the console inside the portfolio folder.");
                return;
            }
            match self.view {
                View::Run => {}
                View::Versions if !self.programs.is_empty() => {
                    egui::ScrollArea::vertical().id_salt("versions").max_height(ui.available_height() * 0.6).show(ui, |ui| self.versions_view(ui, ctx));
                    ui.separator();
                }
                View::Seed => {
                    egui::ScrollArea::vertical().id_salt("seed").max_height(ui.available_height() * 0.6).show(ui, |ui| self.seed_view(ui, ctx));
                    ui.separator();
                }
                _ => {}
            }
            self.log(ui);
        });

        self.write_self_smoke(ctx);
    }
}

struct Args {
    install: bool,
    uninstall: bool,
    version: bool,
    quiet: bool,
    root: Option<PathBuf>,
    smoke: Option<PathBuf>,
}

fn parse_args(args: &[String]) -> Result<Args, String> {
    let mut a = Args { install: false, uninstall: false, version: false, quiet: false, root: None, smoke: None };
    let mut it = args.iter();
    while let Some(x) = it.next() {
        match x.trim_start_matches('-') {
            "install" => a.install = true,
            "uninstall" => a.uninstall = true,
            "version" => a.version = true,
            "quiet" => a.quiet = true,
            "root" => a.root = Some(it.next().ok_or("--root needs a folder")?.into()),
            "smoke" => a.smoke = Some(it.next().ok_or("--smoke needs a file")?.into()),
            _ => return Err(format!("unknown option {x}")),
        }
    }
    Ok(a)
}

/// Show a result: a message box normally, nothing with --quiet (the exit code still tells).
fn tell(quiet: bool, text: &str, error: bool) {
    if !quiet {
        let icon = if error { "Error" } else { "Information" };
        let script = format!(
            "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('{}', '{}', 'OK', '{icon}') | Out-Null",
            text.replace('\'', "''"),
            install::NAME
        );
        let _ = std::process::Command::new("powershell").args(["-NoProfile", "-Command", &script]).status();
    }
}

fn main() {
    let argv: Vec<String> = std::env::args().skip(1).collect();
    let args = match parse_args(&argv) {
        Ok(a) => a,
        Err(e) => {
            tell(false, &e, true);
            std::process::exit(2);
        }
    };
    if args.version {
        println!("{VERSION}");
        return;
    }
    let exe = std::env::current_exe().unwrap_or_default();
    let exe_dir = exe.parent().map(Path::to_path_buf).unwrap_or_default();
    if args.install || args.uninstall {
        let env = |k: &str| std::env::var(k).ok();
        let result = install::plan(&env, args.root.as_deref()).and_then(|p| {
            if args.install {
                let config = [exe_dir.join("config"), PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("config")]
                    .into_iter()
                    .find(|d| d.is_dir());
                install::install(&p, &exe, config.as_deref(), VERSION)
                    .map(|_| format!("{} {VERSION} is installed in {}.", install::NAME, p.dir.display()))
            } else {
                install::uninstall(&p, &exe).map(|_| format!("{} is uninstalled. Your settings are kept.", install::NAME))
            }
        });
        match result {
            Ok(msg) => tell(args.quiet, &msg, false),
            Err(e) => {
                tell(args.quiet, &e, true);
                std::process::exit(1);
            }
        }
        return;
    }

    let root = std::env::current_dir()
        .ok()
        .and_then(|d| registry::find_root(&d))
        .or_else(|| registry::find_root(&exe_dir));
    let mut layers = vec![exe_dir.join("config")];
    if let Some(r) = &root {
        layers.insert(0, r.join("dev_console").join("config"));
    }
    let local = std::env::var_os("LOCALAPPDATA").map(PathBuf::from);
    let cfg = config::load(&layers, config::user_dir(local.as_deref()));

    let opts = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_title(TITLE)
            .with_inner_size([1100.0, 720.0])
            .with_icon(window_icon()),
        ..Default::default()
    };
    let smoke = args.smoke;
    if let Err(e) = eframe::run_native(TITLE, opts, Box::new(move |_| Ok(Box::new(App::new(cfg, root, smoke))))) {
        tell(args.quiet, &e.to_string(), true);
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn v(a: &[&str]) -> Vec<String> {
        a.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn args_parse_both_dash_styles() {
        let a = parse_args(&v(&["--install", "-root", "X", "--quiet"])).unwrap();
        assert!(a.install && a.quiet && !a.uninstall);
        assert_eq!(a.root.as_deref(), Some(Path::new("X")));
        assert_eq!(parse_args(&v(&["--smoke", "r.json"])).unwrap().smoke.as_deref(), Some(Path::new("r.json")));
        assert!(parse_args(&v(&["--root"])).is_err());
        assert!(parse_args(&v(&["--bogus"])).is_err());
    }

    #[test]
    fn window_icon_is_32px_rgba() {
        let icon = window_icon();
        assert_eq!((icon.width, icon.height), (32, 32));
        assert_eq!(icon.rgba.len(), 32 * 32 * 4);
    }

    #[test]
    fn shortcut_text_reads_back() {
        let sc = config::shortcut("Ctrl+Shift+T").unwrap().unwrap();
        assert_eq!(sc_text(&sc), "Ctrl+Shift+T");
        assert_eq!(sc_text(&config::shortcut("F5").unwrap().unwrap()), "F5");
    }

    #[test]
    fn default_version_files_all_have_a_version() {
        let root = registry::find_root(Path::new(env!("CARGO_MANIFEST_DIR"))).unwrap();
        let (programs, _) = registry::load(&config::parse(include_str!("../config/programs.ini")));
        for p in &programs {
            for f in &p.version_files {
                let s = versions::find_in(&root.join(&p.dir).join(f)).unwrap();
                assert!(versions::valid(&s.value), "{}/{f}: {}", p.dir, s.value);
            }
        }
    }
}

// ==== stamp v1 | author=kjFriday | hmac-sha256=6c0d8fce49119333dac1d9c92b48836b1521dd90acf3afacd7558708306e8a60 ====
