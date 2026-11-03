// ==== Generic Company Inc. portfolio ====================================
// Project: dev_console | File: src/app.rs
// About: The console's state and what it does: jobs and their events, live tests, the live site...
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
// ========================================================================

//! The console's state and what it does: jobs and their events, live tests, the live site, seed data and
//! versions. The keyboard controls are in app/keys.rs; the drawing, with the frame loop that calls all of
//! this, is in app/views.rs and app/views/.

mod keys;
mod views;

use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{Receiver, Sender, channel};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use eframe::egui;

use crate::jobs::{self, Event, Job, Status};
use crate::registry::{self, Action, Program};
use crate::{TITLE, VERSION, config, desktop, live, production, seed, versions};

const TEST: usize = 1; // index of Action::Test in Action::ALL
const CONFIRM_FOR: Duration = Duration::from_secs(5);

/// The window's views. ALL holds each view with its tab label, its controls.ini key and its hover help, in tab
/// order.
#[derive(Clone, Copy, PartialEq, Eq)]
enum View {
    Run,
    Versions,
    Seed,
    Production,
}

impl View {
    const ALL: [(View, &'static str, &'static str, &'static str); 4] = [
        (
            View::Run,
            "Run",
            "view_run",
            "Build, test, run and smoke-check the selected program, and read its output.",
        ),
        (
            View::Versions,
            "Versions & commands",
            "view_versions",
            "Change the selected program's version (in every file that holds it) and the commands the console runs for it.",
        ),
        (
            View::Seed,
            "Seed data",
            "view_seed",
            "The CRUD Hub's shared database: row counts, backups, reseeding and mock snapshots.",
        ),
        (
            View::Production,
            "live-production",
            "view_production",
            "Start and stop a program's live site from its production command, open it, and check what it answers.",
        ),
    ];
}

/// What a job belongs to.
#[derive(Clone, Copy, PartialEq, Eq)]
enum Kind {
    /// (program index, action index in Action::ALL)
    Program(usize, usize),
    Desktop,
    Seed(seed::Op),
    Stamp,
    /// A program's live site (its production command).
    Production(usize),
}

/// A job's process, once it runs.
#[derive(Default)]
struct Proc {
    pid: Option<u32>,
    started: Option<Instant>,
    /// Stop was pressed: the job ends as Stopped, not as a failure.
    stopped: bool,
    /// Cleared when the job ends, so a thread waiting for its port gives up.
    alive: Option<Arc<AtomicBool>>,
}

/// Results from a checks thread: the URL checked and its outcomes.
type Checked = (String, Vec<production::Outcome>);

/// The console's whole state. Each job has one entry in four lists indexed by its id (`jobs`, `smoke`,
/// `kind`, `procs`): add_job pushes to all four, and nothing is removed.
pub struct App {
    root: Option<PathBuf>,
    cfg: config::Config,
    programs: Vec<Program>,
    zoom: f32,
    view: View,
    selected: usize,
    jobs: Vec<Job>,
    /// Smoke report file per job, read when the job ends.
    smoke: Vec<Option<PathBuf>>,
    /// What each job belongs to.
    kind: Vec<Kind>,
    /// Each job's process.
    procs: Vec<Proc>,
    /// The job whose log is shown.
    shown: Option<usize>,
    /// Last finished status per (program, action).
    last: Vec<[Option<Status>; Action::ALL.len()]>,
    tx: Sender<Event>,
    rx: Receiver<Event>,
    /// Live tests on or off per program, shared with the watcher thread.
    live: Arc<Mutex<Vec<bool>>>,
    /// Programs whose folders changed, from the watcher thread that first_frame starts.
    live_rx: Option<Receiver<usize>>,
    /// `--smoke FILE`: write a report after the first frame, then close.
    self_smoke: Option<PathBuf>,
    /// first_frame has run.
    started: bool,
    /// Messages from the last save or version change, shown in the Versions view.
    notes: Vec<(bool, String)>,
    ver: Versions,
    seed: SeedView,
    prod: ProdView,
}

/// live-production view state.
struct ProdView {
    /// The program shown (an index into `programs`).
    pick: Option<usize>,
    outcomes: Vec<production::Outcome>,
    /// When the outcomes were taken, and the URL they were taken from.
    checked: Option<(Instant, String)>,
    checking: bool,
    /// The address a check is waiting on, while a just-started server comes up.
    waiting: Option<String>,
    keep_checking: bool,
    note: Option<(bool, String)>,
    tx: Sender<Checked>,
    rx: Receiver<Checked>,
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
    /// The state for the programs in `cfg`; `root` is the portfolio folder, if it was found.
    pub fn new(cfg: config::Config, root: Option<PathBuf>, self_smoke: Option<PathBuf>) -> Self {
        let (tx, rx) = channel();
        let zoom = cfg.number("view", "zoom", 1.0);
        let (programs, problems) = registry::load(&cfg.programs);
        let mut cfg = cfg;
        cfg.warnings.extend(problems);
        let n = programs.len();
        let env = |k: &str| std::env::var(k).ok();
        let db = seed::default_db(&env)
            .map(|p| p.display().to_string())
            .unwrap_or_default();
        let (ptx, prx) = channel();
        App {
            root,
            cfg,
            zoom,
            view: View::Run,
            selected: 0,
            jobs: vec![],
            smoke: vec![],
            kind: vec![],
            procs: vec![],
            shown: None,
            last: vec![Default::default(); n],
            tx,
            rx,
            live: Arc::new(Mutex::new(vec![false; n])),
            live_rx: None,
            self_smoke,
            started: false,
            notes: vec![],
            ver: Versions {
                for_program: None,
                spots: vec![],
                new_version: String::new(),
                edit: programs.clone(),
            },
            seed: SeedView {
                db,
                counts: None,
                counts_error: None,
                backups: vec![],
                pick: None,
                armed: None,
                loaded: false,
            },
            prod: ProdView {
                pick: None,
                outcomes: vec![],
                checked: None,
                checking: false,
                waiting: None,
                keep_checking: false,
                note: None,
                tx: ptx,
                rx: prx,
            },
            programs,
        }
    }

    /// Runs once, on the first frame: the text size, and the thread that watches program folders for Live tests.
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
        let mut job = Job {
            title,
            lines: vec![],
            status: Status::Running,
        };
        job.push(header);
        self.jobs.push(job);
        self.smoke.push(smoke);
        self.kind.push(kind);
        self.procs.push(Proc::default());
        self.shown = Some(id);
        id
    }

    fn wake(ctx: &egui::Context) -> impl Fn() + Send + Clone + 'static {
        let ctx = ctx.clone();
        move || ctx.request_repaint()
    }

    /// Start action `a` (an index in Action::ALL) of program `p`, unless it is running already.
    fn start(&mut self, ctx: &egui::Context, p: usize, a: usize) {
        let Some(root) = self.root.clone() else { return };
        if p >= self.programs.len() || self.busy(Kind::Program(p, a)) {
            return;
        }
        let report = std::env::temp_dir().join(format!(
            "gc-console-smoke-{}-{}.json",
            std::process::id(),
            self.jobs.len()
        ));
        let Some(cmd) = registry::command(&self.programs[p], Action::ALL[a], &root, &report) else {
            return;
        };
        let title = format!("{} · {}", self.programs[p].name, Action::ALL[a].label());
        let header = format!("> {} {}", cmd.program, cmd.args.join(" "));
        let id = self.add_job(
            title,
            header,
            Kind::Program(p, a),
            (Action::ALL[a] == Action::Smoke).then_some(report),
        );
        self.last[p][a] = Some(Status::Running);
        jobs::spawn(id, cmd, self.tx.clone(), Self::wake(ctx));
    }

    /// The event pump, once per frame (and in tests): job events, then check results, then the timers.
    fn drain(&mut self, ctx: &egui::Context) {
        self.drain_jobs(ctx);
        self.drain_checks();
        self.tick(ctx);
    }

    /// Apply the job events that arrived since the last frame. A job that ends is marked Stopped if Stop was
    /// pressed, lets a check waiting for its port give up, adds its --smoke report to its log, and then runs its
    /// follow-up: the last-run mark, the seed counts or a seed refresh, or the restamp note.
    fn drain_jobs(&mut self, ctx: &egui::Context) {
        while let Ok(ev) = self.rx.try_recv() {
            match ev {
                Event::Started(id, pid) => {
                    self.procs[id].pid = Some(pid);
                    self.procs[id].started.get_or_insert_with(Instant::now);
                }
                Event::Line(id, l) => self.jobs[id].push(l),
                Event::Done(id, s) => {
                    let s = if self.procs[id].stopped {
                        self.jobs[id].push("stopped from the console".into());
                        Status::Stopped
                    } else {
                        s
                    };
                    if let Some(alive) = &self.procs[id].alive {
                        alive.store(false, Ordering::Relaxed);
                    }
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
                            self.notes.push((
                                ok,
                                if ok {
                                    "Stamps renewed.".into()
                                } else {
                                    "tools/stamp.py --restamp failed; see its log.".into()
                                },
                            ));
                        }
                        Kind::Desktop | Kind::Production(_) => {}
                    }
                }
            }
        }
    }

    /// Take the results of a finished production check.
    fn drain_checks(&mut self) {
        while let Ok((url, outcomes)) = self.prod.rx.try_recv() {
            self.prod.outcomes = outcomes;
            self.prod.checked = Some((Instant::now(), url));
            self.prod.checking = false;
            self.prod.waiting = None;
        }
    }

    /// The rest of the frame's bookkeeping: the keep-checking timer, a test run for each program whose files
    /// changed (Live tests), and the end of a second-click confirm that was not answered in time.
    fn tick(&mut self, ctx: &egui::Context) {
        if self.prod.keep_checking && !self.prod.checking {
            let every = Duration::from_secs_f32(self.cfg.number("production", "interval_s", 30.0).max(5.0));
            if let Some(p) = self.prod.pick {
                if self.prod.checked.as_ref().is_none_or(|(t, _)| t.elapsed() >= every) {
                    self.check_production(ctx, p, None);
                }
            }
        }
        let changed: Vec<usize> = self
            .live_rx
            .as_ref()
            .map(|r| r.try_iter().collect())
            .unwrap_or_default();
        for p in changed {
            self.start(ctx, p, TEST);
        }
        if self.seed.armed.is_some_and(|(_, t)| t.elapsed() > CONFIRM_FOR) {
            self.seed.armed = None;
        }
    }

    /// Whether a job of `kind` is running.
    fn busy(&self, kind: Kind) -> bool {
        self.kind
            .iter()
            .zip(&self.jobs)
            .any(|(&k, j)| k == kind && j.status == Status::Running)
    }

    /// Whether any seed job is running.
    fn seed_busy(&self) -> bool {
        self.kind
            .iter()
            .zip(&self.jobs)
            .any(|(k, j)| matches!(k, Kind::Seed(_)) && j.status == Status::Running)
    }

    /// Start a desktop-shortcut job: build and place the set (`make`), or take it away.
    fn desktop_job(&mut self, ctx: &egui::Context, make: bool) {
        let (Some(root), Some(user)) = (self.root.clone(), self.cfg.user_dir.clone()) else {
            return;
        };
        if self.busy(Kind::Desktop) {
            return;
        }
        let title = if make {
            "Desktop shortcuts"
        } else {
            "Remove desktop shortcuts"
        };
        let id = self.add_job(title.into(), format!("> {title}"), Kind::Desktop, None);
        if make {
            desktop::make(
                id,
                self.programs.clone(),
                root,
                user,
                None,
                self.tx.clone(),
                Self::wake(ctx),
            );
        } else {
            desktop::remove(id, user, self.tx.clone(), Self::wake(ctx));
        }
    }

    // ---- live production ---------------------------------------------------------------------

    /// The running live-site job of program `p`, if any.
    fn production_job(&self, p: usize) -> Option<usize> {
        (0..self.jobs.len())
            .rev()
            .find(|&id| self.kind[id] == Kind::Production(p) && self.jobs[id].status == Status::Running)
    }

    /// The last live-site job of program `p`, running or not.
    fn last_production_job(&self, p: usize) -> Option<usize> {
        (0..self.jobs.len())
            .rev()
            .find(|&id| self.kind[id] == Kind::Production(p))
    }

    /// Folders whose paths a public page must never show: the user's own and the portfolio's.
    fn local_paths(&self) -> Vec<PathBuf> {
        let mut v: Vec<PathBuf> = ["USERPROFILE", "LOCALAPPDATA"]
            .iter()
            .filter_map(|k| std::env::var_os(k))
            .map(PathBuf::from)
            .collect();
        v.extend(self.root.clone());
        v
    }

    /// Start program `p`'s live site, then check it once its address answers.
    fn start_production(&mut self, ctx: &egui::Context, p: usize) {
        let Some(root) = self.root.clone() else { return };
        if self.production_job(p).is_some() {
            return;
        }
        let prog = self.programs[p].clone();
        let Some(cmd) = registry::Cmd::new(registry::split_args(&prog.production), root.join(&prog.dir)) else {
            return;
        };
        let addr = production::host_port(&prog.production_url);
        if let Some(a) = addr
            .as_deref()
            .filter(|a| production::answers(a, Duration::from_millis(300)))
        {
            self.prod.note = Some((
                false,
                format!(
                    "Something already answers on {a}. Stop it first, so the checks reach the server started here."
                ),
            ));
            return;
        }
        self.prod.note = None;
        let header = format!("> {} {}", cmd.program, cmd.args.join(" "));
        let id = self.add_job(
            format!("{} · live-production", prog.name),
            header,
            Kind::Production(p),
            None,
        );
        let alive = Arc::new(AtomicBool::new(true));
        self.procs[id].alive = Some(alive.clone());
        jobs::spawn(id, cmd, self.tx.clone(), Self::wake(ctx));
        if let Some(a) = addr {
            let wait = Duration::from_secs_f32(self.cfg.number("production", "start_wait_s", 120.0).max(1.0));
            self.check_production(ctx, p, Some((a, wait, alive)));
        }
    }

    /// Check program `p`'s site on a thread; with `wait`, first wait for its address to answer.
    fn check_production(&mut self, ctx: &egui::Context, p: usize, wait: Option<(String, Duration, Arc<AtomicBool>)>) {
        let url = self.programs[p].production_url.trim().to_string();
        if url.is_empty() || self.prod.checking {
            return;
        }
        let checks = match production::parse_checks(&self.programs[p].production_checks) {
            Ok(c) => c,
            Err(e) => {
                self.prod.note = Some((false, format!("production_checks: {e}")));
                return;
            }
        };
        let leaks = production::leak_patterns(&self.local_paths());
        let timeout = Duration::from_secs_f32(self.cfg.number("production", "timeout_s", 10.0).max(1.0));
        let (tx, wake) = (self.prod.tx.clone(), Self::wake(ctx));
        self.prod.checking = true;
        self.prod.waiting = wait.as_ref().map(|(a, _, _)| a.clone());
        std::thread::spawn(move || {
            let outcomes = match wait {
                Some((addr, limit, alive)) if !production::wait_for(&addr, limit, &alive) => {
                    let detail = if alive.load(Ordering::Relaxed) {
                        format!("not answering after {} s", limit.as_secs())
                    } else {
                        "ended before it answered; see its log".to_string()
                    };
                    vec![production::Outcome {
                        label: format!("Server on {addr}"),
                        ok: false,
                        detail,
                        ms: None,
                    }]
                }
                _ => production::run(&url, &checks, &leaks, timeout),
            };
            let _ = tx.send((url, outcomes));
            wake();
        });
    }

    /// Stop job `id`'s process and everything it started.
    fn stop_job(&mut self, id: usize) {
        let Some(pid) = self.procs[id].pid else { return };
        self.procs[id].stopped = true;
        if let Err(e) = jobs::stop(pid) {
            self.procs[id].stopped = false;
            self.jobs[id].push(format!("stop: {e}"));
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
        let backup = self
            .seed
            .pick
            .and_then(|i| self.seed.backups.get(i))
            .map(|b| b.path.clone());
        let Some(cmd) = seed::command(op, &root, &db, backup.as_deref()) else {
            return;
        };
        let header = match op {
            seed::Op::Restore => format!(
                "> restore {} from {}",
                db.display(),
                backup.unwrap_or_default().display()
            ),
            seed::Op::Counts | seed::Op::Backup => format!("> {} {}", op.label().to_lowercase(), db.display()),
            _ => format!("> {} {}", cmd.program, cmd.args.join(" ")),
        };
        let id = self.add_job(format!("Seed · {}", op.label()), header, Kind::Seed(op), None);
        jobs::spawn(id, cmd, self.tx.clone(), Self::wake(ctx));
    }

    /// Rescan backups and re-read the counts.
    fn refresh_seed(&mut self, ctx: &egui::Context) {
        self.seed.loaded = true;
        let picked = self
            .seed
            .pick
            .and_then(|i| self.seed.backups.get(i))
            .map(|b| b.path.clone());
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
        self.ver.spots = p
            .version_files
            .iter()
            .map(|f| versions::find_in(&root.join(&p.dir).join(f)))
            .collect();
        self.ver.for_program = Some(self.selected);
        self.ver.new_version = self
            .ver
            .spots
            .iter()
            .flatten()
            .next()
            .map(|s| s.value.clone())
            .unwrap_or_default();
    }

    fn apply_version(&mut self, ctx: &egui::Context) {
        let Some(root) = self.root.clone() else { return };
        let spots: Vec<versions::Spot> = self.ver.spots.iter().flatten().cloned().collect();
        let new = self.ver.new_version.trim().to_string();
        let name = self.programs[self.selected].name.clone();
        match versions::set(&spots, &new) {
            Err(e) => self.notes.push((false, e)),
            Ok(changed) if changed.is_empty() => {
                self.notes.push((true, format!("{name} is already {new} everywhere.")))
            }
            Ok(changed) => {
                let rel: Vec<String> = changed
                    .iter()
                    .map(|f| f.strip_prefix(&root).unwrap_or(f).to_string_lossy().replace('\\', "/"))
                    .collect();
                self.notes
                    .push((true, format!("{name} is now {new} in {}.", rel.join(", "))));
                // Stamped sources need a new stamp after an edit; JSON files carry none.
                let stamped: Vec<String> = rel.into_iter().filter(|f| !f.ends_with(".json")).collect();
                if !stamped.is_empty() && root.join("tools").join("stamp.py").is_file() {
                    let mut words = vec!["python".to_string(), "tools/stamp.py".into(), "--restamp".into()];
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
            self.notes
                .push((false, "No config folder to save programs.ini in.".into()));
            return;
        };
        let text = registry::render(&self.ver.edit);
        let (check, problems) = registry::load(&config::parse(&text));
        if !problems.is_empty() || check.len() != self.ver.edit.len() {
            self.notes.push((false, format!("Not saved: {}", problems.join("; "))));
            return;
        }
        let result = path
            .parent()
            .map_or(Ok(()), std::fs::create_dir_all)
            .and_then(|_| std::fs::write(&path, text));
        match result {
            Ok(()) => {
                self.programs = self.ver.edit.clone();
                self.notes.push((true, format!("Saved to {}.", path.display())));
            }
            Err(e) => self
                .notes
                .push((false, format!("Could not save {}: {e}", path.display()))),
        }
    }

    // ---- live, zoom --------------------------------------------------------------------------

    fn is_live(&self, p: usize) -> bool {
        self.live.lock().unwrap()[p]
    }

    fn set_live(&mut self, p: usize, on: bool) {
        self.live.lock().unwrap()[p] = on;
    }

    fn set_zoom(&mut self, ctx: &egui::Context, z: f32) {
        let (lo, hi) = (
            self.cfg.number("view", "zoom_min", 0.5),
            self.cfg.number("view", "zoom_max", 3.0),
        );
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

    // ---- smoke report ------------------------------------------------------------------------

    /// `--smoke FILE`: after the first frame, write the report and close the window.
    fn write_self_smoke(&mut self, ctx: &egui::Context) {
        let Some(path) = self.self_smoke.take() else { return };
        let views: Vec<String> = View::ALL
            .iter()
            .map(|(_, label, _, _)| format!("\"{label}\""))
            .collect();
        let sites = self.programs.iter().filter(|p| p.has_production()).count();
        let report = format!(
            "{{\"title\": \"{}\", \"version\": \"{VERSION}\", \"programs\": {}, \"root_found\": {}, \"controls\": {}, \"warnings\": {}, \"views\": [{}], \"live_sites\": {sites}}}\n",
            TITLE,
            self.programs.len(),
            self.root.is_some(),
            self.cfg.controls.len(),
            self.cfg.warnings.len(),
            views.join(", ")
        );
        let _ = std::fs::write(path, report);
        ctx.send_viewport_cmd(egui::ViewportCommand::Close);
    }
}

impl Drop for App {
    /// Closing the console must not leave a live site running with no console to stop it.
    fn drop(&mut self) {
        for id in 0..self.jobs.len() {
            if matches!(self.kind[id], Kind::Production(_)) && self.jobs[id].status == Status::Running {
                if let Some(pid) = self.procs[id].pid {
                    let _ = jobs::stop(pid);
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    /// The view's own Start, checks and Stop, on the Journal at a free port. Needs Go; slow.
    #[test]
    #[ignore]
    fn app_starts_checks_and_stops_the_live_site() {
        let root = registry::find_root(Path::new(env!("CARGO_MANIFEST_DIR"))).unwrap();
        let mut app = App::new(
            config::load(&[root.join("tools").join("dev_console").join("config")], None),
            Some(root),
            None,
        );
        let p = app.programs.iter().position(|p| p.name == "Journal").unwrap();
        let port = std::net::TcpListener::bind("127.0.0.1:0")
            .unwrap()
            .local_addr()
            .unwrap()
            .port();
        let addr = format!("127.0.0.1:{port}");
        let old = production::host_port(&app.programs[p].production_url).unwrap();
        app.programs[p].production = app.programs[p].production.replace(&old, &addr);
        app.programs[p].production_url = format!("http://{addr}");
        let ctx = egui::Context::default();
        app.start_production(&ctx, p);
        let id = app.production_job(p).expect("Start made no job");
        let started = Instant::now();
        while app.prod.checked.is_none() {
            assert!(started.elapsed() < Duration::from_secs(180), "no check results");
            std::thread::sleep(Duration::from_millis(200));
            app.drain(&ctx);
        }
        let failed: Vec<_> = app.prod.outcomes.iter().filter(|o| !o.ok).collect();
        assert!(
            failed.is_empty() && app.prod.outcomes.len() >= 7,
            "{:#?}",
            app.prod.outcomes
        );
        assert!(app.procs[id].pid.is_some());
        app.stop_job(id);
        let stopping = Instant::now();
        while app.jobs[id].status == Status::Running {
            assert!(stopping.elapsed() < Duration::from_secs(20), "still running after Stop");
            std::thread::sleep(Duration::from_millis(100));
            app.drain(&ctx);
        }
        assert_eq!(app.jobs[id].status, Status::Stopped);
        assert!(
            !production::answers(&addr, Duration::from_millis(500)),
            "{addr} still answers after Stop"
        );
    }
}

// ==== stamp v1 | author=kjFriday | hmac-sha256=e701841fb56ae042e93d2d918eb799041864acd88821c0d91b4c2a12b2023752 ====
