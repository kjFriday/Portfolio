# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: tools/test_stamp.py
# About: Tests for stamp.py.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Unit tests for stamp.py: headers, footers, About lines, tamper checks, repo scanning.

    python -m unittest discover -s tools      # from the portfolio root

The tests use a fixed, public test key (KEY), never the author's real key, and work on strings or
on throwaway git repositories in a temporary folder, so they never touch the portfolio's files.

Groups:
1. RoundTrip: every comment style stamps, checks "ok" and restamps to the same bytes.
2. Placement: the header goes after lines that must stay first and keeps encodings intact.
3. LegacyHeaders: headers from an older, wider TITLE are replaced, never duplicated.
4. Tamper: any change to body, header, key or path makes the stamp INVALID.
5. Repository: scope rules, generated files and run() against a real temporary git repo.

Start reading at RoundTrip.
"""

import ast
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import stamp as st  # noqa: E402

# two different test keys (bytes 0..31 and 1..32): public values, only for these tests
KEY = bytes(range(32))
OTHER_KEY = bytes(range(1, 33))


def stamped(text, ext, year="2026", provenance=False):
    """Stamp text as file "a<ext>" of project "proj" (path "proj/a<ext>") under KEY."""
    return st.stamp_text(text, ext, "proj/a" + ext, "proj", "a" + ext, KEY, year=year, provenance=provenance)


class RoundTrip(unittest.TestCase):
    """Stamping and checking for every comment style, and how the About line is chosen."""

    # one small file per style, each with a doc comment in that language's usual form
    SAMPLES = {
        ".py": '"""Load the seed rows. More text."""\nimport os\n',
        ".ps1": "# End-to-end check of the programs.\nparam([string]$X)\n",
        ".go": "// Package foo parses things.\npackage foo\n",
        ".rs": "//! The dashboard core.\nfn main() {}\n",
        ".js": "/* Draws the chart. */\nconst a = 1;\n",
        ".css": "/* Page styles. */\nbody { margin: 0 }\n",
        ".html": "<!DOCTYPE html>\n<html><head><title>Generic Company Tickets</title></head></html>\n",
        ".sql": "-- Shared schema; owned by the hub.\nCREATE TABLE t (id INTEGER);\n",
    }

    def test_every_style_checks_ok_and_is_idempotent(self):
        """A fresh stamp checks "ok", and stamping again changes nothing, in every style."""
        for ext, text in self.SAMPLES.items():
            with self.subTest(ext=ext):
                once = stamped(text, ext)
                self.assertEqual(st.check_text(once, ext, "proj/a" + ext, KEY), "ok")
                self.assertEqual(stamped(once, ext), once)

    def test_unstamped_is_missing(self):
        """A file with no footer is "missing", not INVALID."""
        self.assertEqual(st.check_text("x = 1\n", ".py", "proj/a.py", KEY), "missing")

    def test_about_comes_from_the_doc_comment(self):
        """The About line is the first sentence of each style's doc comment (SQL ";" becomes ",")."""
        expect = {
            ".py": "Load the seed rows.", ".ps1": "End-to-end check of the programs.",
            ".go": "Package foo parses things.", ".rs": "The dashboard core.", ".js": "Draws the chart.",
            ".css": "Page styles.", ".html": "Generic Company Tickets", ".sql": "Shared schema, owned by the hub.",
        }
        for ext, text in self.SAMPLES.items():
            with self.subTest(ext=ext):
                self.assertIn(st.STYLES[ext].wrap("About: " + expect[ext]), stamped(text, ext))

    def test_about_falls_back_to_language(self):
        """A file with no doc comment is described by its language and project."""
        self.assertIn("# About: Python source for proj.", stamped("x = 1\n", ".py"))

    def test_about_skips_build_tags_and_rust_attributes(self):
        """A Go build tag and a Rust inner attribute above the doc comment are not the About text."""
        go = "//go:build ignore\n\n// Excerpt kept for reading.\npackage x\n"
        self.assertEqual(st.about(go.splitlines(), ".go"), "Excerpt kept for reading.")
        rs = '#![windows_subsystem = "windows"]\n//! Ticket window.\nfn main() {}\n'
        self.assertEqual(st.about(rs.splitlines(), ".rs"), "Ticket window.")

    def test_about_is_one_safe_line(self):
        """A long comment is cut to ABOUT_MAX plus "...", and comment closers never leak into it."""
        long = "# " + "word " * 40 + "\n"
        self.assertLessEqual(len(st.about(long.splitlines(), ".py")), st.ABOUT_MAX + 3)
        self.assertNotIn("--", st.sentence("a -- b", st.STYLES[".html"]))
        self.assertNotIn("*/", st.sentence("a */ b", st.STYLES[".css"]))

    def test_sentence_does_not_stop_at_abbreviations(self):
        """The "Inc." in the company name does not end the first sentence."""
        self.assertEqual(st.sentence("Where the Generic Company Inc. programs live. More.", st.STYLES[".py"]),
                         "Where the Generic Company Inc. programs live.")

    def test_fallbacks(self):
        """Each fallback rule: Go test, Go package, Python test, Rust mod.rs."""
        self.assertEqual(st.fallback(["package db"], ".go", "cms", "internal/db/db_test.go"), "Tests for package db.")
        self.assertEqual(st.fallback(["package db"], ".go", "cms", "internal/db/x.go"), "Part of package db in cms.")
        self.assertEqual(st.fallback([], ".py", "hub", "test_paths.py"), "Tests for paths.py.")
        self.assertEqual(st.fallback([], ".rs", "dash", "src/core/mod.rs"), "Module list for core.")

    def test_provenance_line(self):
        """The PROVENANCE.md line appears only when asked for."""
        self.assertIn("PROVENANCE.md", stamped("x = 1\n", ".py", provenance=True))
        self.assertNotIn("PROVENANCE.md", stamped("x = 1\n", ".py"))

    def test_empty_file(self):
        """An empty file gets a header and footer that check and restamp cleanly."""
        out = stamped("", ".py")
        self.assertEqual(st.check_text(out, ".py", "proj/a.py", KEY), "ok")
        self.assertEqual(stamped(out, ".py"), out)

    def test_file_without_final_newline(self):
        """A last line without a newline still yields a valid stamp."""
        out = stamped("x = 1", ".py")
        self.assertEqual(st.check_text(out, ".py", "proj/a.py", KEY), "ok")

    def test_existing_year_is_kept(self):
        """A restamp keeps the header's copyright year (2025) instead of the year passed in (2030)."""
        out = stamped("x = 1\n", ".py", year="2025")
        self.assertIn("(c) 2025 ", stamped(out, ".py", year="2030"))


class Placement(unittest.TestCase):
    """Where the header goes, and that the file's encoding details survive."""

    def test_shebang_and_coding_cookie_stay_first(self):
        """Shebang and coding cookie stay on lines 1 and 2, as Python and the OS require."""
        out = stamped("#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\nx = 1\n", ".py")
        lines = out.splitlines()
        self.assertEqual(lines[:2], ["#!/usr/bin/env python3", "# -*- coding: utf-8 -*-"])
        self.assertEqual(lines[2], "# " + st.TITLE)

    def test_python_docstring_is_still_the_docstring(self):
        """The header is comments only, so the module docstring is still the first statement."""
        out = stamped('"""Doc."""\nx = 1\n', ".py")
        self.assertEqual(ast.get_docstring(ast.parse(out)), "Doc.")

    def test_doctype_and_charset_stay_first(self):
        """HTML <!DOCTYPE> and CSS @charset must open the file, so the header follows them."""
        self.assertTrue(stamped("<!DOCTYPE html>\n<p>x</p>\n", ".html").startswith("<!DOCTYPE html>\n<!-- ===="))
        self.assertTrue(stamped('@charset "utf-8";\nb{}\n', ".css").startswith('@charset "utf-8";\n/* ===='))

    def test_go_header_is_separated_from_build_tag_and_package_doc(self):
        """A blank line follows the Go header, so it is never read as the package doc or a build tag."""
        out = stamped("//go:build ignore\n\npackage x\n", ".go").splitlines()
        rule = out.index("// " + st.RULE)
        self.assertEqual(out[rule + 1], "")
        self.assertEqual(out[rule + 2], "//go:build ignore")

    def test_rust_shebang_like_attribute_is_not_prelude(self):
        """In Rust "#![...]" is an inner attribute, so the header still goes on line 1."""
        self.assertTrue(stamped("#![allow(dead_code)]\nfn f() {}\n", ".rs").startswith("// ===="))

    def test_bom_and_crlf_are_kept(self):
        """A BOM and CRLF ends survive stamping, and the stamp checks after decoding again."""
        raw = b"\xef\xbb\xbf# A script.\r\nparam()\r\n"
        text, bom, crlf = st.decode(raw)
        self.assertTrue(bom and crlf)
        out = st.encode(st.stamp_text(text, ".ps1", "p/a.ps1", "p", "a.ps1", KEY), bom, crlf)
        self.assertTrue(out.startswith(b"\xef\xbb\xbf# ===="))
        self.assertNotIn(b"\n", out.replace(b"\r\n", b""))
        again = st.decode(out)[0]
        self.assertEqual(st.check_text(again, ".ps1", "p/a.ps1", KEY), "ok")

    def test_not_utf8(self):
        """A UTF-16 BOM (FF FE) is not UTF-8, so decode refuses it."""
        self.assertIsNone(st.decode(b"\xff\xfe\x00x"))


class LegacyHeaders(unittest.TestCase):
    """Headers written under an older, wider TITLE are found and replaced, never kept in the body."""

    @staticmethod
    def legacy(ext, width=83):
        """A four-line header block of the given width under an old company name."""
        wrap = st.STYLES[ext].wrap
        title = "==== Old Name Inc. portfolio "
        return [wrap(title + "=" * (width - len(title))), wrap("Project: proj | File: a" + ext),
                wrap("About: ==== Old Name Inc. portfolio ===="), wrap("=" * width)]

    def test_a_stale_block_after_the_header_is_dropped(self):
        """A legacy block wedged after today's header is removed, giving back the clean stamp."""
        for ext, doc in ((".py", '"""Load the rows."""\nx = 1\n'), (".go", "// Package foo parses.\npackage foo\n"),
                         (".html", "<html><head><title>Tickets</title></head></html>\n")):
            with self.subTest(ext=ext):
                once = stamped(doc, ext)
                rule = once.split("\n").index(st.STYLES[ext].wrap(st.RULE))
                lines = once.split("\n")
                damaged = "\n".join(lines[:rule + 2] + self.legacy(ext) + [""] + lines[rule + 2:])
                healed = stamped(damaged, ext)
                self.assertEqual(healed, once)
                self.assertEqual(st.check_text(healed, ext, "proj/a" + ext, KEY), "ok")

    def test_two_stale_blocks_are_both_dropped(self):
        """Stale blocks of two different widths (83 and 88) are all removed."""
        once = stamped("// Package foo parses.\npackage foo\n", ".go")
        lines = once.split("\n")
        rule = lines.index("// " + st.RULE)
        damaged = "\n".join(lines[:rule + 2] + self.legacy(".go", 83) + [""] + self.legacy(".go", 88) + [""] + lines[rule + 2:])
        self.assertEqual(stamped(damaged, ".go"), once)

    def test_a_file_with_only_a_legacy_header_gets_one_header(self):
        """A legacy header alone is replaced by exactly one current header."""
        text = "\n".join(self.legacy(".py") + ["", '"""Doc."""', "x = 1", ""])
        out = stamped(text, ".py")
        self.assertEqual(out.count("portfolio ="), 1)
        self.assertIn("# About: Doc.", out)
        self.assertEqual(stamped(out, ".py"), out)

    def test_a_body_comment_that_only_looks_like_a_rule_is_kept(self):
        """A row of "=" in the body is not a header (no title line), so it stays."""
        out = stamped("x = 1\n# " + "=" * 30 + "\n", ".py")
        self.assertIn("# " + "=" * 30 + "\n", out)


class Tamper(unittest.TestCase):
    """Every kind of change to a stamped file is caught by check_text."""

    def setUp(self):
        """Stamp a two-line function as proj/a.py."""
        self.out = stamped("def f():\n    return 1\n", ".py")

    def test_body_change(self):
        """Changing one character of code makes the stamp INVALID."""
        self.assertEqual(st.check_text(self.out.replace("return 1", "return 2"), ".py", "proj/a.py", KEY), "INVALID")

    def test_header_change(self):
        """Changing the author named in the header makes the stamp INVALID."""
        self.assertEqual(st.check_text(self.out.replace("kjFriday |", "someone |"), ".py", "proj/a.py", KEY), "INVALID")

    def test_wrong_key(self):
        """A stamp made with one key does not check under another."""
        self.assertEqual(st.check_text(self.out, ".py", "proj/a.py", OTHER_KEY), "INVALID")

    def test_footer_moved_to_another_path(self):
        """The path is part of the MAC, so a stamped file copied elsewhere is INVALID."""
        self.assertEqual(st.check_text(self.out, ".py", "proj/b.py", KEY), "INVALID")

    def test_restamping_with_the_key_repairs(self):
        """The key holder can restamp a changed file to make it "ok" again."""
        changed = self.out.replace("return 1", "return 2")
        self.assertEqual(st.check_text(stamped(changed, ".py"), ".py", "proj/a.py", KEY), "ok")


class Repository(unittest.TestCase):
    """Which files are in scope, and run() / source_files() on throwaway git repositories."""

    def test_scope(self):
        """Source extensions are in; excluded folders, data files and Markdown are out."""
        self.assertTrue(st.in_scope("src/web.rs"))
        self.assertFalse(st.in_scope("reference/throttle/excerpt.go"))
        self.assertFalse(st.in_scope("testdata/fixture/x.py"))
        self.assertFalse(st.in_scope("data/settings.json"))
        self.assertFalse(st.in_scope("README.md"))

    def test_generated(self):
        """Both common "generated ... do not edit" markers count; the word "generated" alone does not."""
        self.assertTrue(st.generated("// Code generated by x. DO NOT EDIT.\npackage y\n"))
        self.assertTrue(st.generated("-- The schema, generated by export_mock.py, do not edit by hand.\n"))
        self.assertFalse(st.generated("# Writes generated files.\n"))

    def test_run_stamps_then_checks_a_real_git_repo(self):
        """run() stamps a.py and b.go, leaves excluded, data and non-UTF-8 files byte for byte alone.

        The repo holds one file of each kind: stamped (a.py, b.go), in an excluded folder
        (reference/c.go), not source (d.json) and not UTF-8 (e.py).
        """
        with tempfile.TemporaryDirectory() as root:
            # run git inside the temporary repository, failing the test on any error
            def git(*args):
                subprocess.run(["git", "-C", root] + list(args), check=True, capture_output=True)
            git("init", "-q")
            os.makedirs(os.path.join(root, "reference"))
            files = {"a.py": b"x = 1\n", "b.go": b"package b\n", "reference/c.go": b"package c\n",
                     "d.json": b"{}\n", "e.py": b"\xff\xfe"}
            for name, data in files.items():
                with open(os.path.join(root, name), "wb") as f:
                    f.write(data)
            git("add", ".")
            with mock.patch.dict(os.environ, {st.KEY_ENV: KEY.hex()}), contextlib.redirect_stdout(io.StringIO()):
                st.run(root, "stamp")
                self.assertEqual(st.run(root, "check"), 0)  # e.py is skipped, a.py and b.go are ok
            for name in ("reference/c.go", "d.json", "e.py"):
                with open(os.path.join(root, name), "rb") as f:
                    self.assertEqual(f.read(), files[name])
            with open(os.path.join(root, "a.py"), encoding="utf-8") as f:
                self.assertEqual(st.check_text(f.read(), ".py", "a.py", KEY), "ok")

    def test_files_are_labelled_with_their_program_folder(self):
        """A setup.json makes utilities/app a program; its files and nested files are labelled "app".

        tools/x.py has no program folder, so it belongs to "portfolio"; the PROVENANCE.md next to
        setup.json adds the provenance line to the app's headers.
        """
        with tempfile.TemporaryDirectory() as root:
            # run git inside the temporary repository, failing the test on any error
            def git(*args):
                subprocess.run(["git", "-C", root] + list(args), check=True, capture_output=True)
            git("init", "-q")
            files = {"utilities/app/setup.json": "{}\n", "utilities/app/PROVENANCE.md": "# Provenance\n",
                     "utilities/app/a.py": '"""App."""\n', "utilities/app/lib/b.py": '"""Lib."""\n',
                     "tools/x.py": '"""Tool."""\n'}
            for name, text in files.items():
                os.makedirs(os.path.dirname(os.path.join(root, name)), exist_ok=True)
                with open(os.path.join(root, name), "w", encoding="utf-8") as f:
                    f.write(text)
            git("add", ".")
            found = {f[0]: f[1:] for f in st.source_files(root)}
            self.assertEqual(found["utilities/app/a.py"], ("app", "a.py", "utilities/app"))
            self.assertEqual(found["utilities/app/lib/b.py"], ("app", "lib/b.py", "utilities/app"))
            self.assertEqual(found["tools/x.py"], ("portfolio", "tools/x.py", ""))
            with mock.patch.dict(os.environ, {st.KEY_ENV: KEY.hex()}), contextlib.redirect_stdout(io.StringIO()):
                st.run(root, "stamp")
            with open(os.path.join(root, "utilities", "app", "a.py"), encoding="utf-8") as f:
                text = f.read()
            self.assertIn("# Project: app | File: a.py\n", text)
            self.assertIn("PROVENANCE.md", text)
            self.assertEqual(st.check_text(text, ".py", "utilities/app/a.py", KEY), "ok")
            with open(os.path.join(root, "tools", "x.py"), encoding="utf-8") as f:
                self.assertIn("# Project: portfolio | File: tools/x.py\n", f.read())


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=8eac747357f293f165bdc749cf170da2aa91dbc2308ee1535ab5e3f1d32e1538 ====
