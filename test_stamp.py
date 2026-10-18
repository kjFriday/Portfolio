# ==== ACME Inc. portfolio ===============================================
# Project: portfolio | File: test_stamp.py
# About: Tests for stamp.py.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

import ast
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import stamp as st  # noqa: E402

KEY = bytes(range(32))
OTHER_KEY = bytes(range(1, 33))


def stamped(text, ext, year="2026", provenance=False):
    return st.stamp_text(text, ext, "proj/a" + ext, "proj", "a" + ext, KEY, year=year, provenance=provenance)


class RoundTrip(unittest.TestCase):
    SAMPLES = {
        ".py": '"""Load the seed rows. More text."""\nimport os\n',
        ".ps1": "# End-to-end check of the programs.\nparam([string]$X)\n",
        ".go": "// Package foo parses things.\npackage foo\n",
        ".rs": "//! The dashboard core.\nfn main() {}\n",
        ".js": "/* Draws the chart. */\nconst a = 1;\n",
        ".css": "/* Page styles. */\nbody { margin: 0 }\n",
        ".html": "<!DOCTYPE html>\n<html><head><title>ACME Tickets</title></head></html>\n",
        ".sql": "-- Shared schema; owned by the hub.\nCREATE TABLE t (id INTEGER);\n",
    }

    def test_every_style_checks_ok_and_is_idempotent(self):
        for ext, text in self.SAMPLES.items():
            with self.subTest(ext=ext):
                once = stamped(text, ext)
                self.assertEqual(st.check_text(once, ext, "proj/a" + ext, KEY), "ok")
                self.assertEqual(stamped(once, ext), once)

    def test_unstamped_is_missing(self):
        self.assertEqual(st.check_text("x = 1\n", ".py", "proj/a.py", KEY), "missing")

    def test_about_comes_from_the_doc_comment(self):
        expect = {
            ".py": "Load the seed rows.", ".ps1": "End-to-end check of the programs.",
            ".go": "Package foo parses things.", ".rs": "The dashboard core.", ".js": "Draws the chart.",
            ".css": "Page styles.", ".html": "ACME Tickets", ".sql": "Shared schema, owned by the hub.",
        }
        for ext, text in self.SAMPLES.items():
            with self.subTest(ext=ext):
                self.assertIn(st.STYLES[ext].wrap("About: " + expect[ext]), stamped(text, ext))

    def test_about_falls_back_to_language(self):
        self.assertIn("# About: Python source for proj.", stamped("x = 1\n", ".py"))

    def test_about_skips_build_tags_and_rust_attributes(self):
        go = "//go:build ignore\n\n// Excerpt kept for reading.\npackage x\n"
        self.assertEqual(st.about(go.splitlines(), ".go"), "Excerpt kept for reading.")
        rs = '#![windows_subsystem = "windows"]\n//! Ticket window.\nfn main() {}\n'
        self.assertEqual(st.about(rs.splitlines(), ".rs"), "Ticket window.")

    def test_about_is_one_safe_line(self):
        long = "# " + "word " * 40 + "\n"
        self.assertLessEqual(len(st.about(long.splitlines(), ".py")), st.ABOUT_MAX + 3)
        self.assertNotIn("--", st.sentence("a -- b", st.STYLES[".html"]))
        self.assertNotIn("*/", st.sentence("a */ b", st.STYLES[".css"]))

    def test_sentence_does_not_stop_at_abbreviations(self):
        self.assertEqual(st.sentence("Where the ACME Inc. programs live. More.", st.STYLES[".py"]),
                         "Where the ACME Inc. programs live.")

    def test_fallbacks(self):
        self.assertEqual(st.fallback(["package db"], ".go", "cms", "internal/db/db_test.go"), "Tests for package db.")
        self.assertEqual(st.fallback(["package db"], ".go", "cms", "internal/db/x.go"), "Part of package db in cms.")
        self.assertEqual(st.fallback([], ".py", "hub", "test_paths.py"), "Tests for paths.py.")
        self.assertEqual(st.fallback([], ".rs", "dash", "src/core/mod.rs"), "Module list for core.")

    def test_provenance_line(self):
        self.assertIn("PROVENANCE.md", stamped("x = 1\n", ".py", provenance=True))
        self.assertNotIn("PROVENANCE.md", stamped("x = 1\n", ".py"))

    def test_empty_file(self):
        out = stamped("", ".py")
        self.assertEqual(st.check_text(out, ".py", "proj/a.py", KEY), "ok")
        self.assertEqual(stamped(out, ".py"), out)

    def test_file_without_final_newline(self):
        out = stamped("x = 1", ".py")
        self.assertEqual(st.check_text(out, ".py", "proj/a.py", KEY), "ok")

    def test_existing_year_is_kept(self):
        out = stamped("x = 1\n", ".py", year="2025")
        self.assertIn("(c) 2025 ", stamped(out, ".py", year="2030"))


class Placement(unittest.TestCase):
    def test_shebang_and_coding_cookie_stay_first(self):
        out = stamped("#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\nx = 1\n", ".py")
        lines = out.splitlines()
        self.assertEqual(lines[:2], ["#!/usr/bin/env python3", "# -*- coding: utf-8 -*-"])
        self.assertEqual(lines[2], "# " + st.TITLE)

    def test_python_docstring_is_still_the_docstring(self):
        out = stamped('"""Doc."""\nx = 1\n', ".py")
        self.assertEqual(ast.get_docstring(ast.parse(out)), "Doc.")

    def test_doctype_and_charset_stay_first(self):
        self.assertTrue(stamped("<!DOCTYPE html>\n<p>x</p>\n", ".html").startswith("<!DOCTYPE html>\n<!-- ===="))
        self.assertTrue(stamped('@charset "utf-8";\nb{}\n', ".css").startswith('@charset "utf-8";\n/* ===='))

    def test_go_header_is_separated_from_build_tag_and_package_doc(self):
        out = stamped("//go:build ignore\n\npackage x\n", ".go").splitlines()
        rule = out.index("// " + st.RULE)
        self.assertEqual(out[rule + 1], "")
        self.assertEqual(out[rule + 2], "//go:build ignore")

    def test_rust_shebang_like_attribute_is_not_prelude(self):
        self.assertTrue(stamped("#![allow(dead_code)]\nfn f() {}\n", ".rs").startswith("// ===="))

    def test_bom_and_crlf_are_kept(self):
        raw = b"\xef\xbb\xbf# A script.\r\nparam()\r\n"
        text, bom, crlf = st.decode(raw)
        self.assertTrue(bom and crlf)
        out = st.encode(st.stamp_text(text, ".ps1", "p/a.ps1", "p", "a.ps1", KEY), bom, crlf)
        self.assertTrue(out.startswith(b"\xef\xbb\xbf# ===="))
        self.assertNotIn(b"\n", out.replace(b"\r\n", b""))
        again = st.decode(out)[0]
        self.assertEqual(st.check_text(again, ".ps1", "p/a.ps1", KEY), "ok")

    def test_not_utf8(self):
        self.assertIsNone(st.decode(b"\xff\xfe\x00x"))


class Tamper(unittest.TestCase):
    def setUp(self):
        self.out = stamped("def f():\n    return 1\n", ".py")

    def test_body_change(self):
        self.assertEqual(st.check_text(self.out.replace("return 1", "return 2"), ".py", "proj/a.py", KEY), "INVALID")

    def test_header_change(self):
        self.assertEqual(st.check_text(self.out.replace("kjFriday |", "someone |"), ".py", "proj/a.py", KEY), "INVALID")

    def test_wrong_key(self):
        self.assertEqual(st.check_text(self.out, ".py", "proj/a.py", OTHER_KEY), "INVALID")

    def test_footer_moved_to_another_path(self):
        self.assertEqual(st.check_text(self.out, ".py", "proj/b.py", KEY), "INVALID")

    def test_restamping_with_the_key_repairs(self):
        changed = self.out.replace("return 1", "return 2")
        self.assertEqual(st.check_text(stamped(changed, ".py"), ".py", "proj/a.py", KEY), "ok")


class Repository(unittest.TestCase):
    def test_scope(self):
        self.assertTrue(st.in_scope("src/web.rs"))
        self.assertFalse(st.in_scope("reference/throttle/excerpt.go"))
        self.assertFalse(st.in_scope("testdata/fixture/x.py"))
        self.assertFalse(st.in_scope("data/settings.json"))
        self.assertFalse(st.in_scope("README.md"))

    def test_generated(self):
        self.assertTrue(st.generated("// Code generated by x. DO NOT EDIT.\npackage y\n"))
        self.assertTrue(st.generated("-- The schema, generated by export_mock.py, do not edit by hand.\n"))
        self.assertFalse(st.generated("# Writes generated files.\n"))

    def test_run_stamps_then_checks_a_real_git_repo(self):
        with tempfile.TemporaryDirectory() as root:
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
            os.environ[st.KEY_ENV] = KEY.hex()
            try:
                st.run(root, "stamp")
                self.assertEqual(st.run(root, "check"), 0)  # e.py is skipped, a.py and b.go are ok
            finally:
                del os.environ[st.KEY_ENV]
            for name in ("reference/c.go", "d.json", "e.py"):
                with open(os.path.join(root, name), "rb") as f:
                    self.assertEqual(f.read(), files[name])
            with open(os.path.join(root, "a.py"), encoding="utf-8") as f:
                self.assertEqual(st.check_text(f.read(), ".py", "a.py", KEY), "ok")


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=5f8b56ebcf649927a3b868d662e5979e61343f7c6458d987003411ae206a2956 ====
