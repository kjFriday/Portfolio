# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: tests/test_publish.py
# About: Tests for publishing the nonlocal pages: plans, writes, removals, Git commits and pushes.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Tests for publishing the nonlocal pages: plans, writes, removals, Git commits and pushes.

These pin what would change, with nothing touched; writing and removing only this program's pages;
and commits in a temporary Git repository. Pushes only go to a bare repository in the same temporary
folder: nothing leaves this computer.

A nonlocal short link is a static redirect page at <base>/<ID>/index.html, where the ID is digits
ending in a Damm check digit. publish.py writes those pages into a folder (kind "folder") or into a Git
work tree it then commits and pushes (kind "git", with CNAME and .nojekyll for GitHub Pages).

Classes:
  SettingTests  links.json's nonlocal.publish setting: its default and how a bad one is refused
  FolderCase    the temporary folder shared by the two classes below
  FolderTests   plan_pages and apply_pages on a plain folder, and the helpers that judge paths
  GitTests      publish into a real Git repository (needs git on PATH), and the program's own path
                from the registry through short_link_ops

Run with the rest of the suite: python -m unittest discover -s tests, in the program folder.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

import app_settings
import making
import publish
import short_link_ops
import shortlinks

# a base address that is not a placeholder (GO.EXAMPLE.COM is one, so it would be refused), and the
# scan tags added to every destination
BASE = "HTTPS://GO.EXAMPLE.SHOP/"
TAGS = {"utm_source": "qr"}


def code_of(body):
    """A valid short-link ID: `body` followed by its Damm check digit."""
    return body + shortlinks.check_digit(body)


# three valid 8-digit IDs
FIRST = code_of("1234567")
SECOND = code_of("7654321")
THIRD = code_of("1111111")


def row(code, target="https://example.com/menu", base=BASE):
    """A registry short-link row for ID `code` under `base`, pointing at `target`."""
    return {"code": code, "url": base + code, "target": target, "hex": "#3366cc", "created": "", "updated": "",
            "pictures": 1}


def read(path):
    """A text file's contents (UTF-8)."""
    handle = open(path, encoding="utf-8")
    try:
        return handle.read()
    finally:
        handle.close()


class SettingTests(unittest.TestCase):
    """nonlocal.publish in links.json: off by default, and a bad value falls back to off with one warning."""

    def setUp(self):
        """A temporary folder for links.json."""
        self.root = tempfile.mkdtemp(prefix="qr_palette_publish_links_")
        self.path = os.path.join(self.root, "links.json")

    def tearDown(self):
        """Remove the folder."""
        shutil.rmtree(self.root, ignore_errors=True)

    def load(self, publish_value):
        """Write a links.json whose nonlocal.publish is `publish_value` and load it -> {"links", "warnings"}."""
        handle = open(self.path, "w", encoding="utf-8")
        handle.write(json.dumps({"nonlocal": {"publish": publish_value}}))
        handle.close()
        return shortlinks.load_links(self.path)

    def test_the_default_is_not_set_up(self):
        """The default publish target is empty, and copy_links copies deeply, so a change never reaches it."""
        self.assertEqual(shortlinks.DEFAULT_LINKS["nonlocal"]["publish"], {"kind": "", "folder": ""})
        copied = shortlinks.copy_links(shortlinks.DEFAULT_LINKS)
        copied["nonlocal"]["publish"]["kind"] = "git"  # a copy, all the way down
        self.assertEqual(shortlinks.DEFAULT_LINKS["nonlocal"]["publish"]["kind"], "")

    def test_a_target_is_read_and_checked(self):
        """A git target loads as written; an unknown kind, a folder that is not text, or a value that is not
        an object each fall back to the empty target with one warning."""
        loaded = self.load({"kind": "git", "folder": self.root})
        self.assertEqual((loaded["links"]["nonlocal"]["publish"], loaded["warnings"]),
                         ({"kind": "git", "folder": self.root}, []))
        for bad in ({"kind": "ftp", "folder": self.root}, {"kind": "git", "folder": 3}, "git"):
            loaded = self.load(bad)
            self.assertEqual(loaded["links"]["nonlocal"]["publish"], {"kind": "", "folder": ""})
            self.assertEqual(len(loaded["warnings"]), 1)


class FolderCase(unittest.TestCase):
    """A temporary root with the publish folder ("site") inside it, not yet made."""

    def setUp(self):
        """Make the root; self.folder is root/site."""
        self.root = tempfile.mkdtemp(prefix="qr_palette_publish_test_")
        self.folder = os.path.join(self.root, "site")

    def tearDown(self):
        """Remove the root, making read-only files writable first.

        Git writes its object files read-only, and on Windows a read-only file cannot be deleted, so
        each failed removal is retried after a chmod."""
        # rmtree's onerror hook: make `path` writable, then retry the call that failed on it
        def unlock(function, path, information):
            os.chmod(path, 0o700)
            function(path)

        shutil.rmtree(self.root, onerror=unlock)

    def page(self, code):
        """Where the redirect page for ID `code` goes in the folder."""
        return os.path.join(self.folder, code, "index.html")


class FolderTests(FolderCase):
    """Publishing into a plain folder (kind "folder"): plans, writes, and what may be removed."""

    def test_a_plan_touches_nothing(self):
        """A plan lists the ID page and the three root pages as added, and does not even make the folder."""
        planned = publish.plan_pages(self.folder, "folder", [row(FIRST)], BASE, TAGS)
        self.assertTrue(planned["ok"], planned["error"])
        self.assertEqual(planned["value"]["added"], [FIRST + "/index.html", "404.html", "index.html", "robots.txt"])
        self.assertEqual((planned["value"]["changed"], planned["value"]["removed"]), ([], []))
        self.assertFalse(os.path.exists(self.folder))

    def test_applying_then_planning_again_finds_nothing(self):
        """After apply_pages, a plan for the same rows finds nothing to add, change or remove."""
        self.assertTrue(publish.apply_pages(self.folder, "folder", [row(FIRST)], BASE, TAGS)["ok"])
        self.assertTrue(os.path.isfile(self.page(FIRST)))
        again = publish.plan_pages(self.folder, "folder", [row(FIRST)], BASE, TAGS)["value"]
        self.assertEqual((again["added"], again["changed"], again["removed"]), ([], [], []))

    def test_a_new_destination_is_a_changed_page(self):
        """A short link pointed somewhere new shows as its page changed, nothing added."""
        publish.apply_pages(self.folder, "folder", [row(FIRST)], BASE, TAGS)
        changed = publish.plan_pages(self.folder, "folder", [row(FIRST, "https://example.com/winter")], BASE, TAGS)["value"]
        self.assertEqual((changed["added"], changed["changed"]), ([], [FIRST + "/index.html"]))

    def test_only_our_pages_are_removed(self):
        """A gone short link's page is removed; the person's own files are kept, byte for byte.

        Kept: a top-level page, a digit folder whose name fails the Damm check ("12345"), an index.html
        in a non-ID folder, a CNAME, and a file beside the removed page, whose folder then stays."""
        publish.apply_pages(self.folder, "folder", [row(FIRST), row(SECOND)], BASE, TAGS)
        keep = {os.path.join(self.folder, "about.html"): "mine",
                os.path.join(self.folder, "12345", "index.html"): "a folder of mine, not an ID",
                os.path.join(self.folder, "assets", "index.html"): "mine too",
                os.path.join(self.folder, "CNAME"): "www.example.shop\n"}
        for path in keep:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            handle = open(path, "w", encoding="utf-8")
            handle.write(keep[path])
            handle.close()
        beside = os.path.join(self.folder, SECOND, "notes.txt")
        handle = open(beside, "w", encoding="utf-8")
        handle.write("mine")
        handle.close()
        applied = publish.apply_pages(self.folder, "folder", [row(FIRST)], BASE, TAGS)
        self.assertEqual(applied["value"]["removed"], [SECOND + "/index.html"])
        self.assertFalse(os.path.exists(self.page(SECOND)))
        self.assertTrue(os.path.isfile(beside))  # its folder stays, since it is not empty
        for path in keep:
            self.assertEqual(read(path), keep[path])

    def test_an_emptied_id_folder_goes_too(self):
        """Removing an ID's only page removes its folder as well."""
        publish.apply_pages(self.folder, "folder", [row(FIRST), row(SECOND)], BASE, TAGS)
        publish.apply_pages(self.folder, "folder", [row(FIRST)], BASE, TAGS)
        self.assertFalse(os.path.exists(os.path.join(self.folder, SECOND)))

    def test_a_short_link_on_another_address_is_left_out(self):
        """A row under a different base (a local server's address) is skipped, not written."""
        applied = publish.apply_pages(self.folder, "folder", [row(FIRST), row(SECOND, base="HTTP://LOCALHOST:8000/")], BASE,
                                      TAGS)
        self.assertEqual(applied["value"]["skipped"], [SECOND])
        self.assertFalse(os.path.exists(self.page(SECOND)))

    def test_a_synced_folder_gets_no_cname(self):
        """CNAME and .nojekyll are for GitHub Pages, so a plain folder gets neither."""
        publish.apply_pages(self.folder, "folder", [row(FIRST)], BASE, TAGS)
        self.assertFalse(os.path.exists(os.path.join(self.folder, "CNAME")))
        self.assertFalse(os.path.exists(os.path.join(self.folder, ".nojekyll")))

    def test_what_is_refused(self):
        """Refused, each with a message naming the fix: no kind, no folder, a placeholder base, a git folder
        that is not there (clone it), and a git folder outside a repository."""
        for folder, kind, base, problem in ((self.folder, "", BASE, "nonlocal.publish"), ("", "folder", BASE, "folder"),
                                            (self.folder, "folder", "HTTPS://GO.EXAMPLE.COM/", "placeholder"),
                                            (self.folder, "git", BASE, "clone")):
            refused = publish.plan_pages(folder, kind, [row(FIRST)], base, TAGS)
            self.assertFalse(refused["ok"], kind)
            self.assertIn(problem, refused["error"])
        os.makedirs(self.folder)
        self.assertIn("not in a Git repository", publish.plan_pages(self.folder, "git", [row(FIRST)], BASE, TAGS)["error"])

    def test_cname(self):
        """CNAME holds the base's host in lower case without a port; a github.io host needs none."""
        self.assertEqual(publish.cname_of("HTTPS://GO.EXAMPLE.SHOP/"), "go.example.shop")
        self.assertEqual(publish.cname_of("HTTP://GO.EXAMPLE.SHOP:8080/Q/"), "go.example.shop")
        self.assertEqual(publish.cname_of("HTTPS://ME.GITHUB.IO/"), "")

    def test_pages_are_told_by_their_shape(self):
        """An ID page is <valid ID>/index.html, under a section folder too; a root page, an 8-digit folder
        that fails the check digit, a word folder and another file name are not."""
        self.assertTrue(publish.is_id_page(FIRST + "/index.html"))
        self.assertTrue(publish.is_id_page("Q/" + FIRST + "/index.html"))
        for path in ("index.html", "12345678/index.html", "assets/index.html", FIRST + "/other.html"):
            self.assertFalse(publish.is_id_page(path), path)


class GitTests(FolderCase):
    """Publishing into a fresh Git repository in the temporary root, with a bare repository as its remote.

    Each repository is set up so the machine's own Git setup cannot change the result: a test identity,
    no commit signing, an empty hooks folder and no line-end conversion."""

    def run_git(self, folder, *arguments):
        """Run git with `arguments` in `folder`, fail the test on a non-zero exit -> stdout as text.

        CREATE_NO_WINDOW (Windows only; 0 elsewhere) keeps a console window from opening for each run."""
        done = subprocess.run(["git"] + list(arguments), cwd=folder, capture_output=True,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.decode("utf-8")

    def setUp(self):
        """Make the site folder a new repository on branch main, with an empty hooks folder beside it."""
        FolderCase.setUp(self)
        os.makedirs(self.folder)
        self.hooks = os.path.join(self.root, "no-hooks")  # this computer's own hooks are not part of the test
        os.makedirs(self.hooks)
        self.configure(self.folder, True)

    def configure(self, folder, new):
        """Set the test identity and settings in `folder`'s repository, running git init first when `new`."""
        if new:
            self.run_git(folder, "init", "-q", "-b", "main")
        self.run_git(folder, "config", "user.name", "Test")
        self.run_git(folder, "config", "user.email", "test@example.com")
        self.run_git(folder, "config", "commit.gpgsign", "false")
        self.run_git(folder, "config", "core.hooksPath", self.hooks)
        self.run_git(folder, "config", "core.autocrlf", "false")

    def first_commit(self):
        """Commit a README.txt, so the repository has a HEAD and history of the person's own."""
        handle = open(os.path.join(self.folder, "README.txt"), "w", encoding="utf-8")
        handle.write("mine\n")
        handle.close()
        self.run_git(self.folder, "add", "README.txt")
        self.run_git(self.folder, "commit", "-q", "-m", "first")

    def add_remote(self):
        """Make a bare repository root/remote.git, add it as origin and push main to it -> its path."""
        remote = os.path.join(self.root, "remote.git")
        self.run_git(self.root, "init", "-q", "--bare", "-b", "main", remote)
        self.run_git(self.folder, "remote", "add", "origin", remote)
        self.run_git(self.folder, "push", "-q", "-u", "origin", "main")
        return remote

    def test_the_pages_are_committed_with_cname_and_nojekyll(self):
        """One commit holds the ID page, CNAME and .nojekyll, with a message counting the changes, and leaves
        a clean work tree.

        The 6 added are the ID page, index.html, 404.html, robots.txt, CNAME and .nojekyll."""
        self.first_commit()
        done = publish.publish(self.folder, "git", [row(FIRST)], BASE, TAGS)
        self.assertTrue(done["ok"], done["error"])
        self.assertNotEqual(done["value"]["commit"], "")
        self.assertEqual(read(os.path.join(self.folder, "CNAME")), "go.example.shop\n")
        names = self.run_git(self.folder, "show", "--name-only", "--format=%s", "HEAD").split()
        self.assertIn(FIRST + "/index.html", names)
        self.assertIn("CNAME", names)
        self.assertIn(".nojekyll", names)
        self.assertEqual(self.run_git(self.folder, "log", "-1", "--format=%s"),
                         "QR Palette: redirect pages: 6 added, 0 changed, 0 removed\n")
        self.assertEqual(self.run_git(self.folder, "status", "--short"), "")

    def test_nothing_changed_is_no_commit(self):
        """Publishing the same rows again makes no commit: commit is "" and HEAD stays."""
        self.first_commit()
        publish.publish(self.folder, "git", [row(FIRST)], BASE, TAGS)
        before = self.run_git(self.folder, "rev-parse", "HEAD")
        done = publish.publish(self.folder, "git", [row(FIRST)], BASE, TAGS)
        self.assertEqual(done["value"]["commit"], "")
        self.assertEqual(self.run_git(self.folder, "rev-parse", "HEAD"), before)

    def test_other_work_stays_out_of_the_commit(self):
        """A file the person staged and one left untracked stay out of the commit, and stay staged and
        untracked afterwards."""
        self.first_commit()
        for name, stage in (("staged.txt", True), ("untracked.txt", False)):
            handle = open(os.path.join(self.folder, name), "w", encoding="utf-8")
            handle.write("my own work\n")
            handle.close()
            if stage:
                self.run_git(self.folder, "add", name)
        publish.publish(self.folder, "git", [row(FIRST)], BASE, TAGS)
        names = self.run_git(self.folder, "show", "--name-only", "--format=", "HEAD").split()
        self.assertNotIn("staged.txt", names)
        self.assertNotIn("untracked.txt", names)
        status = self.run_git(self.folder, "status", "--short")
        self.assertIn("A  staged.txt", status)
        self.assertIn("?? untracked.txt", status)

    def test_removed_pages_are_committed_as_removed(self):
        """A page whose short link is gone is reported removed and is no longer tracked."""
        self.first_commit()
        publish.publish(self.folder, "git", [row(FIRST), row(SECOND)], BASE, TAGS)
        done = publish.publish(self.folder, "git", [row(FIRST)], BASE, TAGS)
        self.assertEqual(done["value"]["changes"]["removed"], [SECOND + "/index.html"])
        self.assertNotIn(SECOND, self.run_git(self.folder, "ls-files"))

    def test_with_no_remote_the_commit_stays_and_the_failure_is_said(self):
        """Without a remote the push fails, but publish still succeeds: the commit stays and push_error says why."""
        self.first_commit()
        done = publish.publish(self.folder, "git", [row(FIRST)], BASE, TAGS)
        self.assertTrue(done["ok"], done["error"])
        self.assertFalse(done["value"]["pushed"])
        self.assertNotEqual(done["value"]["push_error"], "")
        self.assertIn(FIRST, self.run_git(self.folder, "ls-files"))

    def test_a_push_to_a_folder_remote_arrives(self):
        """With a bare repository as origin, the push succeeds and the page is on the remote's main."""
        self.first_commit()
        remote = self.add_remote()
        done = publish.publish(self.folder, "git", [row(FIRST)], BASE, TAGS)
        self.assertTrue(done["value"]["pushed"], done["value"]["push_error"])
        self.assertIn(FIRST, self.run_git(remote, "ls-tree", "-r", "--name-only", "main"))

    def test_a_push_is_never_forced(self):
        """When someone else pushed first, the push is rejected and reported ("pull them"), their commit stays
        on the remote, and the local commit is kept.

        A second clone ("other") pushes theirs.txt, so the remote's main is ahead of the site folder."""
        self.first_commit()
        remote = self.add_remote()
        other = os.path.join(self.root, "other")
        self.run_git(self.root, "clone", "-q", remote, other)
        self.configure(other, False)
        handle = open(os.path.join(other, "theirs.txt"), "w", encoding="utf-8")
        handle.write("theirs\n")
        handle.close()
        self.run_git(other, "add", "theirs.txt")
        self.run_git(other, "commit", "-q", "-m", "theirs")
        self.run_git(other, "push", "-q")
        done = publish.publish(self.folder, "git", [row(FIRST)], BASE, TAGS)
        self.assertTrue(done["ok"], done["error"])
        self.assertFalse(done["value"]["pushed"])
        self.assertIn("pull them", done["value"]["push_error"])
        self.assertIn("theirs.txt", self.run_git(remote, "ls-tree", "-r", "--name-only", "main"))  # theirs is still there
        self.assertNotEqual(done["value"]["commit"], "")

    def test_the_program_publishes_from_its_registry_by_the_day_in_force(self):
        """The program's own path: a made code with a nonlocal short link, a change of destination due on
        2026-12-01, a plan the day before that touches nothing, and a publish on the day that writes the
        new destination.

        app_settings.LINKS is pointed at BASE and this repository for the test and put back after."""
        self.first_commit()
        db = os.path.join(self.root, "palette.db")
        saved = shortlinks.copy_links(app_settings.LINKS)
        app_settings.LINKS["nonlocal"]["base"] = BASE
        app_settings.LINKS["nonlocal"]["publish"] = {"kind": "git", "folder": self.folder}
        try:
            made = making.make_qr(db, "https://example.com/menu", "#3366cc", "M", os.path.join(self.root, "a.png"), 4,
                                  short_link_ops.short_request(FIRST, "nonlocal"))
            self.assertTrue(made["ok"], made["error"])
            self.assertTrue(short_link_ops.schedule_link_change(db, FIRST, "https://example.com/winter",
                                                                "2026-12-01")["ok"])
            plan = short_link_ops.publish_plan(db, "2026-11-30")
            self.assertIn(FIRST + "/index.html", plan["value"]["added"])
            self.assertFalse(os.path.exists(self.page(FIRST)))
            done = short_link_ops.publish_now(db, "2026-12-01")
            self.assertTrue(done["ok"], done["error"])
            self.assertIn("https://example.com/winter", read(self.page(FIRST)))
        finally:
            app_settings.LINKS = saved


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=aed5e13034c4f35269a590a944ba48a1d80f65e803490df2e482e0b28d9cf641 ====
