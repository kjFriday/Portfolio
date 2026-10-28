// ==== Generic Company Inc. portfolio ====================================
// Project: portfolio | File: dev_console/src/production.rs
// About: Checks for the live-production view: ask a running site what it answers (through...
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
// ========================================================================

//! Checks for the live-production view: ask a running site what it answers (through curl.exe, which
//! also speaks HTTPS), then judge the answers: each status, the security headers, and no local paths.

use std::net::{TcpStream, ToSocketAddrs};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

/// Headers every page of a public site should send.
pub const HEADERS: [&str; 4] = ["Content-Security-Policy", "X-Frame-Options", "X-Content-Type-Options", "Referrer-Policy"];

const METHODS: [&str; 7] = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"];

/// One line of production_checks: send `method` to `path`, expect `want`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Check {
    pub method: String,
    pub path: String,
    pub want: u16,
}

impl Check {
    pub fn label(&self) -> String {
        format!("{} {}", self.method, self.path)
    }
}

/// `GET / 200, POST /about 405` -> the checks; Err names the first entry that is not METHOD /path STATUS.
/// An empty text means `GET / 200`.
pub fn parse_checks(text: &str) -> Result<Vec<Check>, String> {
    let mut out = vec![];
    for item in text.split(',').map(str::trim).filter(|i| !i.is_empty()) {
        let words: Vec<&str> = item.split_whitespace().collect();
        let [method, path, status] = words.as_slice() else {
            return Err(format!("'{item}': write METHOD /path STATUS"));
        };
        let method = method.to_uppercase();
        if !METHODS.contains(&method.as_str()) {
            return Err(format!("'{item}': unknown method {method}"));
        }
        if !path.starts_with('/') {
            return Err(format!("'{item}': the path must start with /"));
        }
        let Some(want) = status.parse::<u16>().ok().filter(|c| (100..600).contains(c)) else {
            return Err(format!("'{item}': {status} is not an HTTP status"));
        };
        out.push(Check { method, path: path.to_string(), want });
    }
    if out.is_empty() {
        out.push(Check { method: "GET".into(), path: "/".into(), want: 200 });
    }
    Ok(out)
}

/// One HTTP answer.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Response {
    pub status: u16,
    pub headers: Vec<(String, String)>,
    pub body: String,
}

impl Response {
    pub fn header(&self, name: &str) -> Option<&str> {
        self.headers.iter().find(|(k, _)| k.eq_ignore_ascii_case(name)).map(|(_, v)| v.as_str())
    }
}

/// What `curl -D -` prints: header blocks (an interim 1xx block first, if any), a blank line, the body.
pub fn parse_response(raw: &str) -> Option<Response> {
    let mut rest = raw;
    loop {
        let (head, body) = match rest.find("\r\n\r\n") {
            Some(i) => (&rest[..i], &rest[i + 4..]),
            None => match rest.find("\n\n") {
                Some(i) => (&rest[..i], &rest[i + 2..]),
                None => (rest.trim_end(), ""),
            },
        };
        let mut lines = head.lines();
        let status: u16 = lines.next()?.split_whitespace().nth(1)?.parse().ok()?;
        if (100..200).contains(&status) && !body.is_empty() {
            rest = body;
            continue;
        }
        let headers = lines.filter_map(|l| l.split_once(':')).map(|(k, v)| (k.trim().to_string(), v.trim().to_string())).collect();
        return Some(Response { status, headers, body: body.to_string() });
    }
}

/// Send `method` to `base` + `path` with curl.exe -> the answer and how long it took (ms).
pub fn probe(base: &str, method: &str, path: &str, timeout: Duration) -> Result<(Response, u128), String> {
    let url = format!("{}{path}", base.trim_end_matches('/'));
    let mut c = Command::new("curl.exe");
    c.args(["-s", "-S", "-D", "-", "-m", &timeout.as_secs().max(1).to_string()]);
    match method {
        "HEAD" => {
            c.arg("-I");
        }
        "GET" => {}
        _ => {
            c.args(["-X", method, "-d", ""]);
        }
    }
    c.arg(&url).stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        c.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    let started = Instant::now();
    let out = c.output().map_err(|e| format!("curl.exe: {e}"))?;
    let ms = started.elapsed().as_millis();
    if !out.status.success() {
        let why = String::from_utf8_lossy(&out.stderr).trim().to_string();
        return Err(if why.is_empty() { format!("curl exited with code {}", out.status.code().unwrap_or(-1)) } else { why });
    }
    parse_response(&String::from_utf8_lossy(&out.stdout)).map(|r| (r, ms)).ok_or_else(|| "no HTTP answer".to_string())
}

/// One row of the checks grid.
#[derive(Clone, Debug, PartialEq)]
pub struct Outcome {
    pub label: String,
    pub ok: bool,
    pub detail: String,
    pub ms: Option<u128>,
}

/// Run every check against `base`, then judge the answers.
pub fn run(base: &str, checks: &[Check], leaks: &[String], timeout: Duration) -> Vec<Outcome> {
    let answers: Vec<(Check, Result<(Response, u128), String>)> =
        checks.iter().map(|c| (c.clone(), probe(base, &c.method, &c.path, timeout))).collect();
    judge(&answers, leaks)
}

/// A row per check (its status against the one wanted), then "Security headers" (every header in
/// HEADERS on every 200 answer) and "No local paths" (no answer's body holds any of `leaks`).
pub fn judge(answers: &[(Check, Result<(Response, u128), String>)], leaks: &[String]) -> Vec<Outcome> {
    let mut out = vec![];
    let mut answered = vec![];
    for (c, a) in answers {
        match a {
            Ok((r, ms)) => {
                let ok = r.status == c.want;
                let detail = if ok { r.status.to_string() } else { format!("{} (want {})", r.status, c.want) };
                out.push(Outcome { label: c.label(), ok, detail, ms: Some(*ms) });
                answered.push((c, r));
            }
            Err(e) => out.push(Outcome { label: c.label(), ok: false, detail: e.clone(), ms: None }),
        }
    }
    let pages: Vec<&(&Check, &Response)> = answered.iter().filter(|(_, r)| r.status == 200).collect();
    if !pages.is_empty() {
        let mut missing = vec![];
        for (c, r) in &pages {
            for h in HEADERS {
                if r.header(h).is_none() {
                    missing.push(format!("{h} on {}", c.path));
                }
            }
        }
        let detail = if missing.is_empty() { format!("all {} on {} page(s)", HEADERS.len(), pages.len()) } else { format!("missing {}", missing.join(", ")) };
        out.push(Outcome { label: "Security headers".into(), ok: missing.is_empty(), detail, ms: None });
    }
    if !answered.is_empty() {
        let mut found = vec![];
        for (c, r) in &answered {
            let body = r.body.to_lowercase();
            for l in leaks.iter().filter(|l| !l.is_empty()) {
                if body.contains(&l.to_lowercase()) {
                    found.push(format!("{l} in {}", c.path));
                }
            }
        }
        let detail = if found.is_empty() { format!("{} answer(s) read", answered.len()) } else { found.join(", ") };
        out.push(Outcome { label: "No local paths".into(), ok: found.is_empty(), detail, ms: None });
    }
    out
}

/// The text a public page must not hold: each folder as written in plain text, in JSON and with `/`.
pub fn leak_patterns(folders: &[PathBuf]) -> Vec<String> {
    let mut out = vec![];
    for f in folders {
        let s = f.display().to_string().trim_end_matches(['\\', '/']).to_string();
        if s.len() < 4 {
            continue; // a bare drive such as C: would match too much
        }
        out.extend([s.replace('\\', "\\\\"), s.replace('\\', "/"), s]);
    }
    out.sort();
    out.dedup();
    out
}

/// `http://127.0.0.1:8722/x` -> `127.0.0.1:8722`; the scheme's own port when none is written.
pub fn host_port(url: &str) -> Option<String> {
    let (scheme, rest) = url.trim().split_once("://")?;
    let host = rest.split(['/', '?', '#']).next()?;
    if host.is_empty() {
        return None;
    }
    if host.rsplit_once(':').is_some_and(|(_, p)| p.parse::<u16>().is_ok()) {
        return Some(host.to_string());
    }
    let port = match scheme.to_lowercase().as_str() {
        "http" => 80,
        "https" => 443,
        _ => return None,
    };
    Some(format!("{host}:{port}"))
}

/// Whether something accepts connections on `addr` now.
pub fn answers(addr: &str, timeout: Duration) -> bool {
    addr.to_socket_addrs().map(|mut a| a.any(|sa| TcpStream::connect_timeout(&sa, timeout).is_ok())).unwrap_or(false)
}

/// Wait until `addr` accepts connections (true), the time is up, or `alive` turns false (the server ended).
pub fn wait_for(addr: &str, limit: Duration, alive: &AtomicBool) -> bool {
    let started = Instant::now();
    while started.elapsed() < limit && alive.load(Ordering::Relaxed) {
        if answers(addr, Duration::from_millis(300)) {
            return true;
        }
        std::thread::sleep(Duration::from_millis(400));
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::net::TcpListener;

    fn answer(status: u16, headers: &[(&str, &str)], body: &str) -> Response {
        Response { status, headers: headers.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect(), body: body.into() }
    }

    fn secure() -> Vec<(&'static str, &'static str)> {
        HEADERS.iter().map(|h| (*h, "x")).collect()
    }

    #[test]
    fn checks_parse_and_refuse() {
        let c = parse_checks("GET / 200, post /about 405,, GET /api/health 404").unwrap();
        assert_eq!(c.len(), 3);
        assert_eq!(c[1], Check { method: "POST".into(), path: "/about".into(), want: 405 });
        assert_eq!(parse_checks("").unwrap(), [Check { method: "GET".into(), path: "/".into(), want: 200 }]);
        for bad in ["GET / abc", "FETCH / 200", "GET about 200", "GET /", "GET / 999"] {
            assert!(parse_checks(bad).is_err(), "{bad}");
        }
    }

    #[test]
    fn responses_parse() {
        let r = parse_response("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nX-Frame-Options: DENY\r\n\r\n<p>hi</p>").unwrap();
        assert_eq!(r.status, 200);
        assert_eq!(r.header("x-frame-options"), Some("DENY"));
        assert_eq!(r.body, "<p>hi</p>");
        let r = parse_response("HTTP/1.1 100 Continue\r\n\r\nHTTP/1.1 405 Method Not Allowed\r\nAllow: GET\r\n\r\nno").unwrap();
        assert_eq!((r.status, r.header("Allow"), r.body.as_str()), (405, Some("GET"), "no"));
        assert_eq!(parse_response("HTTP/2 204\r\n\r\n").unwrap().status, 204);
        assert!(parse_response("garbage").is_none());
    }

    #[test]
    fn judge_names_what_is_wrong() {
        let check = |m: &str, p: &str, w: u16| Check { method: m.into(), path: p.into(), want: w };
        let leaks = leak_patterns(&[PathBuf::from(r"C:\Users\someone")]);
        let answers = vec![
            (check("GET", "/", 200), Ok((answer(200, &secure(), "fine"), 5))),
            (check("GET", "/about", 200), Ok((answer(200, &[("X-Frame-Options", "DENY")], r#"{"db":"C:\\Users\\someone\\x.db"}"#), 3))),
            (check("GET", "/api/health", 404), Ok((answer(200, &secure(), ""), 2))),
            (check("POST", "/about", 405), Err("connection refused".into())),
        ];
        let out = judge(&answers, &leaks);
        let row = |l: &str| out.iter().find(|o| o.label == l).unwrap().clone();
        assert!(row("GET /").ok);
        assert_eq!(row("GET /api/health").detail, "200 (want 404)");
        assert_eq!(row("POST /about").detail, "connection refused");
        let h = row("Security headers");
        assert!(!h.ok && h.detail.contains("Content-Security-Policy on /about") && !h.detail.contains("X-Frame-Options"), "{}", h.detail);
        let l = row("No local paths");
        assert!(!l.ok && l.detail.contains("/about"), "{}", l.detail);
    }

    #[test]
    fn leak_patterns_cover_json_and_slashes() {
        let p = leak_patterns(&[PathBuf::from(r"D:\Portfolio\"), PathBuf::from("C:")]);
        assert_eq!(p, [r"D:/Portfolio", r"D:\Portfolio", r"D:\\Portfolio"]);
    }

    #[test]
    fn host_port_fills_in_the_port() {
        assert_eq!(host_port("http://127.0.0.1:8722/x").as_deref(), Some("127.0.0.1:8722"));
        assert_eq!(host_port("https://journal.example.com").as_deref(), Some("journal.example.com:443"));
        assert_eq!(host_port("http://localhost").as_deref(), Some("localhost:80"));
        assert_eq!(host_port("http://[::1]:9000/").as_deref(), Some("[::1]:9000"));
        assert_eq!(host_port("ftp://x"), None);
        assert_eq!(host_port("127.0.0.1:80"), None);
    }

    /// A one-shot server answering each request with `reply`; -> its base URL.
    fn serve(reply: &'static str, requests: usize) -> String {
        let l = TcpListener::bind("127.0.0.1:0").unwrap();
        let base = format!("http://{}", l.local_addr().unwrap());
        std::thread::spawn(move || {
            for s in l.incoming().take(requests) {
                let mut s = s.unwrap();
                let mut got = vec![];
                let mut buf = [0u8; 1024];
                while !got.windows(4).any(|w| w == b"\r\n\r\n") {
                    match s.read(&mut buf) {
                        Ok(0) | Err(_) => break,
                        Ok(n) => got.extend_from_slice(&buf[..n]),
                    }
                }
                let _ = s.write_all(reply.as_bytes());
            }
        });
        base
    }

    fn curl_missing() -> bool {
        Command::new("curl.exe").arg("--version").stdout(Stdio::null()).status().is_err()
    }

    #[test]
    fn probe_reads_a_real_answer() {
        if curl_missing() {
            return;
        }
        let base = serve("HTTP/1.1 405 Method Not Allowed\r\nAllow: GET\r\nContent-Length: 2\r\nConnection: close\r\n\r\nno", 1);
        let (r, _) = probe(&base, "POST", "/about", Duration::from_secs(5)).unwrap();
        assert_eq!((r.status, r.header("allow"), r.body.as_str()), (405, Some("GET"), "no"));
    }

    #[test]
    fn probe_reports_no_server() {
        if curl_missing() {
            return;
        }
        let port = TcpListener::bind("127.0.0.1:0").unwrap().local_addr().unwrap().port(); // freed again at once
        assert!(probe(&format!("http://127.0.0.1:{port}"), "GET", "/", Duration::from_secs(2)).is_err());
        assert!(!answers(&format!("127.0.0.1:{port}"), Duration::from_millis(300)));
    }

    /// The Journal's own production command, checked end to end, then stopped. Needs Go; slow.
    #[test]
    #[ignore]
    fn journal_passes_its_production_checks() {
        use crate::jobs::{self, Event, Status};
        let root = crate::registry::find_root(std::path::Path::new(env!("CARGO_MANIFEST_DIR"))).unwrap();
        let (programs, _) = crate::registry::load(&crate::config::parse(include_str!("../config/programs.ini")));
        let j = programs.iter().find(|p| p.name == "Journal").unwrap();
        let port = TcpListener::bind("127.0.0.1:0").unwrap().local_addr().unwrap().port();
        let addr = format!("127.0.0.1:{port}");
        let words: Vec<String> =
            crate::registry::split_args(&j.production).into_iter().map(|w| if w.starts_with("127.0.0.1:") { addr.clone() } else { w }).collect();
        assert!(words.contains(&addr), "{words:?}");
        let (tx, rx) = std::sync::mpsc::channel();
        jobs::spawn(0, crate::registry::Cmd::new(words, root.join(&j.dir)).unwrap(), tx, || {});
        let pid = loop {
            match rx.recv().unwrap() {
                Event::Started(0, pid) => break pid,
                Event::Done(0, s) => panic!("ended early: {s:?}"),
                _ => {}
            }
        };
        assert!(wait_for(&addr, Duration::from_secs(180), &AtomicBool::new(true)), "the Journal never answered on {addr}");
        let leaks = leak_patterns(&[std::env::var_os("USERPROFILE").map(PathBuf::from).unwrap(), root.clone()]);
        let out = run(&format!("http://{addr}"), &parse_checks(&j.production_checks).unwrap(), &leaks, Duration::from_secs(10));
        jobs::stop(pid).unwrap();
        let done = loop {
            if let Event::Done(0, s) = rx.recv_timeout(Duration::from_secs(20)).expect("the job did not end after stop") {
                break s;
            }
        };
        assert_ne!(done, Status::Running);
        assert!(!answers(&addr, Duration::from_millis(500)), "something still answers on {addr} after stop");
        let failed: Vec<&Outcome> = out.iter().filter(|o| !o.ok).collect();
        assert!(failed.is_empty(), "{failed:#?}");
        assert!(out.len() >= 7, "{out:#?}");
    }
}

// ==== stamp v1 | author=kjFriday | hmac-sha256=984454a32948ca0d58e07d8abe72b942207eec1e5e2aeaaa07869f3137e7708c ====
