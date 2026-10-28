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
}

pub enum Event {
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
        let mut c = Command::new(&cmd.program);
        c.args(&cmd.args).current_dir(&cmd.cwd).stdout(Stdio::piped()).stderr(Stdio::piped());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            c.creation_flags(0x0800_0000); // CREATE_NO_WINDOW: no console flashes for child tools
        }
        let mut child = match c.spawn() {
            Ok(ch) => ch,
            Err(e) => {
                let _ = tx.send(Event::Done(id, Status::Failed(format!("{}: {e}", cmd.program))));
                wake();
                return;
            }
        };
        let readers = [pipe(child.stdout.take(), id, &tx, &wake), pipe(child.stderr.take(), id, &tx, &wake)];
        for r in readers.into_iter().flatten() {
            let _ = r.join();
        }
        let status = match child.wait() {
            Ok(s) => Status::Exited(s.code().unwrap_or(-1)),
            Err(e) => Status::Failed(e.to_string()),
        };
        let _ = tx.send(Event::Done(id, status));
        wake();
    });
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
        let mut lines = vec![];
        let status = loop {
            match rx.recv().unwrap() {
                Event::Line(7, l) => lines.push(l),
                Event::Done(7, s) => break s,
                _ => panic!("wrong id"),
            }
        };
        assert_eq!(lines, ["hello"]);
        assert_eq!(status, Status::Exited(3));
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

// ==== stamp v1 | author=kjFriday | hmac-sha256=2134c8a2dd5ccc4be366f3ba9eab8de25d2112eb4772aef4e7ece97b9f9b65a1 ====
