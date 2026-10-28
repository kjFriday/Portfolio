# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: stamp.py
# About: Add a license header and a keyed stamp footer to every tracked source file (standard...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

# ==== Generic Company Inc. portfolio ===============================================
# Project: portfolio | File: stamp.py
# About: Add a license header and a keyed stamp footer to every tracked source file (standard...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""Add a license header and a keyed stamp footer to every tracked source file (standard library only).

    python stamp.py --init-key     # once: create the private key outside the repo (back it up)
    python stamp.py                # stamp every source file that has no stamp yet
    python stamp.py --dry-run      # list what would be stamped, write nothing
    python stamp.py --check        # verify every stamp, exit 1 if any is missing or invalid
    python stamp.py --restamp [PATH ...]   # re-stamp after your own edits (all files if no PATH)

Files come from `git ls-files` in this repo and in each submodule listed in .gitmodules. The header
names the project and file, says what the file does (first sentence of its own doc comment) and
carries the AGPL-3.0 notice. The footer is an HMAC-SHA256, under a key only the author holds, of the
author's name, the file's path and the whole file apart from the footer. Anyone may still change a
file (the code is AGPL-3.0); --check shows which files no longer match what the author stamped.
"""

import argparse
import ast
import codecs
import datetime
import hashlib
import hmac
import os
import re
import secrets
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
AUTHOR = "kjFriday"
SPDX = "AGPL-3.0-only"
KEY_ENV = "PORTFOLIO_STAMP_KEY"
KEY_FILE = os.path.join(os.path.expanduser("~"), ".portfolio_stamp_key")
TOP_PROJECT = "portfolio"
EXCLUDED_DIRS = {"reference", "testdata", "_extracted", ".claude"}
WIDTH = 72
ABOUT_MAX = 90
VERSION = "v1"


class Style:
    """How one language writes comments: header lines, and the markers used to read its doc comment."""

    def __init__(self, language, open_, close, line_markers, blocks):
        self.language, self.open, self.close = language, open_, close
        self.line_markers, self.blocks = line_markers, blocks

    def wrap(self, text):
        return self.open + text + self.close


STYLES = {
    ".py": Style("Python", "# ", "", ("#",), {}),
    ".ps1": Style("PowerShell", "# ", "", ("#",), {"<#": "#>"}),
    ".go": Style("Go", "// ", "", ("//",), {"/*": "*/"}),
    ".rs": Style("Rust", "// ", "", ("///", "//!", "//"), {"/*": "*/"}),
    ".js": Style("JavaScript", "// ", "", ("//",), {"/*": "*/"}),
    ".css": Style("CSS", "/* ", " */", (), {"/*": "*/"}),
    ".html": Style("HTML", "<!-- ", " -->", (), {"<!--": "-->"}),
    ".sql": Style("SQL", "-- ", "", ("--",), {"/*": "*/"}),
}

TITLE = "==== Generic Company Inc. portfolio "
TITLE = TITLE + "=" * (WIDTH - len(TITLE))
RULE = "=" * WIDTH
FOOTER_RE = re.compile(r"==== stamp (v\d+) \| author=([^\s|]+) \| hmac-sha256=([0-9a-f]{64}) ====")
YEAR_RE = re.compile(r"Copyright \(c\) (\d{4}(?:-\d{4})?) ")
COOKIE_RE = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*[-\w.]+")
DIRECTIVE_RE = re.compile(r"^(go:|\+build|requires\b|-\*-|eslint|noqa|type:|pylint|!)", re.I)
TITLE_TAG_RE = re.compile(r"<title>(.*?)</title>", re.I | re.S)
GENERATED_RE = re.compile(r"generated\b.{0,80}\bdo not edit", re.I | re.S)
PACKAGE_RE = re.compile(r"^package (\w+)", re.M)
ABBREVIATIONS = {"Inc.", "Ltd.", "Co.", "e.g.", "i.e.", "etc.", "vs.", "cf."}


# --- reading a file ----------------------------------------------------------------------------

def prelude_count(lines, ext):
    """Lines that must stay first: shebang, Python coding cookie, HTML doctype, CSS @charset."""
    n = 0
    if lines and lines[0].startswith("#!") and ext != ".rs":
        n = 1
    if ext == ".py" and n < len(lines) and COOKIE_RE.match(lines[n]):
        n += 1
    if ext == ".html" and lines and lines[0].lstrip().lower().startswith("<!doctype"):
        n = 1
    if ext == ".css" and lines and lines[0].startswith("@charset"):
        n = 1
    return n


def strip_footer(text, ext):
    """(core, footer line or None). A stamped file is `core + "\\n" + footer + "\\n"`.

    The core is everything the MAC covers: prelude + header + one blank line + body, LF endings.
    """
    if text:
        stripped = text[:-1] if text.endswith("\n") else text
        cut = stripped.rfind("\n") + 1
        last = stripped[cut:]
        if last.startswith(STYLES[ext].open) and FOOTER_RE.search(last):
            core = stripped[:cut]
            return (core[:-1] if core.endswith("\n\n") else core), last
    return text, None


def split(text, ext):
    """Split LF text into (prelude, header, body, footer); header and footer are None if absent."""
    style = STYLES[ext]
    core, footer = strip_footer(text, ext)
    lines = core[:-1].split("\n") if core.endswith("\n") else (core.split("\n") if core else [])
    n = prelude_count(lines, ext)
    header = None
    if n < len(lines) and lines[n] == style.wrap(TITLE):
        for end in range(n + 1, min(len(lines), n + 20)):
            if lines[end] == style.wrap(RULE):
                header = lines[n:end + 1]
                break
    rest = n + len(header) if header else n
    if header and rest < len(lines) and lines[rest] == "":
        rest += 1
    return lines[:n], header, lines[rest:], footer


def join(lines):
    return "\n".join(lines) + "\n" if lines else ""


def sentence(text, style):
    """First sentence of `text`, one line, safe inside the style's comment."""
    text = " ".join(text.split())
    for m in re.finditer(r"(\S*[.!?])\s", text):
        if m.group(1) not in ABBREVIATIONS:
            text = text[:m.end(1)]
            break
    if style.close:
        text = text.replace(style.close.strip(), "")
    if style.language == "HTML":
        text = text.replace("--", "-")
    if style.language == "SQL":
        text = text.replace(";", ",")
    if len(text) > ABOUT_MAX:
        text = text[:ABOUT_MAX].rsplit(" ", 1)[0].rstrip(",.;:") + "..."
    return text


def about(body, ext):
    """What the file does, from its own docstring or leading comment, or None."""
    style = STYLES[ext]
    if ext == ".py":
        try:
            doc = ast.get_docstring(ast.parse(join(body)))
        except (SyntaxError, ValueError):
            doc = None
        if doc:
            return sentence(doc, style)
    if ext == ".html":
        m = TITLE_TAG_RE.search(join(body))
        if m and m.group(1).strip():
            return sentence(m.group(1), style)
    words, close = [], None
    for line in body:
        s = line.strip()
        if close is None:
            opener = next((o for o in style.blocks if s.startswith(o)), None)
            marker = next((m for m in style.line_markers if s.startswith(m)), None)
            if opener:
                close, s = style.blocks[opener], s[len(opener):]
            elif marker:
                s = s[len(marker):]
            elif not words and (not s or (ext == ".rs" and s.startswith("#"))):
                continue  # blank lines and Rust attributes before the doc comment
            else:
                break
        ended = False
        if close is not None:
            if close in s:
                s, ended = s[:s.index(close)], True
            s = s.lstrip("*")
        if ended:
            close = None
        s = s.strip()
        if not s:
            if words:
                break
            continue
        if DIRECTIVE_RE.match(s) or (ext == ".ps1" and s.startswith(".")):
            continue
        words.append(s)
    return sentence(" ".join(words), style) if words else None


def fallback(body, ext, project, inner):
    """A plain description for a file with no doc comment of its own."""
    name = inner.rsplit("/", 1)[-1]
    pkg = PACKAGE_RE.search(join(body)) if ext == ".go" else None
    if name.endswith("_test.go"):
        return "Tests for package %s." % (pkg.group(1) if pkg else name[:-8])
    if ext == ".py" and name.startswith("test_"):
        return "Tests for %s." % name[5:]
    if pkg:
        return "Part of package %s in %s." % (pkg.group(1), project)
    if ext == ".rs" and name == "mod.rs":
        return "Module list for %s." % inner.rsplit("/", 2)[-2]
    if ext == ".py" and name == "__init__.py":
        return "Package marker for %s." % inner.rsplit("/", 2)[-2]
    return "%s source for %s." % (STYLES[ext].language, project)


# --- writing a stamp ---------------------------------------------------------------------------

def header_lines(ext, project, inner, summary, year, provenance):
    style = STYLES[ext]
    text = [
        TITLE,
        "Project: %s | File: %s" % (project, inner),
        "About: %s" % summary,
        "Copyright (c) %s %s | SPDX-License-Identifier: %s" % (year, AUTHOR, SPDX),
        "You may change this file under the AGPL-3.0. The stamp at the end marks",
        "the version %s wrote. Verify with the portfolio's stamp.py --check." % AUTHOR,
    ]
    if provenance:
        text.append("Reused code, if any, is mapped in PROVENANCE.md.")
    text.append(RULE)
    return [style.wrap(t) for t in text]


def mac(key, relkey, core):
    msg = b"\0".join([VERSION.encode(), AUTHOR.encode(), relkey.encode("utf-8"), core.encode("utf-8")])
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def stamp_text(text, ext, relkey, project, inner, key, year=None, provenance=False):
    """Return LF `text` with a fresh header and footer (any old ones are replaced)."""
    prelude, header, body, _ = split(text, ext)
    old_year = YEAR_RE.search("\n".join(header)) if header else None
    year = old_year.group(1) if old_year else (year or str(datetime.date.today().year))
    summary = about(body, ext) or fallback(body, ext, project, inner)
    head = header_lines(ext, project, inner, summary, year, provenance)
    core = join(prelude + head + ([""] + body if body else []))
    footer = STYLES[ext].wrap("==== stamp %s | author=%s | hmac-sha256=%s ====" % (VERSION, AUTHOR, mac(key, relkey, core)))
    return core + "\n" + footer + "\n"


def check_text(text, ext, relkey, key):
    """'ok', 'missing' (no footer) or 'INVALID' (footer does not match this file)."""
    core, footer = strip_footer(text, ext)
    if footer is None:
        return "missing"
    version, author, digest = FOOTER_RE.search(footer).groups()
    if version != VERSION or author != AUTHOR:
        return "INVALID"
    return "ok" if hmac.compare_digest(digest, mac(key, relkey, core)) else "INVALID"


def decode(raw):
    """(LF text, had BOM, used CRLF) or None if the file is not UTF-8."""
    bom = raw.startswith(codecs.BOM_UTF8)
    try:
        text = raw[len(codecs.BOM_UTF8) if bom else 0:].decode("utf-8")
    except UnicodeDecodeError:
        return None
    crlf = text.count("\r\n") * 2 > text.count("\n")
    return text.replace("\r\n", "\n"), bom, crlf


def encode(text, bom, crlf):
    if crlf:
        text = text.replace("\n", "\r\n")
    return (codecs.BOM_UTF8 if bom else b"") + text.encode("utf-8")


def generated(text):
    """True for files a tool writes ("Code generated ... DO NOT EDIT", "generated by x, do not edit")."""
    return bool(GENERATED_RE.search(text[:600]))


# --- the repository ----------------------------------------------------------------------------

def git_files(path):
    out = subprocess.run(["git", "-C", path, "ls-files", "-z"], capture_output=True, check=True).stdout
    return [f for f in out.decode("utf-8").split("\0") if f]


def submodules(root):
    if not os.path.isfile(os.path.join(root, ".gitmodules")):
        return []
    out = subprocess.run(["git", "-C", root, "config", "-f", ".gitmodules", "--get-regexp", r"\.path$"],
                         capture_output=True, text=True).stdout
    return [line.split(" ", 1)[1].strip() for line in out.splitlines() if " " in line]


def in_scope(rel):
    parts = rel.split("/")
    return os.path.splitext(rel)[1].lower() in STYLES and not EXCLUDED_DIRS.intersection(parts[:-1])


def source_files(root):
    """(relkey, project, path inside project) for every tracked source file, sorted."""
    found = [(rel, TOP_PROJECT, rel) for rel in git_files(root)]
    for sub in submodules(root):
        if os.path.isdir(os.path.join(root, sub)):
            found += [("%s/%s" % (sub, rel), sub, rel) for rel in git_files(os.path.join(root, sub))]
    return sorted(f for f in found if in_scope(f[2]) and os.path.isfile(os.path.join(root, f[0])))


def load_key():
    value = os.environ.get(KEY_ENV)
    if not value and os.path.isfile(KEY_FILE):
        with open(KEY_FILE, encoding="ascii") as f:
            value = f.read()
    value = (value or "").strip()
    if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        sys.exit("no stamp key: run `python stamp.py --init-key` (or set %s to 64 hex chars)" % KEY_ENV)
    return bytes.fromhex(value)


def init_key(root):
    path, root = os.path.abspath(KEY_FILE), os.path.abspath(root)
    same_drive = os.path.splitdrive(path)[0].lower() == os.path.splitdrive(root)[0].lower()
    if same_drive and os.path.commonpath([path, root]) == root:
        sys.exit("refusing to write the key inside the repository")
    if os.path.exists(path):
        sys.exit("a key already exists at %s; not overwriting it" % path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write(secrets.token_hex(32) + "\n")
    print("key written to %s. Back it up: without it no stamp can be checked." % path)


def run(root, mode, only=None):
    """Stamp, re-stamp or check every source file; returns the process exit code."""
    key = load_key()
    counts, problems = {}, []
    only = {p.replace("\\", "/").strip("/") for p in only} if only else None
    for relkey, project, inner in source_files(root):
        if only is not None and relkey not in only:
            continue
        path = os.path.join(root, relkey)
        with open(path, "rb") as f:
            raw = f.read()
        decoded = decode(raw)
        if decoded is None:
            counts["skipped"] = counts.get("skipped", 0) + 1
            problems.append("skipped (not UTF-8)  %s" % relkey)
            continue
        text, bom, crlf = decoded
        ext = os.path.splitext(relkey)[1].lower()
        if generated(text):
            counts["generated"] = counts.get("generated", 0) + 1
            continue
        status = check_text(text, ext, relkey, key)
        if mode == "check" or (mode in ("stamp", "dry-run") and status != "missing"):
            counts[status] = counts.get(status, 0) + 1
            if status != "ok":
                problems.append("%-8s %s" % (status, relkey))
            continue
        provenance = os.path.isfile(os.path.join(root, project if project != TOP_PROJECT else "", "PROVENANCE.md"))
        new = stamp_text(text, ext, relkey, project, inner, key, provenance=provenance)
        if mode != "dry-run":
            with open(path, "wb") as f:
                f.write(encode(new, bom, crlf))
        label = "would stamp" if mode == "dry-run" else "stamped"
        counts[label] = counts.get(label, 0) + 1
        print("%s  %s" % (label, relkey))
    for line in problems:
        print(line)
    print(", ".join("%d %s" % (n, k) for k, n in sorted(counts.items())) or "no source files")
    if mode == "stamp" and counts.get("INVALID"):
        print("INVALID files were left alone; use --restamp PATH for files you changed yourself.")
    return 1 if mode == "check" and (counts.get("INVALID") or counts.get("missing")) else 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Add and check license stamps on tracked source files.")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="verify every stamp")
    g.add_argument("--dry-run", action="store_true", help="list files that would be stamped")
    g.add_argument("--restamp", nargs="*", metavar="PATH", help="re-stamp these files (all if none given)")
    g.add_argument("--init-key", action="store_true", help="create the private key")
    p.add_argument("--root", default=ROOT, help=argparse.SUPPRESS)
    a = p.parse_args(argv)
    if a.init_key:
        init_key(a.root)
        return 0
    if a.restamp is not None:
        return run(a.root, "restamp", a.restamp or None)
    return run(a.root, "check" if a.check else "dry-run" if a.dry_run else "stamp")


if __name__ == "__main__":
    sys.exit(main())

# ==== stamp v1 | author=kjFriday | hmac-sha256=6f6ce1ecf5a17f568da920d72778ae310ad4f7f0d7f254dbc4693c9459fd5480 ====
