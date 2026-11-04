# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: short_link_ops.py
# About: Short links in the registry: the one a new code prints, where each one goes now and...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Short links in the registry: the one a new code prints, where each one goes now and later, and its pages.

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
    a tag works just the same, so a key that cannot be made never stops a code being made."""
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
    short links to the same destination are separate, since they print different addresses."""
    def plan(connection):
        found = registry.short_link_for(connection, target, color, short["base"])
        if found is not None:
            return ok_result({"code": found["code"], "url": found["url"], "made": True})
        code = short["code"]
        tries = 0
        while not shortlinks.is_valid_code(code) or registry.code_taken(connection, code):
            tries = tries + 1
            if tries > 50:
                return fail("cannot find a free short-link ID; raise id_digits in links.json")
            code = fresh_code(db_path, short["digits"])
        return ok_result({"code": code, "url": shortlinks.short_url(short["base"], code), "made": False})

    return with_registry(db_path, plan)


def retarget_link(db_path, code, link):
    """Send short link `code` to `link` from now on -> Result True. Export the pages to publish it."""
    checked = shortlinks.check_target(link)
    if not checked["ok"]:
        return checked

    def change(connection):
        return registry.retarget(connection, code, checked["value"])

    changed = with_registry(db_path, change)
    if changed["ok"] and not changed["value"]:
        return fail("there is no short link " + code)
    return changed


def undo_link_change(db_path, code):
    """Send short link `code` back where it went before its latest change -> Result its target now."""
    def undo(connection):
        return registry.undo_last_change(connection, code)

    return with_registry(db_path, undo)


def schedule_link_change(db_path, code, link, from_day):
    """Send short link `code` to `link` from `from_day` on -> Result the schedule's id."""
    checked = shortlinks.check_target(link)
    if not checked["ok"]:
        return checked

    def schedule(connection):
        return registry.schedule_change(connection, code, checked["value"], from_day)

    return with_registry(db_path, schedule)


def cancel_link_change(db_path, number):
    def cancel(connection):
        return registry.cancel_scheduled(connection, number)

    return with_registry(db_path, cancel)


def link_history(db_path, code):
    """A short link's past and future -> Result {"changes": [Change], "coming": [Scheduled]}."""
    def read(connection):
        return ok_result({"changes": registry.link_changes(connection, code),
                          "coming": registry.scheduled(connection, code)})

    return with_registry(db_path, read)


def due_link_changes(db_path, today):
    """The scheduled changes whose day has come -> Result [Scheduled]."""
    def read(connection):
        return ok_result(registry.due_changes(connection, today))

    return with_registry(db_path, read)


def apply_due_changes(db_path, today):
    """Make the scheduled changes whose day has come -> Result how many."""
    def apply(connection):
        return registry.apply_due(connection, today)

    return with_registry(db_path, apply)


def import_scan_file(db_path, path):
    """Scan counts from an analytics CSV or a server log into the registry -> Result {"kind", "source",
    "read", "ignored", "days", "scans": how many counted, "unknown": [IDs that are not short links here]}.
    Importing the same file again changes nothing."""
    read = scans.read_file(path)
    if not read["ok"]:
        return read
    value = read["value"]

    def bring(connection):
        return registry.import_scans(connection, value["counts"], value["source"])

    saved = with_registry(db_path, bring)
    if not saved["ok"]:
        return saved
    counted = 0
    for key in value["counts"]:
        if key[0] not in saved["value"]["unknown"]:
            counted = counted + value["counts"][key]
    return ok_result({"kind": value["kind"], "source": value["source"], "read": value["read"],
                      "ignored": value["ignored"], "days": saved["value"]["days"], "scans": counted,
                      "unknown": saved["value"]["unknown"]})


def export_redirects(db_path, folder, section, day=""):
    """Write a redirect page for every short link of `section` ("local" or "nonlocal") into `folder`
    (shortlinks.export_pages), with the destination in force on `day` ("" for today) -> Result. The
    registry is only read, on the read-only rail."""
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
    """The short links as they should be published on `day` ("" for today) -> Result [ShortLink]."""
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
    """What publishing the nonlocal pages would change, with nothing touched -> Result publish.Changes."""
    rows = publish_rows(db_path, day)
    if not rows["ok"]:
        return rows
    target = app_settings.LINKS["nonlocal"]["publish"]
    return publish.plan_pages(target["folder"], target["kind"], rows["value"], app_settings.LINKS["nonlocal"]["base"],
                              app_settings.LINKS["tags"])


def publish_now(db_path, day=""):
    """Publish the nonlocal pages where links.json says -> Result of publish.publish."""
    rows = publish_rows(db_path, day)
    if not rows["ok"]:
        return rows
    target = app_settings.LINKS["nonlocal"]["publish"]
    return publish.publish(target["folder"], target["kind"], rows["value"], app_settings.LINKS["nonlocal"]["base"],
                           app_settings.LINKS["tags"])


def tamper_verdict(db_path, text):
    """What the Read tab says about a scanned link -> {"line": str, "warning": bool}, "" for a link that
    has nothing to do with your addresses. A warning is for an address that only looks like yours, or
    an ID on your address that is not yours. Limits: two tag digits are right by chance 1 time in 100."""
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
    lifted = text.upper()
    section = ""
    for name in shortlinks.SECTIONS:
        if lifted.startswith(app_settings.LINKS[name]["base"]):
            section = name
    if section == "":
        return verdict
    code = text.split("?")[0].rstrip("/").split("/")[-1]
    if not code.isdigit() or not code.isascii():
        return verdict

    def read(connection):
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
        verdict["line"] = ("Not yours: this ID is on your address (" + section + "), but it is not in this registry and "
                           "its tag or check digit is wrong. It may be a sticker over your code.")
        verdict["warning"] = True
    return verdict


def short_note(shown):
    """A short link's section for the window: " (local)", " (nonlocal)", or "" when its address is
    on neither section's base any more."""
    section = shortlinks.section_of(app_settings.LINKS, shown["link"])
    if section == "":
        return ""
    return " (" + section + ")"

# ==== stamp v1 | author=kjFriday | hmac-sha256=7518b9c6c8a1ab332f924631dd55c597ae9484b83c690ea7b07186be83ed66d0 ====
