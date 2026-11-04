// ==== Generic Company Inc. portfolio ====================================
// Project: dev_console | File: src/production.rs
// About: Checks for the live-production view: ask a running site what it answers (through...
// Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
// You may change this file under the AGPL-3.0. The stamp at the end marks
// the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
// ========================================================================

//! Live-production checks: probe a running site with curl.exe and judge what it answers.
//!
//! Checks for the live-production view: ask a running site what it answers (through curl.exe, which
//! also speaks HTTPS), then judge the answers: each status, the security headers, and no local paths.
//! app.rs runs them on a background thread when the view's Start, Check now or Keep checking asks.
//!
//! Flow of one check:
//! 1. `parse_checks` turns a program's `production_checks` text (`GET / 200, POST /about 405`) into `Check`s.
//! 2. With Start, `host_port` and `wait_for` first wait until the new server accepts TCP connections.
//! 3. `run` sends each check with `probe`: curl.exe prints the raw status line and headers (`-D -`) and
//!    the body, and `parse_response` reads them back into a `Response`.
//! 4. `judge` turns the answers into `Outcome` rows: one per check, then "Security headers" and
//!    "No local paths", built from `leak_patterns`.
//!
//! curl.exe ships with Windows 10 (1803 and later), so no HTTP or TLS library is linked into the console.
//!
//! Defines `Check`, `Response` and `Outcome`. Start reading at `run`.

use std::net::{TcpStream, ToSocketAddrs};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

/// Headers every page of a public site should send.
///
/// - Content-Security-Policy: which sources may supply scripts, styles and frames (stops injected scripts).
/// - X-Frame-Options: whether other sites may show the page in a frame (stops clickjacking).
/// - X-Content-Type-Options: `nosniff` makes the browser trust the declared type, not guess one.
/// - Referrer-Policy: how much of the page address goes to other sites in the Referer header.
///
/// Only their presence is checked, not their values.
pub const HEADERS: [&str; 4] = [
    "Content-Security-Policy",
    "X-Frame-Options",
    "X-Content-Type-Options",
    "Referrer-Policy",
];

/// The HTTP methods a check may use: the common ones from the HTTP semantics standard (RFC 9110 section 9)
/// plus PATCH. CONNECT and TRACE are left out, since they make no sense against a web page.
const METHODS: [&str; 7] = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"];

/// One line of production_checks: send `method` to `path`, expect `want`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Check {
    /// One of METHODS, upper case.
    pub method: String,
    /// The request path, starting with `/`; added to the site's base URL.
    pub path: String,
    /// The HTTP status the answer must have (100 to 599).
    pub want: u16,
}

// How a check is named in the grid.
impl Check {
    /// `GET /about`: the row label in the checks grid.
    pub fn label(&self) -> String {
        format!("{} {}", self.method, self.path)
    }
}

/// `GET / 200, POST /about 405` -> the checks; Err names the first entry that is not METHOD /path STATUS.
/// An empty text means `GET / 200`.
///
/// Entries are separated by commas; empty entries (`,,`) are skipped. Each must be exactly three words. The
/// method is accepted in any case and stored upper case.
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
        out.push(Check {
            method,
            path: path.to_string(),
            want,
        });
    }
    if out.is_empty() {
        out.push(Check {
            method: "GET".into(),
            path: "/".into(),
            want: 200,
        });
    }
    Ok(out)
}

/// One HTTP answer.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Response {
    /// The status code from the final status line (after any 1xx interim answer).
    pub status: u16,
    /// The header fields in the order sent, name and value trimmed; names keep their case.
    pub headers: Vec<(String, String)>,
    /// The body as text (lossily decoded from UTF-8); empty for HEAD.
    pub body: String,
}

// Header lookup.
impl Response {
    /// The value of header `name`, matched without regard to case (HTTP header names are case-insensitive);
    /// the first one when it is sent more than once.
    pub fn header(&self, name: &str) -> Option<&str> {
        self.headers
            .iter()
            .find(|(k, _)| k.eq_ignore_ascii_case(name))
            .map(|(_, v)| v.as_str())
    }
}

/// What `curl -D -` prints: header blocks (an interim 1xx block first, if any), a blank line, the body.
///
/// HTTP/1.1 ends the header block with an empty line (CRLF CRLF); curl prints HTTP/2 answers in the same
/// shape, as `HTTP/2 204` with no reason phrase. A 1xx answer (`100 Continue`) is a preliminary block the
/// server may send before the real one, so it is skipped. None when there is no readable status line.
///
/// Steps:
/// 1. Split at the first blank line (CRLF, or bare LF for lenient servers) into head and body.
/// 2. The status code is the second word of the head's first line.
/// 3. A 1xx head with more text after it: start again on that text.
/// 4. Otherwise every `Name: value` line of the head is a header; the rest is the body.
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
        let headers = lines
            .filter_map(|l| l.split_once(':'))
            .map(|(k, v)| (k.trim().to_string(), v.trim().to_string()))
            .collect();
        return Some(Response {
            status,
            headers,
            body: body.to_string(),
        });
    }
}

/// Send `method` to `base` + `path` with curl.exe -> the answer and how long it took (ms).
///
/// `base` is the site address (`production_url`), a trailing `/` allowed; `timeout` caps the whole request,
/// rounded down to whole seconds and at least 1. Any HTTP status is a success here; judging it is `judge`'s
/// work. Err is curl's own message (refused connection, unknown host, TLS failure, timeout) or
/// "no HTTP answer". The time includes starting curl.exe, so it is an upper bound on the server's time.
pub fn probe(base: &str, method: &str, path: &str, timeout: Duration) -> Result<(Response, u128), String> {
    let url = format!("{}{path}", base.trim_end_matches('/'));
    let mut c = Command::new("curl.exe");
    // curl flags: -s no progress meter, -S but still print errors, -D - write the received headers to
    // stdout before the body, -m the time limit in seconds for the whole transfer
    c.args(["-s", "-S", "-D", "-", "-m", &timeout.as_secs().max(1).to_string()]);
    match method {
        // -I sends HEAD and expects no body; `-X HEAD` would make curl wait for a body that never comes
        "HEAD" => {
            c.arg("-I");
        }
        "GET" => {}
        // -X sets the method; -d "" sends an empty body with Content-Length: 0, which some servers require
        // on POST and PUT (411 Length Required otherwise)
        _ => {
            c.args(["-X", method, "-d", ""]);
        }
    }
    c.arg(&url)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        c.creation_flags(crate::win::CREATE_NO_WINDOW);
    }
    let started = Instant::now();
    let out = c.output().map_err(|e| format!("curl.exe: {e}"))?;
    let ms = started.elapsed().as_millis();
    if !out.status.success() {
        let why = String::from_utf8_lossy(&out.stderr).trim().to_string();
        return Err(if why.is_empty() {
            format!("curl exited with code {}", out.status.code().unwrap_or(-1))
        } else {
            why
        });
    }
    parse_response(&String::from_utf8_lossy(&out.stdout))
        .map(|r| (r, ms))
        .ok_or_else(|| "no HTTP answer".to_string())
}

/// One row of the checks grid.
#[derive(Clone, Debug, PartialEq)]
pub struct Outcome {
    /// What was checked: `GET /about`, "Security headers", "No local paths" or "Server on ADDR".
    pub label: String,
    /// Whether it passed.
    pub ok: bool,
    /// The status got (and the one wanted, on a mismatch), what is missing or leaked, or the error.
    pub detail: String,
    /// Round-trip time in milliseconds, for rows that made a request that got an answer.
    pub ms: Option<u128>,
}

/// Run every check against `base`, then judge the answers.
///
/// Blocking: the checks run one after another, each up to `timeout`, so app.rs calls this on a background
/// thread. `leaks` comes from `leak_patterns`.
pub fn run(base: &str, checks: &[Check], leaks: &[String], timeout: Duration) -> Vec<Outcome> {
    let answers: Vec<(Check, Result<(Response, u128), String>)> = checks
        .iter()
        .map(|c| (c.clone(), probe(base, &c.method, &c.path, timeout)))
        .collect();
    judge(&answers, leaks)
}

/// A row per check (its status against the one wanted), then "Security headers" (every header in
/// HEADERS on every 200 answer) and "No local paths" (no answer's body holds any of `leaks`).
///
/// Kept apart from `run` so tests can judge made-up answers without a server. The two summary rows appear
/// only when there is something to judge: "Security headers" needs at least one 200 answer, "No local
/// paths" at least one answer of any status. The leak match ignores case, since Windows paths do.
///
/// Steps:
/// 1. One row per check: ok when the status equals the wanted one; an error row when curl got no answer.
/// 2. Over the 200 answers (real pages; a redirect or error page need not carry them): list each missing
///    header with its path.
/// 3. Over every answer, error pages included (stack traces leak paths too): list each leak with its path.
pub fn judge(answers: &[(Check, Result<(Response, u128), String>)], leaks: &[String]) -> Vec<Outcome> {
    let mut out = vec![];
    let mut answered = vec![];
    // ---- one row per check ----
    for (c, a) in answers {
        match a {
            Ok((r, ms)) => {
                let ok = r.status == c.want;
                let detail = if ok {
                    r.status.to_string()
                } else {
                    format!("{} (want {})", r.status, c.want)
                };
                out.push(Outcome {
                    label: c.label(),
                    ok,
                    detail,
                    ms: Some(*ms),
                });
                answered.push((c, r));
            }
            Err(e) => out.push(Outcome {
                label: c.label(),
                ok: false,
                detail: e.clone(),
                ms: None,
            }),
        }
    }
    // ---- security headers on the 200 pages ----
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
        let detail = if missing.is_empty() {
            format!("all {} on {} page(s)", HEADERS.len(), pages.len())
        } else {
            format!("missing {}", missing.join(", "))
        };
        out.push(Outcome {
            label: "Security headers".into(),
            ok: missing.is_empty(),
            detail,
            ms: None,
        });
    }
    // ---- no local paths in any answer ----
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
        let detail = if found.is_empty() {
            format!("{} answer(s) read", answered.len())
        } else {
            found.join(", ")
        };
        out.push(Outcome {
            label: "No local paths".into(),
            ok: found.is_empty(),
            detail,
            ms: None,
        });
    }
    out
}

/// The text a public page must not hold: each folder as written in plain text, in JSON and with `/`.
///
/// app.rs passes the user's profile and local app-data folders and the portfolio root. A server that shows
/// one of them (in an error page, a config dump or a JSON field) tells strangers the account name and the
/// folder layout. Returns the patterns sorted with duplicates removed.
pub fn leak_patterns(folders: &[PathBuf]) -> Vec<String> {
    let mut out = vec![];
    for f in folders {
        let s = f.display().to_string().trim_end_matches(['\\', '/']).to_string();
        if s.len() < 4 {
            continue; // a bare drive such as C: would match too much
        }
        // `C:\\Users\\x` is how JSON escapes the path, `C:/Users/x` how many tools print it
        out.extend([s.replace('\\', "\\\\"), s.replace('\\', "/"), s]);
    }
    out.sort();
    out.dedup();
    out
}

/// `http://127.0.0.1:8722/x` -> `127.0.0.1:8722`; the scheme's own port when none is written.
///
/// The result is the TCP address `answers` and `wait_for` connect to. None for a text with no `scheme://`,
/// an empty host, or a scheme other than http and https with no port written.
pub fn host_port(url: &str) -> Option<String> {
    let (scheme, rest) = url.trim().split_once("://")?;
    // the authority part ends at the first path, query or fragment character
    let host = rest.split(['/', '?', '#']).next()?;
    if host.is_empty() {
        return None;
    }
    // rsplit, so the colons inside an IPv6 literal such as `[::1]:9000` are not taken for the port's
    // Known limitation: user info (`user@host`) is not removed
    if host.rsplit_once(':').is_some_and(|(_, p)| p.parse::<u16>().is_ok()) {
        return Some(host.to_string());
    }
    // the default ports of the two schemes (80 for HTTP, 443 for HTTPS)
    let port = match scheme.to_lowercase().as_str() {
        "http" => 80,
        "https" => 443,
        _ => return None,
    };
    Some(format!("{host}:{port}"))
}

/// Whether something accepts connections on `addr` now.
///
/// `addr` is `host:port`; a host name may resolve to several addresses (IPv4 and IPv6), and any one that
/// completes a TCP connect within `timeout` counts. Only the connection is tested, not HTTP; the stream is
/// closed at once. A name that does not resolve counts as no answer. Name lookup is not bounded by `timeout`.
pub fn answers(addr: &str, timeout: Duration) -> bool {
    addr.to_socket_addrs()
        .map(|mut a| a.any(|sa| TcpStream::connect_timeout(&sa, timeout).is_ok()))
        .unwrap_or(false)
}

/// Wait until `addr` accepts connections (true), the time is up, or `alive` turns false (the server ended).
///
/// `alive` is the job's flag, which app.rs clears when the server's job ends, so a server that crashed at
/// start-up ends the wait at once instead of after `limit`. Polls about every 0.7 s: a 300 ms connect
/// attempt, then a 400 ms pause. Relaxed ordering is enough, since the flag guards no other data.
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

/// Unit tests: parsing and judging with made-up answers, then curl.exe against a tiny local server.
#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::net::TcpListener;

    // A made-up Response with these headers and body.
    fn answer(status: u16, headers: &[(&str, &str)], body: &str) -> Response {
        Response {
            status,
            headers: headers.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect(),
            body: body.into(),
        }
    }

    // Every security header, each with a dummy value (only presence is judged).
    fn secure() -> Vec<(&'static str, &'static str)> {
        HEADERS.iter().map(|h| (*h, "x")).collect()
    }

    // A list with a lower-case method and an empty entry parses to three checks; empty text gives GET / 200;
    // a bad status, unknown method, relative path, missing word or out-of-range status is refused.
    #[test]
    fn checks_parse_and_refuse() {
        let c = parse_checks("GET / 200, post /about 405,, GET /api/health 404").unwrap();
        assert_eq!(c.len(), 3);
        assert_eq!(
            c[1],
            Check {
                method: "POST".into(),
                path: "/about".into(),
                want: 405
            }
        );
        assert_eq!(
            parse_checks("").unwrap(),
            [Check {
                method: "GET".into(),
                path: "/".into(),
                want: 200
            }]
        );
        for bad in ["GET / abc", "FETCH / 200", "GET about 200", "GET /", "GET / 999"] {
            assert!(parse_checks(bad).is_err(), "{bad}");
        }
    }

    // A plain answer, one after a 100 Continue block, an HTTP/2 status line with no reason phrase, and garbage.
    #[test]
    fn responses_parse() {
        let r = parse_response("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nX-Frame-Options: DENY\r\n\r\n<p>hi</p>")
            .unwrap();
        assert_eq!(r.status, 200);
        assert_eq!(r.header("x-frame-options"), Some("DENY"));
        assert_eq!(r.body, "<p>hi</p>");
        let r = parse_response("HTTP/1.1 100 Continue\r\n\r\nHTTP/1.1 405 Method Not Allowed\r\nAllow: GET\r\n\r\nno")
            .unwrap();
        assert_eq!((r.status, r.header("Allow"), r.body.as_str()), (405, Some("GET"), "no"));
        assert_eq!(parse_response("HTTP/2 204\r\n\r\n").unwrap().status, 204);
        assert!(parse_response("garbage").is_none());
    }

    // Four answers cover each kind of failure: a wrong status, no answer, a 200 page missing three headers
    // (X-Frame-Options it has must not be named), and a JSON body leaking an escaped user folder.
    #[test]
    fn judge_names_what_is_wrong() {
        let check = |m: &str, p: &str, w: u16| Check {
            method: m.into(),
            path: p.into(),
            want: w,
        };
        let leaks = leak_patterns(&[PathBuf::from(r"C:\Users\someone")]);
        let answers = vec![
            (check("GET", "/", 200), Ok((answer(200, &secure(), "fine"), 5))),
            (
                check("GET", "/about", 200),
                Ok((
                    answer(
                        200,
                        &[("X-Frame-Options", "DENY")],
                        r#"{"db":"C:\\Users\\someone\\x.db"}"#,
                    ),
                    3,
                )),
            ),
            (check("GET", "/api/health", 404), Ok((answer(200, &secure(), ""), 2))),
            (check("POST", "/about", 405), Err("connection refused".into())),
        ];
        let out = judge(&answers, &leaks);
        let row = |l: &str| out.iter().find(|o| o.label == l).unwrap().clone();
        assert!(row("GET /").ok);
        assert_eq!(row("GET /api/health").detail, "200 (want 404)");
        assert_eq!(row("POST /about").detail, "connection refused");
        let h = row("Security headers");
        assert!(
            !h.ok && h.detail.contains("Content-Security-Policy on /about") && !h.detail.contains("X-Frame-Options"),
            "{}",
            h.detail
        );
        let l = row("No local paths");
        assert!(!l.ok && l.detail.contains("/about"), "{}", l.detail);
    }

    // A folder with a trailing backslash gives three spellings, sorted; a bare drive `C:` gives none.
    #[test]
    fn leak_patterns_cover_json_and_slashes() {
        let p = leak_patterns(&[PathBuf::from(r"D:\Portfolio\"), PathBuf::from("C:")]);
        assert_eq!(p, [r"D:/Portfolio", r"D:\Portfolio", r"D:\\Portfolio"]);
    }

    // Written ports are kept (IPv6 too), http and https get 80 and 443, other schemes and a text with no
    // scheme give None.
    #[test]
    fn host_port_fills_in_the_port() {
        assert_eq!(host_port("http://127.0.0.1:8722/x").as_deref(), Some("127.0.0.1:8722"));
        assert_eq!(
            host_port("https://journal.example.com").as_deref(),
            Some("journal.example.com:443")
        );
        assert_eq!(host_port("http://localhost").as_deref(), Some("localhost:80"));
        assert_eq!(host_port("http://[::1]:9000/").as_deref(), Some("[::1]:9000"));
        assert_eq!(host_port("ftp://x"), None);
        assert_eq!(host_port("127.0.0.1:80"), None);
    }

    /// A one-shot server answering each request with `reply`; -> its base URL.
    ///
    /// Port 0 lets the system pick a free port. It serves `requests` connections, reading each request only
    /// up to the blank line that ends its headers (the checks send no body worth reading).
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

    // Whether curl.exe cannot be started; the curl tests pass without checking anything then.
    fn curl_missing() -> bool {
        Command::new("curl.exe")
            .arg("--version")
            .stdout(Stdio::null())
            .status()
            .is_err()
    }

    // A POST through real curl.exe reads back a 405 answer's status, header and body.
    #[test]
    fn probe_reads_a_real_answer() {
        if curl_missing() {
            return;
        }
        let base = serve(
            "HTTP/1.1 405 Method Not Allowed\r\nAllow: GET\r\nContent-Length: 2\r\nConnection: close\r\n\r\nno",
            1,
        );
        let (r, _) = probe(&base, "POST", "/about", Duration::from_secs(5)).unwrap();
        assert_eq!((r.status, r.header("allow"), r.body.as_str()), (405, Some("GET"), "no"));
    }

    // A port that was free a moment ago gives a curl error and no TCP answer.
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
    ///
    /// The command's `127.0.0.1:PORT` word is swapped for a free port, so it cannot clash with a Journal
    /// already running. Run with `cargo test -- --ignored`. At least 7 rows: the Journal's checks plus the two
    /// summary rows.
    #[test]
    #[ignore]
    fn journal_passes_its_production_checks() {
        use crate::jobs::{self, Event, Status};
        let root = crate::registry::find_root(std::path::Path::new(env!("CARGO_MANIFEST_DIR"))).unwrap();
        let (programs, _) = crate::registry::load(&crate::config::parse(include_str!("../config/programs.ini")));
        let j = programs.iter().find(|p| p.name == "Journal").unwrap();
        let port = TcpListener::bind("127.0.0.1:0").unwrap().local_addr().unwrap().port();
        let addr = format!("127.0.0.1:{port}");
        let words: Vec<String> = crate::registry::split_args(&j.production)
            .into_iter()
            .map(|w| if w.starts_with("127.0.0.1:") { addr.clone() } else { w })
            .collect();
        assert!(words.contains(&addr), "{words:?}");
        let (tx, rx) = std::sync::mpsc::channel();
        jobs::spawn(
            0,
            crate::registry::Cmd::new(words, root.join(&j.dir)).unwrap(),
            tx,
            || {},
        );
        let pid = loop {
            match rx.recv().unwrap() {
                Event::Started(0, pid) => break pid,
                Event::Done(0, s) => panic!("ended early: {s:?}"),
                _ => {}
            }
        };
        assert!(
            wait_for(&addr, Duration::from_secs(180), &AtomicBool::new(true)),
            "the Journal never answered on {addr}"
        );
        let leaks = leak_patterns(&[
            std::env::var_os("USERPROFILE").map(PathBuf::from).unwrap(),
            root.clone(),
        ]);
        let out = run(
            &format!("http://{addr}"),
            &parse_checks(&j.production_checks).unwrap(),
            &leaks,
            Duration::from_secs(10),
        );
        jobs::stop(pid).unwrap();
        let done = loop {
            if let Event::Done(0, s) = rx
                .recv_timeout(Duration::from_secs(20))
                .expect("the job did not end after stop")
            {
                break s;
            }
        };
        assert_ne!(done, Status::Running);
        assert!(
            !answers(&addr, Duration::from_millis(500)),
            "something still answers on {addr} after stop"
        );
        let failed: Vec<&Outcome> = out.iter().filter(|o| !o.ok).collect();
        assert!(failed.is_empty(), "{failed:#?}");
        assert!(out.len() >= 7, "{out:#?}");
    }
}

// ==== stamp v1 | author=kjFriday | hmac-sha256=c7c18639057777a41739cdbaf8150b88077ec0a829acb205b6ca0b35596d54af ====
