// ==== Generic Company Inc. portfolio ====================================
// Project: dev_console | File: src/jobs.rs
// About: Background jobs: run a command, stream its output lines back to the window.
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
// ========================================================================

//! Background jobs: run a command, stream its output lines back to the window.
//!
//! Every button that runs something (Build, Test, a seed op, the live site, a restamp) becomes a job. app.rs
//! gives it an id (its index in `App::jobs`), then calls `spawn`; desktop.rs calls `run` directly for each
//! build step on its own thread. The window never blocks: all it does each frame is drain the `Event`
//! channel.
//!
//! Flow of one job:
//! 1. `spawn` starts a runner thread that calls `run`.
//! 2. `run` starts the process with stdout and stderr piped, sends `Event::Started` with the process id
//!    (which Stop needs), and starts one reader thread per pipe.
//! 3. Each reader sends every line as `Event::Line` and calls `wake`, so egui repaints and shows it.
//! 4. When both pipes close, `run` waits for the exit code; the runner sends `Event::Done`.
//!
//! Stop goes through `stop`, which uses `taskkill /T` so the whole process tree ends.
//!
//! Defines `Status` (how a job stands), `Event` (what the threads send) and `Job` (a job's log and status).

use std::io::{BufRead, BufReader, Read};
use std::process::{Command, Stdio};
use std::sync::mpsc::Sender;
use std::thread;

use crate::registry::Cmd;

/// How a job stands: still running, or how it ended. Shown on the job tab and as a program's last-run mark.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Status {
    /// The process has not ended yet (also the state before it starts).
    Running,
    /// The process ended with this exit code; -1 when the system reports none.
    Exited(i32),
    /// The process could not be started or waited on; the text says why.
    Failed(String),
    /// Ended from the console (Stop), whatever exit code the kill left.
    ///
    /// This module never produces it: app.rs swaps it in for the `Done` status of a job whose Stop was pressed.
    Stopped,
}

/// A message from a job's threads to the window. The first field of each variant is the job id.
pub enum Event {
    /// The job's process is running, with this process id.
    Started(usize, u32),
    /// One line the process printed on stdout or stderr, without its line ending.
    Line(usize, String),
    /// The process ended (or never started); always the job's last event.
    Done(usize, Status),
}

/// One job as the window keeps it: the tab title, the log lines and the current status.
pub struct Job {
    /// The tab text, such as `Journal · Test`.
    pub title: String,
    /// The log: the header line app.rs adds, then the output, at most MAX_LINES.
    pub lines: Vec<String>,
    /// Updated from `Event::Done`.
    pub status: Status,
}

/// Lines kept per job; older ones are dropped.
///
/// 5000 keeps a long `cargo test` or build log whole while bounding memory and the work of drawing the log.
pub const MAX_LINES: usize = 5000;

// The log cap.
impl Job {
    /// Append `line` to the log, dropping the oldest lines past MAX_LINES.
    pub fn push(&mut self, line: String) {
        self.lines.push(line);
        if self.lines.len() > MAX_LINES {
            let extra = self.lines.len() - MAX_LINES;
            self.lines.drain(..extra);
        }
    }
}

/// Start `cmd` on a thread; output and the exit status arrive on `tx` tagged with `id`.
/// `wake` is called after each event so the window repaints.
///
/// Returns at once. The events arrive in the order Started (unless the program could not start), any
/// number of Lines, then exactly one Done. The thread is detached: the job lives until its process ends or
/// is stopped.
pub fn spawn(id: usize, cmd: Cmd, tx: Sender<Event>, wake: impl Fn() + Send + Clone + 'static) {
    thread::spawn(move || {
        let status = run(id, &cmd, &tx, &wake);
        let _ = tx.send(Event::Done(id, status));
        wake();
    });
}

/// Run `cmd` on this thread, streaming its lines to `tx` as job `id`; returns how it ended.
///
/// Sends Started and the Lines but not Done: the caller decides when the job is over (`spawn` sends Done
/// at once; desktop.rs runs several steps under one job id first). Blocks until the process ends.
///
/// Steps:
/// 1. Build the process in `cmd.cwd` with both pipes captured and no console window.
/// 2. A program that cannot start (not on PATH, bad folder) returns `Failed` without a Started event.
/// 3. Send Started with the process id, then read stdout and stderr on two threads, so neither pipe fills
///    up and stalls the child while the other is being read.
/// 4. Join both readers (they end when the child closes its pipes), then collect the exit code.
pub fn run(id: usize, cmd: &Cmd, tx: &Sender<Event>, wake: &(impl Fn() + Send + Clone + 'static)) -> Status {
    let mut c = Command::new(&cmd.program);
    c.args(&cmd.args)
        .current_dir(&cmd.cwd)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        c.creation_flags(crate::win::CREATE_NO_WINDOW); // no console flashes for child tools
    }
    let mut child = match c.spawn() {
        Ok(ch) => ch,
        Err(e) => return Status::Failed(format!("{}: {e}", cmd.program)),
    };
    let _ = tx.send(Event::Started(id, child.id()));
    let readers = [
        pipe(child.stdout.take(), id, tx, wake),
        pipe(child.stderr.take(), id, tx, wake),
    ];
    for r in readers.into_iter().flatten() {
        let _ = r.join();
    }
    // Known limitation: the readers end when every holder of the pipes has closed them, so a grandchild
    // that inherited the pipes and keeps running (a server started by `go run`) keeps the job Running until
    // it ends too; Stop's `taskkill /T` covers that case.
    match child.wait() {
        Ok(s) => Status::Exited(s.code().unwrap_or(-1)),
        Err(e) => Status::Failed(e.to_string()),
    }
}

/// End process `pid` and every process it started (`go run` starts the real server as a child).
///
/// Returns once taskkill has finished; the job's own Done event follows on its channel when the pipes close.
/// Err holds taskkill's message, for example when the process has already ended.
pub fn stop(pid: u32) -> Result<(), String> {
    // taskkill: /T ends the whole tree under the process, /F forces it (console tools started without a
    // window cannot receive a close request)
    let mut c = Command::new("taskkill");
    c.args(["/PID", &pid.to_string(), "/T", "/F"])
        .stdout(Stdio::null())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        c.creation_flags(crate::win::CREATE_NO_WINDOW);
    }
    let out = c.output().map_err(|e| format!("taskkill: {e}"))?;
    if out.status.success() {
        Ok(())
    } else {
        Err(String::from_utf8_lossy(&out.stderr).trim().to_string())
    }
}

/// Start a thread that reads `src` line by line and sends each line as job `id`; None when the pipe is absent.
///
/// The thread also stops when the window has dropped its receiver.
///
/// Known limitation: a line that is not valid UTF-8 (or any read error) ends the reading, since `lines()`
/// yields an error then; the rest of that pipe's output is not shown.
fn pipe<R: Read + Send + 'static>(
    src: Option<R>,
    id: usize,
    tx: &Sender<Event>,
    wake: &(impl Fn() + Send + Clone + 'static),
) -> Option<thread::JoinHandle<()>> {
    let src = src?;
    let (tx, wake) = (tx.clone(), wake.clone());
    Some(thread::spawn(move || {
        for line in BufReader::new(src).lines().map_while(Result::ok) {
            if tx.send(Event::Line(id, line)).is_err() {
                break;
            }
            wake();
        }
    }))
}

/// Unit tests: the log cap, and real child processes started through cmd.exe.
#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::mpsc::channel;

    // Ten lines past the cap leave exactly MAX_LINES, the oldest ten ("0" to "9") dropped.
    #[test]
    fn push_caps_lines() {
        let mut j = Job {
            title: "t".into(),
            lines: vec![],
            status: Status::Running,
        };
        for i in 0..MAX_LINES + 10 {
            j.push(i.to_string());
        }
        assert_eq!(j.lines.len(), MAX_LINES);
        assert_eq!(j.lines[0], "10");
    }

    // One echoed line, a non-zero exit code (3) and a real pid all arrive tagged with the job id; `echo hello&`
    // has no space before `&` so cmd prints no trailing space.
    #[test]
    fn spawn_streams_output_and_exit_code() {
        let (tx, rx) = channel();
        let cmd = Cmd {
            program: "cmd".into(),
            args: vec!["/C".into(), "echo hello& exit 3".into()],
            cwd: std::env::temp_dir(),
        };
        spawn(7, cmd, tx, || {});
        let (mut lines, mut pid) = (vec![], None);
        let status = loop {
            match rx.recv().unwrap() {
                Event::Started(7, p) => pid = Some(p),
                Event::Line(7, l) => lines.push(l),
                Event::Done(7, s) => break s,
                _ => panic!("wrong id"),
            }
        };
        assert_eq!(lines, ["hello"]);
        assert_eq!(status, Status::Exited(3));
        assert!(pid.is_some_and(|p| p > 0));
    }

    // A job blocked on a 60 s ping child ends within 10 s once stopped, so the tree kill works.
    #[test]
    fn stop_ends_the_process_and_its_children() {
        let (tx, rx) = channel();
        // cmd starts ping as a child: stopping cmd must take the child with it
        let cmd = Cmd {
            program: "cmd".into(),
            args: vec!["/C".into(), "ping -n 60 127.0.0.1 >nul".into()],
            cwd: std::env::temp_dir(),
        };
        spawn(2, cmd, tx, || {});
        let Event::Started(2, pid) = rx.recv().unwrap() else {
            panic!("expected Started first")
        };
        stop(pid).unwrap();
        let done = loop {
            match rx
                .recv_timeout(std::time::Duration::from_secs(10))
                .expect("job did not end after stop")
            {
                Event::Done(2, s) => break s,
                _ => {}
            }
        };
        assert_ne!(done, Status::Running);
    }

    // A program that is not on PATH sends Done(Failed) as its first event, with no Started.
    #[test]
    fn spawn_reports_missing_program() {
        let (tx, rx) = channel();
        let cmd = Cmd {
            program: "no-such-program-gc".into(),
            args: vec![],
            cwd: std::env::temp_dir(),
        };
        spawn(1, cmd, tx, || {});
        match rx.recv().unwrap() {
            Event::Done(1, Status::Failed(_)) => {}
            _ => panic!("expected failure"),
        }
    }
}

// ==== stamp v1 | author=kjFriday | hmac-sha256=c8196a722368654621ed3add2a1689b681e0e9767e6194b3adb3ae4682d5b94a ====
