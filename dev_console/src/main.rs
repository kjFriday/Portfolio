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

use std::path::{Path, PathBuf};
use std::sync::mpsc::{channel, Receiver, Sender};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use eframe::egui::{self, Key, KeyboardShortcut};
use jobs::{Event, Job, Status};
use registry::{Action, PROJECTS};

const VERSION: &str = env!("CARGO_PKG_VERSION");
const TITLE: &str = concat!("Generic Company Inc. — Dev Console ", env!("CARGO_PKG_VERSION"));
const TEST: usize = 1; // index of Action::Test in Action::ALL

struct App {
    root: Option<PathBuf>,
    cfg: config::Config,
    zoom: f32,
    selected: usize,
    jobs: Vec<Job>,
    /// Smoke report file per job, read when the job ends.
    smoke: Vec<Option<PathBuf>>,
    shown: Option<usize>,
    /// Last finished status per (project, action).
    last: Vec<[Option<Status>; Action::ALL.len()]>,
    /// (program, action) for each job; None for desktop-shortcut jobs.
    owner: Vec<Option<(usize, usize)>>,
    tx: Sender<Event>,
    rx: Receiver<Event>,
    live: Arc<Mutex<Vec<bool>>>,
    live_rx: Option<Receiver<usize>>,
    /// `--smoke FILE`: write a report after the first frame, then close.
    self_smoke: Option<PathBuf>,
    started: bool,
}

impl App {
    fn new(cfg: config::Config, root: Option<PathBuf>, self_smoke: Option<PathBuf>) -> Self {
        let (tx, rx) = channel();
        let zoom = cfg.number("view", "zoom", 1.0);
        App {
            root,
            cfg,
            zoom,
            selected: 0,
            jobs: vec![],
            smoke: vec![],
            shown: None,
            last: vec![Default::default(); PROJECTS.len()],
            owner: vec![],
            tx,
            rx,
            live: Arc::new(Mutex::new(vec![false; PROJECTS.len()])),
            live_rx: None,
            self_smoke,
            started: false,
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
            let skip = self.cfg.list("live", "skip");
            let every = Duration::from_millis(self.cfg.number("live", "interval_ms", 1000.0).max(200.0) as u64);
            let ctx = ctx.clone();
            std::thread::spawn(move || {
                let mut watches: Vec<live::Watch> = PROJECTS.iter().map(|_| live::Watch::default()).collect();
                loop {
                    let on = flags.lock().unwrap().clone();
                    for (i, p) in PROJECTS.iter().enumerate() {
                        if !on[i] {
                            watches[i] = live::Watch::default();
                            continue;
                        }
                        if watches[i].changed(live::newest(&root.join(p.dir), &skip)) {
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

    fn start(&mut self, ctx: &egui::Context, p: usize, a: usize) {
        let Some(root) = self.root.clone() else { return };
        if self.running(p, a) {
            return;
        }
        let id = self.jobs.len();
        let report = std::env::temp_dir().join(format!("gc-console-smoke-{}-{id}.json", std::process::id()));
        let Some(cmd) = registry::command(&PROJECTS[p], Action::ALL[a], &root, &report) else { return };
        let title = format!("{} · {}", PROJECTS[p].name, Action::ALL[a].label());
        let mut job = Job { title, lines: vec![], status: Status::Running };
        job.push(format!("> {} {}", cmd.program, cmd.args.join(" ")));
        self.jobs.push(job);
        self.smoke.push((Action::ALL[a] == Action::Smoke).then_some(report));
        self.owner.push(Some((p, a)));
        self.last[p][a] = Some(Status::Running);
        self.shown = Some(id);
        let ctx = ctx.clone();
        jobs::spawn(id, cmd, self.tx.clone(), move || ctx.request_repaint());
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
                    if let Some((p, a)) = self.owner[id] {
                        self.last[p][a] = Some(s.clone());
                    }
                    self.jobs[id].status = s;
                }
            }
        }
        let changed: Vec<usize> = self.live_rx.as_ref().map(|r| r.try_iter().collect()).unwrap_or_default();
        for p in changed {
            self.start(ctx, p, TEST);
        }
    }

    /// Start a desktop-shortcut job: build and place the set (`make`), or take it away.
    fn desktop_job(&mut self, ctx: &egui::Context, make: bool) {
        let (Some(root), Some(user)) = (self.root.clone(), self.cfg.user_dir.clone()) else { return };
        if self.desktop_busy() {
            return;
        }
        let id = self.jobs.len();
        let title = if make { "Desktop shortcuts" } else { "Remove desktop shortcuts" };
        self.jobs.push(Job { title: title.into(), lines: vec![], status: Status::Running });
        self.smoke.push(None);
        self.owner.push(None);
        self.shown = Some(id);
        let wake = { let ctx = ctx.clone(); move || ctx.request_repaint() };
        if make {
            desktop::make(id, root, user, None, self.tx.clone(), wake);
        } else {
            desktop::remove(id, user, self.tx.clone(), wake);
        }
    }

    fn desktop_busy(&self) -> bool {
        self.owner.iter().zip(&self.jobs).any(|(o, j)| o.is_none() && j.status == Status::Running)
    }

    fn running(&self, p: usize, a: usize) -> bool {
        self.owner.iter().zip(&self.jobs).any(|(&o, j)| o == Some((p, a)) && j.status == Status::Running)
    }

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
        if self.pressed(ctx, "test_all") {
            (0..PROJECTS.len()).for_each(|p| self.start(ctx, p, TEST));
        }
        if self.pressed(ctx, "desktop_shortcuts") {
            self.desktop_job(ctx, true);
        }
        if self.pressed(ctx, "next") {
            self.selected = (self.selected + 1) % PROJECTS.len();
        }
        if self.pressed(ctx, "previous") {
            self.selected = (self.selected + PROJECTS.len() - 1) % PROJECTS.len();
        }
        if self.pressed(ctx, "toggle_live") {
            let p = self.selected;
            self.set_live(p, !self.is_live(p));
        }
        for (a, act) in Action::ALL.iter().enumerate() {
            if self.pressed(ctx, &act.label().to_lowercase()) {
                self.start(ctx, self.selected, a);
            }
        }
    }

    fn hint(&self, action: &str) -> String {
        self.cfg.controls.get(action).map(|sc| format!(" ({})", sc_text(sc))).unwrap_or_default()
    }

    fn write_self_smoke(&mut self, ctx: &egui::Context) {
        let Some(path) = self.self_smoke.take() else { return };
        let report = format!(
            "{{\"title\": \"{}\", \"version\": \"{VERSION}\", \"programs\": {}, \"root_found\": {}, \"controls\": {}, \"warnings\": {}}}\n",
            TITLE,
            PROJECTS.len(),
            self.root.is_some(),
            self.cfg.controls.len(),
            self.cfg.warnings.len()
        );
        let _ = std::fs::write(path, report);
        ctx.send_viewport_cmd(egui::ViewportCommand::Close);
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

fn badge(s: &Option<Status>) -> (&'static str, egui::Color32) {
    match s {
        None => ("·", egui::Color32::GRAY),
        Some(Status::Running) => ("…", egui::Color32::LIGHT_BLUE),
        Some(Status::Exited(0)) => ("✔", egui::Color32::from_rgb(90, 190, 110)),
        Some(_) => ("✖", egui::Color32::from_rgb(220, 90, 80)),
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

        egui::Panel::left("projects").resizable(false).min_size(250.0).show(ui, |ui| {
            ui.heading("Programs");
            ui.separator();
            for (i, p) in PROJECTS.iter().enumerate() {
                ui.horizontal(|ui| {
                    let test = badge(&self.last[i][TEST]);
                    ui.colored_label(test.1, test.0);
                    if ui.selectable_label(self.selected == i, p.name).clicked() {
                        self.selected = i;
                    }
                    ui.weak(p.lang.label());
                    if self.is_live(i) {
                        ui.colored_label(egui::Color32::from_rgb(90, 190, 110), "live");
                    }
                });
            }
            ui.separator();
            if ui.button(format!("Test all{}", self.hint("test_all"))).clicked() {
                (0..PROJECTS.len()).for_each(|p| self.start(ctx, p, TEST));
            }
            ui.add_space(8.0);
            let can = self.root.is_some() && self.cfg.user_dir.is_some() && !self.desktop_busy();
            if ui
                .add_enabled(can, egui::Button::new(format!("Desktop shortcuts{}", self.hint("desktop_shortcuts"))))
                .on_hover_text("Build every program from source, then put a versioned shortcut to each build and to each source folder on the desktop.")
                .clicked()
            {
                self.desktop_job(ctx, true);
            }
            if ui.add_enabled(can, egui::Button::new("Remove desktop shortcuts")).clicked() {
                self.desktop_job(ctx, false);
            }
            ui.add_space(8.0);
            ui.horizontal(|ui| {
                ui.weak(format!("Text {:.0}%", self.zoom * 100.0));
                if ui.small_button("−").clicked() {
                    self.set_zoom(ctx, self.zoom - self.cfg.number("view", "zoom_step", 0.1));
                }
                if ui.small_button("+").clicked() {
                    self.set_zoom(ctx, self.zoom + self.cfg.number("view", "zoom_step", 0.1));
                }
            });
            for w in &self.cfg.warnings {
                ui.colored_label(egui::Color32::YELLOW, w);
            }
            ui.add_space(8.0);
            ui.collapsing("About", |ui| {
                ui.label(format!("{} {VERSION}", install::NAME));
                ui.weak("Generic Company Inc. is fictional. AGPL-3.0.");
                ui.weak("Icon: application_xp_terminal.png from the Silk icon set by Mark James, CC BY 2.5; enlarged by whole pixels.");
                ui.hyperlink_to("CC BY 2.5", "http://creativecommons.org/licenses/by/2.5/");
            });
        });

        egui::Panel::top("actions").show(ui, |ui| {
            let p = self.selected;
            ui.horizontal(|ui| {
                ui.strong(PROJECTS[p].name);
                ui.weak(PROJECTS[p].dir);
            });
            ui.horizontal(|ui| {
                let root = self.root.clone().unwrap_or_else(|| PathBuf::from("."));
                for (a, act) in Action::ALL.iter().enumerate() {
                    let applies = registry::command(&PROJECTS[p], *act, &root, &root).is_some();
                    let (mark, col) = badge(&self.last[p][a]);
                    let enabled = applies && self.root.is_some() && !self.running(p, a);
                    let label = format!("{}{}", act.label(), self.hint(&act.label().to_lowercase()));
                    if ui.add_enabled(enabled, egui::Button::new(label)).clicked() {
                        self.start(ctx, p, a);
                    }
                    ui.colored_label(col, mark);
                }
                let mut on = self.is_live(p);
                if ui.checkbox(&mut on, format!("Live tests{}", self.hint("toggle_live"))).changed() {
                    self.set_live(p, on);
                }
            });
            ui.add_space(4.0);
        });

        egui::Panel::top("jobs").show(ui, |ui| {
            egui::ScrollArea::horizontal().show(ui, |ui| {
                ui.horizontal(|ui| {
                    for (id, j) in self.jobs.iter().enumerate().rev() {
                        let (mark, col) = badge(&Some(j.status.clone()));
                        ui.colored_label(col, mark);
                        if ui.selectable_label(self.shown == Some(id), &j.title).clicked() {
                            self.shown = Some(id);
                        }
                    }
                });
            });
        });

        egui::CentralPanel::default().show(ui, |ui| {
            if self.root.is_none() {
                ui.colored_label(egui::Color32::YELLOW, "Portfolio root not found: start the console inside the portfolio folder.");
                return;
            }
            let Some(job) = self.shown.and_then(|i| self.jobs.get(i)) else {
                ui.weak("Pick a program and an action. Output appears here.");
                return;
            };
            match &job.status {
                Status::Running => ui.label("Running…"),
                Status::Exited(c) => ui.label(format!("Exited with code {c}")),
                Status::Failed(e) => ui.colored_label(egui::Color32::from_rgb(220, 90, 80), format!("Could not start: {e}")),
            };
            ui.separator();
            egui::ScrollArea::vertical().stick_to_bottom(true).auto_shrink(false).show(ui, |ui| {
                for l in &job.lines {
                    ui.monospace(l);
                }
            });
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
            .with_inner_size([1000.0, 640.0])
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
}

// ==== stamp v1 | author=kjFriday | hmac-sha256=fd22873f4ab5c6a015fca84ceefd6e1e3620c1893d776de486818266b64bb40a ====
