// ==== Generic Company Inc. portfolio ====================================
// Project: portfolio | File: dev_console/src/jobs.rs
// About: Background jobs: run a command, stream its output lines back to the window.
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
// ========================================================================

//! Background jobs: run a command, stream its output lines back to the window.

use std::io::{BufRead, BufReader, Read};
use std::process::{Command, Stdio};
use std::sync::mpsc::Sender;
use std::thread;

use crate::registry::Cmd;

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Status {
    Running,
    Exited(i32),
    Failed(String),
    /// Ended from the console (Stop), whatever exit code the kill left.
    Stopped,
}

pub enum Event {
    /// The job's process is running, with this process id.
    Started(usize, u32),
    Line(usize, String),
    Done(usize, Status),
}

pub struct Job {
    pub title: String,
    pub lines: Vec<String>,
    pub status: Status,
}

/// Lines kept per job; older ones are dropped.
pub const MAX_LINES: usize = 5000;

impl Job {
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
pub fn spawn(id: usize, cmd: Cmd, tx: Sender<Event>, wake: impl Fn() + Send + Clone + 'static) {
    thread::spawn(move || {
        let status = run(id, &cmd, &tx, &wake);
        let _ = tx.send(Event::Done(id, status));
        wake();
    });
}

/// Run `cmd` on this thread, streaming its lines to `tx` as job `id`; returns how it ended.
pub fn run(id: usize, cmd: &Cmd, tx: &Sender<Event>, wake: &(impl Fn() + Send + Clone + 'static)) -> Status {
    let mut c = Command::new(&cmd.program);
    c.args(&cmd.args).current_dir(&cmd.cwd).stdout(Stdio::piped()).stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        c.creation_flags(0x0800_0000); // CREATE_NO_WINDOW: no console flashes for child tools
    }
    let mut child = match c.spawn() {
        Ok(ch) => ch,
        Err(e) => return Status::Failed(format!("{}: {e}", cmd.program)),
    };
    let _ = tx.send(Event::Started(id, child.id()));
    let readers = [pipe(child.stdout.take(), id, tx, wake), pipe(child.stderr.take(), id, tx, wake)];
    for r in readers.into_iter().flatten() {
        let _ = r.join();
    }
    match child.wait() {
        Ok(s) => Status::Exited(s.code().unwrap_or(-1)),
        Err(e) => Status::Failed(e.to_string()),
    }
}

/// End process `pid` and every process it started (`go run` starts the real server as a child).
pub fn stop(pid: u32) -> Result<(), String> {
    let mut c = Command::new("taskkill");
    c.args(["/PID", &pid.to_string(), "/T", "/F"]).stdout(Stdio::null()).stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        c.creation_flags(0x0800_0000);
    }
    let out = c.output().map_err(|e| format!("taskkill: {e}"))?;
    if out.status.success() {
        Ok(())
    } else {
        Err(String::from_utf8_lossy(&out.stderr).trim().to_string())
    }
}

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

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::mpsc::channel;

    #[test]
    fn push_caps_lines() {
        let mut j = Job { title: "t".into(), lines: vec![], status: Status::Running };
        for i in 0..MAX_LINES + 10 {
            j.push(i.to_string());
        }
        assert_eq!(j.lines.len(), MAX_LINES);
        assert_eq!(j.lines[0], "10");
    }

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

    #[test]
    fn stop_ends_the_process_and_its_children() {
        let (tx, rx) = channel();
        // cmd starts ping as a child: stopping cmd must take the child with it
        let cmd = Cmd { program: "cmd".into(), args: vec!["/C".into(), "ping -n 60 127.0.0.1 >nul".into()], cwd: std::env::temp_dir() };
        spawn(2, cmd, tx, || {});
        let Event::Started(2, pid) = rx.recv().unwrap() else { panic!("expected Started first") };
        stop(pid).unwrap();
        let done = loop {
            match rx.recv_timeout(std::time::Duration::from_secs(10)).expect("job did not end after stop") {
                Event::Done(2, s) => break s,
                _ => {}
            }
        };
        assert_ne!(done, Status::Running);
    }

    #[test]
    fn spawn_reports_missing_program() {
        let (tx, rx) = channel();
        let cmd = Cmd { program: "no-such-program-gc".into(), args: vec![], cwd: std::env::temp_dir() };
        spawn(1, cmd, tx, || {});
        match rx.recv().unwrap() {
            Event::Done(1, Status::Failed(_)) => {}
            _ => panic!("expected failure"),
        }
    }
}

// ==== stamp v1 | author=kjFriday | hmac-sha256=86e722fd2536c7b44fe786688d6fd17f0b5900fa6e070d6f64379c300cb3ee61 ====
