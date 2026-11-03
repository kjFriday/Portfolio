# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: publish.py
# About: Publishing the nonlocal redirect pages: writing them into a folder a web host serves...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Publishing the nonlocal redirect pages: writing them into a folder a web host serves, without copying files
by hand. links.json's nonlocal.publish says where:
  kind "git"     a folder in a Git repository, such as one GitHub Pages serves. CNAME (the base's host) and
                 .nojekyll are written too, and the pages are committed and pushed.
  kind "folder"  a folder something else syncs. The pages are written there, and that is all.

Nothing changes until it is asked for: plan_pages() exports into a temporary folder and compares it with the
target, so the person sees which pages would be added, changed or removed first. apply_pages() then writes them. A
page whose short link is gone is removed, but only ID-named folders' index.html, never anything else there.
A commit holds only the pages it made, even if other work is staged in that repository, and a push is never
forced: a rejected push is reported, and the commit stays.

Records
  Result   {"ok": bool, "error": str, "value": any}
  Changes  {"folder", "added": [paths], "changed": [paths], "removed": [paths], "skipped": [IDs]}  paths use /
  Pushed   {"committed": bool, "commit": str, "pushed": bool, "push_error": str}
"""

import hashlib
import os
import shutil
import subprocess
import tempfile

import shortlinks

KINDS = ("", "git", "folder")
ROOT_PAGES = ("index.html", "404.html", "robots.txt", "CNAME", ".nojekyll")
GIT_TIMEOUT = 60
PUSH_TIMEOUT = 180


def ok_result(value):
    return {"ok": True, "error": "", "value": value}


def fail(error):
    return {"ok": False, "error": error, "value": None}


def is_id_page(relative):
    """True for "…/73491205/index.html": a page this program writes, by its shape."""
    parts = relative.split("/")
    return len(parts) >= 2 and parts[len(parts) - 1] == "index.html" and shortlinks.is_valid_code(parts[len(parts) - 2])


def page_digest(path):
    """A file's hash with its line ends made the same, since Git may hand back pages with CRLF."""
    handle = open(path, "rb")
    try:
        return hashlib.sha256(handle.read().replace(b"\r\n", b"\n")).hexdigest()
    finally:
        handle.close()


def pages_in(folder):
    """The pages in a folder, as this program would have written them -> {relative path: hash}. Any
    other file is not ours and is not looked at; a repository's own .git folder is not even entered."""
    found = {}
    for root, folders, files in os.walk(folder):
        if ".git" in folders:
            folders.remove(".git")
        for name in files:
            relative = os.path.relpath(os.path.join(root, name), folder).replace(os.sep, "/")
            if relative in ROOT_PAGES or is_id_page(relative):
                found[relative] = page_digest(os.path.join(root, name))
    return found


def cname_of(base):
    """The host a CNAME file names, in lower case, without a port; "" for a host GitHub gives itself."""
    host = shortlinks.host_of(base).split(":")[0].lower()
    if host.endswith(".github.io"):
        return ""
    return host


def write_pages(folder, kind, rows, base, tags):
    """The pages and, for Git, CNAME and .nojekyll -> Result of shortlinks.export_pages."""
    written = shortlinks.export_pages(folder, rows, base, tags)
    if not written["ok"]:
        return written
    if kind == "git":
        try:
            cname = cname_of(base)
            if cname != "":
                shortlinks.write_text(os.path.join(folder, "CNAME"), cname + "\n")
            shortlinks.write_text(os.path.join(folder, ".nojekyll"), "")
        except OSError as error:
            return fail("cannot write the redirect pages: " + str(error))
    return written


def check_target(folder, kind, base):
    """"" when pages can be published to this folder from this base, else what is wrong."""
    if kind not in ("git", "folder"):
        return "set nonlocal.publish in links.json first: its kind (git or folder) and its folder"
    if folder == "":
        return "set nonlocal.publish's folder in links.json first"
    if shortlinks.is_placeholder(base):
        return "set your own nonlocal address in links.json first: " + base + " is only a placeholder"
    if kind == "git":
        if not os.path.isdir(folder):
            return folder + " is not there: clone the repository first"
        inside = git(folder, ["rev-parse", "--is-inside-work-tree"], GIT_TIMEOUT)
        if not inside["ok"]:
            if "not found" in inside["error"]:
                return inside["error"]
            return folder + " is not in a Git repository"
    return ""


def compare(old, new):
    """Two {path: hash} tables -> what going from one to the other would do. Only an ID's page is ever
    removed: the pages at the top are always written, and a CNAME left there may be someone's."""
    added = []
    changed = []
    removed = []
    for path in sorted(new):
        if path not in old:
            added.append(path)
        elif old[path] != new[path]:
            changed.append(path)
    for path in sorted(old):
        if path not in new and is_id_page(path):
            removed.append(path)
    return added, changed, removed


def plan_pages(folder, kind, rows, base, tags):
    """What publishing would change, with nothing touched -> Result Changes."""
    problem = check_target(folder, kind, base)
    if problem != "":
        return fail(problem)
    scratch = tempfile.mkdtemp(prefix="qr_palette_publish_")
    try:
        written = write_pages(scratch, kind, rows, base, tags)
        if not written["ok"]:
            return written
        old = {}
        if os.path.isdir(folder):
            old = pages_in(folder)
        added, changed, removed = compare(old, pages_in(scratch))
    except OSError as error:
        return fail("cannot compare the pages: " + str(error))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return ok_result({"folder": folder, "added": added, "changed": changed, "removed": removed,
                      "skipped": written["value"]["skipped"]})


def apply_pages(folder, kind, rows, base, tags):
    """Write the pages into the folder and remove those whose short link is gone -> Result Changes."""
    plan = plan_pages(folder, kind, rows, base, tags)
    if not plan["ok"]:
        return plan
    written = write_pages(folder, kind, rows, base, tags)
    if not written["ok"]:
        return written
    try:
        for relative in plan["value"]["removed"]:
            path = os.path.join(folder, *relative.split("/"))
            os.remove(path)
            parent = os.path.dirname(path)
            if os.path.abspath(parent) != os.path.abspath(folder) and len(os.listdir(parent)) == 0:
                os.rmdir(parent)
    except OSError as error:
        return fail("cannot remove an old page: " + str(error))
    return plan


# --- Git ---------------------------------------------------------------------------------------------

def git(folder, arguments, timeout):
    """Run git in a folder -> Result its output. It never waits for a person: with no credentials to
    hand it fails, and says so. No console window opens."""
    environment = dict(os.environ)
    environment["GIT_TERMINAL_PROMPT"] = "0"
    try:
        done = subprocess.run(["git"] + arguments, cwd=folder, env=environment, capture_output=True, timeout=timeout,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError:
        return fail("git was not found on this computer")
    except subprocess.TimeoutExpired:
        return fail("git " + arguments[0] + " took longer than " + str(timeout) + " seconds")
    except OSError as error:
        return fail("cannot run git: " + str(error))
    output = done.stdout.decode("utf-8", "replace")
    if done.returncode != 0:
        said = done.stderr.decode("utf-8", "replace").strip() or output.strip()
        return {"ok": False, "error": said or ("git " + arguments[0] + " failed"), "value": done.returncode}
    return ok_result(output)


def commit_message(changes):
    return ("QR Palette: redirect pages: " + str(len(changes["added"])) + " added, " + str(len(changes["changed"])) +
            " changed, " + str(len(changes["removed"])) + " removed")


def commit_pages(folder, changes):
    """Commit exactly the pages that changed -> Result the new commit's hash, "" when Git sees nothing
    new. Whatever else is staged in the repository stays staged and out of this commit."""
    paths = changes["added"] + changes["changed"] + changes["removed"]
    if len(paths) == 0:
        return ok_result("")
    added = git(folder, ["add", "-A", "--"] + paths, GIT_TIMEOUT)
    if not added["ok"]:
        return fail("cannot stage the pages: " + added["error"])
    staged = git(folder, ["diff", "--cached", "--quiet", "--"] + paths, GIT_TIMEOUT)
    if staged["ok"]:
        return ok_result("")  # the same as before, line ends apart
    made = git(folder, ["commit", "-q", "-m", commit_message(changes), "--"] + paths, GIT_TIMEOUT)
    if not made["ok"]:
        return fail("cannot commit the pages: " + made["error"])
    head = git(folder, ["rev-parse", "--short", "HEAD"], GIT_TIMEOUT)
    if not head["ok"]:
        return fail(head["error"])
    return ok_result(head["value"].strip())


def push_pages(folder):
    """Push the branch to its remote. Never forced: if the remote has moved on, this fails, and says so
    -> Result True."""
    pushed = git(folder, ["push"], PUSH_TIMEOUT)
    if pushed["ok"]:
        return ok_result(True)
    said = pushed["error"]
    if "rejected" in said or "fetch first" in said or "non-fast-forward" in said:
        return fail("the remote has commits this folder does not; pull them in your Git client, then publish again")
    return fail(said)


def publish(folder, kind, rows, base, tags):
    """Write the pages, and for Git commit and push them -> Result {"changes": Changes, "commit": str, "pushed":
    bool, "push_error": str}. A failed push leaves the commit in place."""
    applied = apply_pages(folder, kind, rows, base, tags)
    if not applied["ok"]:
        return applied
    result = {"changes": applied["value"], "commit": "", "pushed": False, "push_error": ""}
    if kind != "git":
        return ok_result(result)
    committed = commit_pages(folder, applied["value"])
    if not committed["ok"]:
        return committed
    result["commit"] = committed["value"]
    if committed["value"] != "":
        pushed = push_pages(folder)
        result["pushed"] = pushed["ok"]
        result["push_error"] = pushed["error"]
    return ok_result(result)

# ==== stamp v1 | author=kjFriday | hmac-sha256=a63d0c8d2535187b820fc248f2fcf1d77ef5ad4a3032a23c62042401a1596cca ====
