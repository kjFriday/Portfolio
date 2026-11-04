# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: short_link_ops.py
# About: Short links in the registry: the one a new code prints, where each one goes now and...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Short links in the registry: planning, changes, scans, pages and tamper checks.

A code can hold a short link, a short address (a base from links.json and a Damm-checked ID) printed under
the code, instead of its destination, so the destination can change without reprinting. links.json,
app_settings.LINKS, has two sections: local (this computer or your own network, for trying codes) and
nonlocal (your internet address, for printing). shortlinks.py makes and checks the IDs and writes the
pages; this module works with the short links the registry keeps:
  - the short link a new code prints: short_request, fresh_code (tagged under the local key when links.json
    says so) and plan_short_link, which reuses the one made for the same destination, color and base
  - where a short link goes: changed now (retarget_link), undone, or scheduled for a later day, and its
    history
  - scan counts from an analytics report or a server log (import_scan_file)
  - the redirect pages, exported for a web server (export_redirects) or published where links.json says
  - what the Read tab says about a scanned link: yours, or only looking like yours (tamper_verdict)

Callers: the window's tabs (gui/make_tab.py: short_request, fresh_code, plan_short_link; gui/find_tab.py:
the change, undo, schedule and history calls; gui/read_tab.py: tamper_verdict; gui/window.py: export,
scan import and publishing), making.py (plan_short_link) and the command line in qr_palette.py
(export_redirects). This module calls registry.py for the stored rows, shortlinks.py for IDs and pages,
localkey.py for the tag key, scans.py for scan files and publish.py for publishing.

The usual flow for a new code with a short link:
  1. The Make tab asks short_request() for the base and a ready ID (fresh_code()), so its preview
     already shows the address that will be printed.
  2. plan_short_link() reuses a short link made earlier for the same destination, color and base, or
     settles on a free, valid ID for a new one.
  3. The code is saved (making.py, registry.save_qr); later retarget_link() or schedule_link_change()
     moves the destination, and export_redirects() or publish_now() writes the pages that carry it.

Every function answers with a Result {"ok", "error", "value"} (common.py) instead of raising, except
short_request, fresh_code, tamper_verdict and short_note, which answer plain values. Writes go through
common.with_registry (read-write, one connection per call); the exports and publishing read on the
read-only rail (registry.connect(path, True)).
"""

import app_settings
import localkey
import publish
import qr_codec
import registry
import scans
import shortlinks
from common import fail, ok_result, with_registry


def short_request(code, section):
    """What make_qr needs for a short link: the base of links.json's `section` ("local" or
    "nonlocal"), the ID length, and the ID to use for a new one (the window keeps one ready, so its
    preview shows the code that will be saved)."""
    return {"base": app_settings.LINKS[section]["base"], "digits": app_settings.LINKS["id_digits"], "code": code,
            "section": section}


def fresh_code(db_path, digits):
    """A new short-link ID, tagged when links.json says so and the registry's key can be had; an ID without
    a tag works just the same, so a key that cannot be made never stops a code being made.

    `digits` is the count of random digits (links.json id_digits); the ID adds two tag digits when
    tagged, and always one Damm check digit. Side effect: localkey.key_for() writes the key file beside
    the registry the first time it is needed."""
    key = None
    if app_settings.LINKS["tag_ids"]:
        found = localkey.key_for(db_path)
        if found["ok"]:
            key = found["value"]
    return shortlinks.new_code(digits, key)


def plan_short_link(db_path, target, color, short):
    """The short link a code for `target` in `color` prints -> Result {"code", "url", "made": bool}:
    the one already made on short["base"] for this destination in this color, else a new one there
    with short["code"] (or a fresh ID when that one is not valid or already used). Local and nonlocal
    short links to the same destination are separate, since they print different addresses.

    `short` is short_request()'s record. "made" is True when the short link already exists in the
    registry (nothing new is stored), False when the caller is to save it with the code. Nothing is
    written here: the registry is only read.

    Steps:
      1. Look for a short link on this base with the same destination and color; reuse it.
      2. Otherwise start from the ID the window had ready, and draw fresh IDs while the current one
         fails its Damm check or is already used, giving up after 50 tries.
    """
    def plan(connection):
        """Find or choose the short link inside one registry connection -> Result."""
        found = registry.short_link_for(connection, target, color, short["base"])
        if found is not None:
            return ok_result({"code": found["code"], "url": found["url"], "made": True})
        code = short["code"]
        tries = 0
        # with 7 random digits there are ten million IDs, so 50 straight collisions means the ID space
        # is nearly full; a longer ID is the only way out
        while not shortlinks.is_valid_code(code) or registry.code_taken(connection, code):
            tries = tries + 1
            if tries > 50:
                return fail("cannot find a free short-link ID; raise id_digits in links.json")
            code = fresh_code(db_path, short["digits"])
        return ok_result({"code": code, "url": shortlinks.short_url(short["base"], code), "made": False})

    return with_registry(db_path, plan)


def retarget_link(db_path, code, link):
    """Send short link `code` to `link` from now on -> Result True. Export the pages to publish it.

    `link` is checked and cleaned by shortlinks.check_target first. Side effect: the registry's
    short_links row changes and the old destination goes into the link's history (registry.retarget).
    Fails with "there is no short link ..." when `code` is not in the registry."""
    checked = shortlinks.check_target(link)
    if not checked["ok"]:
        return checked

    def change(connection):
        """Retarget inside one registry connection -> Result True when the short link exists."""
        return registry.retarget(connection, code, checked["value"])

    changed = with_registry(db_path, change)
    if changed["ok"] and not changed["value"]:
        return fail("there is no short link " + code)
    return changed


def undo_link_change(db_path, code):
    """Send short link `code` back where it went before its latest change -> Result its target now.

    The undo is itself written into the history as a change (registry.undo_last_change)."""
    def undo(connection):
        """Undo the latest change inside one registry connection -> Result."""
        return registry.undo_last_change(connection, code)

    return with_registry(db_path, undo)


def schedule_link_change(db_path, code, link, from_day):
    """Send short link `code` to `link` from `from_day` on -> Result the schedule's id.

    `from_day` is a calendar day "YYYY-MM-DD". The change shows in exports from that day on, and in the
    registry's own row once apply_due_changes() runs on or after it."""
    checked = shortlinks.check_target(link)
    if not checked["ok"]:
        return checked

    def schedule(connection):
        """Store the scheduled change inside one registry connection -> Result id."""
        return registry.schedule_change(connection, code, checked["value"], from_day)

    return with_registry(db_path, schedule)


def cancel_link_change(db_path, number):
    """Take back scheduled change `number` before its day -> Result True when there was one.

    A change already applied cannot be cancelled; undo_link_change() reverses it instead."""
    def cancel(connection):
        """Delete the scheduled change inside one registry connection -> Result."""
        return registry.cancel_scheduled(connection, number)

    return with_registry(db_path, cancel)


def link_history(db_path, code):
    """A short link's past and future -> Result {"changes": [Change], "coming": [Scheduled]}.

    "changes" is newest first; "coming" is soonest first. A registry older than schema 3 kept no
    history, so both lists are empty there."""
    def read(connection):
        """Read the history and the schedule inside one registry connection -> Result."""
        return ok_result({"changes": registry.link_changes(connection, code),
                          "coming": registry.scheduled(connection, code)})

    return with_registry(db_path, read)


def due_link_changes(db_path, today):
    """The scheduled changes whose day has come -> Result [Scheduled].

    `today` is "YYYY-MM-DD" (the window passes registry.today_text()); days compare as text, which
    orders correctly because the format is fixed-width."""
    def read(connection):
        """List the due changes inside one registry connection -> Result."""
        return ok_result(registry.due_changes(connection, today))

    return with_registry(db_path, read)


def apply_due_changes(db_path, today):
    """Make the scheduled changes whose day has come -> Result how many.

    Each one is applied in order and written into its link's history, in one transaction."""
    def apply(connection):
        """Apply the due changes inside one registry connection -> Result count."""
        return registry.apply_due(connection, today)

    return with_registry(db_path, apply)


def import_scan_file(db_path, path):
    """Scan counts from an analytics CSV or a server log into the registry -> Result {"kind", "source",
    "read", "ignored", "days", "scans": how many counted, "unknown": [IDs that are not short links here]}.
    Importing the same file again changes nothing.

    Steps:
      1. scans.read_file() parses the file into counts keyed by (code, day).
      2. registry.import_scans() stores one row per (code, day, source), replacing an earlier count,
         and names the codes it does not know.
      3. The scans total counts only the codes the registry knows.
    """
    read = scans.read_file(path)
    if not read["ok"]:
        return read
    value = read["value"]

    def bring(connection):
        """Store the counts inside one registry connection -> Result {"days", "unknown"}."""
        return registry.import_scans(connection, value["counts"], value["source"])

    saved = with_registry(db_path, bring)
    if not saved["ok"]:
        return saved
    counted = 0
    for key in value["counts"]:
        # key is (code, day); scans of IDs that are not short links here were not stored
        if key[0] not in saved["value"]["unknown"]:
            counted = counted + value["counts"][key]
    return ok_result({"kind": value["kind"], "source": value["source"], "read": value["read"],
                      "ignored": value["ignored"], "days": saved["value"]["days"], "scans": counted,
                      "unknown": saved["value"]["unknown"]})


def export_redirects(db_path, folder, section, day=""):
    """Write a redirect page for every short link of `section` ("local" or "nonlocal") into `folder`
    (shortlinks.export_pages), with the destination in force on `day` ("" for today) -> Result. The
    registry is only read, on the read-only rail.

    Side effect: files under `folder` (one index.html per ID, plus index.html, 404.html and
    robots.txt). Short links on the other section's base are skipped by export_pages."""
    if day == "":
        day = registry.today_text()
    opened = registry.connect(db_path, True)
    if not opened["ok"]:
        return opened
    try:
        rows = registry.short_links_on(opened["value"], day)
    except Exception as error:
        return fail("cannot read the short links: " + str(error))
    finally:
        registry.close(opened["value"])
    return shortlinks.export_pages(folder, rows, app_settings.LINKS[section]["base"], app_settings.LINKS["tags"])


def publish_rows(db_path, day):
    """The short links as they should be published on `day` ("" for today) -> Result [ShortLink].

    Read-only: a scheduled change whose day has come counts even before it is applied."""
    opened = registry.connect(db_path, True)
    if not opened["ok"]:
        return opened
    try:
        return ok_result(registry.short_links_on(opened["value"], day or registry.today_text()))
    except Exception as error:
        return fail("cannot read the short links: " + str(error))
    finally:
        registry.close(opened["value"])


def publish_plan(db_path, day=""):
    """What publishing the nonlocal pages would change, with nothing touched -> Result publish.Changes.

    The window shows this list and asks before publish_now() runs."""
    rows = publish_rows(db_path, day)
    if not rows["ok"]:
        return rows
    target = app_settings.LINKS["nonlocal"]["publish"]
    return publish.plan_pages(target["folder"], target["kind"], rows["value"], app_settings.LINKS["nonlocal"]["base"],
                              app_settings.LINKS["tags"])


def publish_now(db_path, day=""):
    """Publish the nonlocal pages where links.json says -> Result of publish.publish.

    Side effects: files in the publish folder, and for kind "git" a commit and a push there
    (publish.py; never forced)."""
    rows = publish_rows(db_path, day)
    if not rows["ok"]:
        return rows
    target = app_settings.LINKS["nonlocal"]["publish"]
    return publish.publish(target["folder"], target["kind"], rows["value"], app_settings.LINKS["nonlocal"]["base"],
                           app_settings.LINKS["tags"])


def tamper_verdict(db_path, text):
    """What the Read tab says about a scanned link -> {"line": str, "warning": bool}, "" for a link that
    has nothing to do with your addresses. A warning is for an address that only looks like yours, or
    an ID on your address that is not yours. Limits: two tag digits are right by chance 1 time in 100.

    Steps:
      1. Anything that is not an http(s) link gets no verdict.
      2. A host that imitates one of your bases (shortlinks.lookalike) is a warning at once.
      3. A link on neither base gets no verdict; otherwise its last path segment is the ID.
      4. shortlinks.code_standing() weighs the ID's check digit, its tag under the local key (read,
         never made here) and whether the registry knows it, and the standing picks the line.

    Side effect: the registry lookup goes through with_registry, which opens read-write and so makes
    an empty registry when the file is missing. A failed lookup counts as "not in this registry"."""
    verdict = {"line": "", "warning": False}
    if not qr_codec.is_link(text):
        return verdict
    bases = (app_settings.LINKS["local"]["base"], app_settings.LINKS["nonlocal"]["base"])
    imitated = shortlinks.lookalike(text, bases)
    if imitated != "":
        verdict["line"] = ("Careful: this address only looks like your " + imitated + ". It goes somewhere else, "
                           "so it may be a sticker over your code.")
        verdict["warning"] = True
        return verdict
    # bases are stored in capitals (QR alphanumeric mode), so compare the scanned text in capitals too
    lifted = text.upper()
    section = ""
    for name in shortlinks.SECTIONS:
        if lifted.startswith(app_settings.LINKS[name]["base"]):
            section = name
    if section == "":
        return verdict
    # the ID is the last path segment, with any query and trailing slash taken off
    code = text.split("?")[0].rstrip("/").split("/")[-1]
    # isdigit() also accepts digits of other scripts (Arabic-Indic, for one); isascii() keeps 0-9 only
    if not code.isdigit() or not code.isascii():
        return verdict

    def read(connection):
        """Ask the registry whether it holds this ID -> Result bool."""
        return ok_result(registry.code_taken(connection, code))

    known = with_registry(db_path, read)
    standing = shortlinks.code_standing(code, localkey.read_key(localkey.key_path(db_path)), known["ok"] and known["value"])
    if standing == "tagged":
        verdict["line"] = "Made with your key: short link " + code + " (" + section + ")."
    elif standing == "untagged":
        verdict["line"] = ("A short link of yours without a tag (" + section + "): made before tags, or with another "
                           "key.")
    elif standing == "unverified":
        verdict["line"] = "A short link in your registry (" + section + "). Its tag cannot be checked: no key here."
    elif standing == "unknown":
        verdict["line"] = "On your address, but not in this registry, and its tag cannot be checked: no key here."
    else:
        # "foreign": a wrong check digit, or a wrong tag on an ID the registry does not know
        verdict["line"] = ("Not yours: this ID is on your address (" + section + "), but it is not in this registry and "
                           "its tag or check digit is wrong. It may be a sticker over your code.")
        verdict["warning"] = True
    return verdict


def short_note(shown):
    """A short link's section for the window: " (local)", " (nonlocal)", or "" when its address is
    on neither section's base any more.

    `shown` is a registry record with its printed address under "link"."""
    section = shortlinks.section_of(app_settings.LINKS, shown["link"])
    if section == "":
        return ""
    return " (" + section + ")"

# ==== stamp v1 | author=kjFriday | hmac-sha256=7518b9c6c8a1ab332f924631dd55c597ae9484b83c690ea7b07186be83ed66d0 ====
