# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: selftest.py
# About: The quick built-in checks that `python qr_palette.py --selftest` runs.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""The quick built-in checks that `python qr_palette.py --selftest` runs.

qr_palette.main calls selftest() for --selftest; the full suite is in tests/.

A quick pass over the core, on a scratch registry in a temporary folder: colors; making and reading back
codes, with a logo too; robustness; a print sheet; a list; a Wi-Fi code; finding; votes; short links, their
tags, pages, history and publishing; scans; and ECP's MCP server. It prints one "ok" or "FAIL" line per
check under a few headings, then a last line, and returns the exit code: 0 when every check passed, else 1.
It runs on the default settings: --selftest never reads settings.json.

qr_palette.main imports this module only for --selftest, because it takes the version and option_value
from qr_palette.py.

Start reading at selftest(): each check() is one behavior, and its message says what it proves.
"""

import os
import shutil
import tempfile

import app_settings
import ecp
import local_inference
import localkey
import mcp_server
import payloads
import publish
import qr_codec
import sheets
import shortlinks
import swatch
from batches import make_batch
from finding import matches_for_text, search
from making import make_qr
from qr_palette import __version__, option_value
from short_link_ops import (export_redirects, fresh_code, import_scan_file, link_history, retarget_link,
                            schedule_link_change, short_request, tamper_verdict, undo_link_change)
from votes import board, vote_color


def check(condition, message, failures):
    """Print one "ok" or "FAIL" line for a check, and add a failed check's message to `failures`."""
    if condition:
        print("  ok   " + message)
    else:
        print("  FAIL " + message)
        failures.append(message)


def selftest():
    """Run every quick check on a scratch registry in a new temporary folder -> the exit code: 0 when
    every check passed, else 1. Prints as it goes; the folder is removed at the end, whatever happens.

    Steps:
    1. colors: the usable set, the order with no votes, and a color's name.
    2. codes: make, read back and register codes; refuse a light color; robustness; a logo; a print
       sheet; a list; a Wi-Fi code; finding; votes; short links, their tags, history and publishing;
       scans.
    3. ecp and mcp: no query before a model is chosen, loopback only, a plan run on a snapshot, the
       MCP handshake and its tool list, and option_value.
    4. Print the last line and return the exit code.
    """
    failures = []
    folder = tempfile.mkdtemp(prefix="qr_palette_selftest_")
    try:
        print("colors")
        check(len(swatch.usable_colors()) == 118, "118 of the 216 colors are dark enough to scan", failures)
        check(swatch.rank_colors("mixer", [])["value"][0] == "#000000", "no votes ranks in discovery order", failures)
        check(swatch.color_name("#006666") == "Muted teal", "colors have Color Voats' names", failures)

        print("codes")
        db_path = os.path.join(folder, "palette.db")
        made = make_qr(db_path, "https://example.com/selftest", "#3366cc", "M", os.path.join(folder, "a.png"), 4)
        check(made["ok"], "a blue PNG code is made, read back and registered", failures)
        made_svg = make_qr(db_path, "https://example.com/selftest", "#006633", "Q", os.path.join(folder, "a.svg"), 4)
        check(made_svg["ok"], "a green SVG code is made, read back and registered", failures)
        check(not make_qr(db_path, "x", "#ffff00", "M", os.path.join(folder, "b.png"), 4)["ok"],
              "a color too light to scan is refused", failures)
        # upper case fits QR's alphanumeric mode, which has no lower-case letters
        sample = "HTTPS://GO.EXAMPLE.COM/12345678"
        worn = qr_codec.robustness(qr_codec.picture_image(qr_codec.encode_text(sample, "H", 1, -1)["value"], 4,
                                                          "#000000"), sample)
        check(worn["ok"] and worn["value"]["passed"] == 9, "a code's robustness is scored (9 of 10 for this one)",
              failures)
        # a flat gray 16 x 16 picture stands in for a logo; a logo always makes the code level H
        logo = make_qr(db_path, "https://example.com/logo", "#663399", "M", os.path.join(folder, "logo.png"), 4, None,
                       qr_codec.make_image(16, 16, 40))
        check(logo["ok"] and logo["value"]["level"] == "H", "a code with a logo in the middle is level H and reads back",
              failures)
        printed = sheets.print_sheet(db_path, [made["value"]["id"], made_svg["value"]["id"]],
                                     sheets.DEFAULT_SHEETS["layouts"]["A4 poster"], os.path.join(folder, "sheet.pdf"))
        check(printed["ok"] and printed["value"]["pages"] == 2, "codes are printed on a sheet as a PDF", failures)
        # the second row's #ffff00 is too light to scan, so the list skips it and says so
        run = make_batch(db_path, [{"row": 2, "link": "https://example.com/list", "color": "#660099", "label": "x",
                                    "file": "", "problem": ""},
                                   {"row": 3, "link": "https://example.com/list", "color": "#ffff00", "label": "y",
                                    "file": "", "problem": ""}], os.path.join(folder, "run"), "png", "M", 4, "", False,
                         None, "selftest")
        check(run["ok"] and run["value"]["made"] == 1 and run["value"]["skipped"] == 1 and
              os.path.isfile(run["value"]["report"]), "a list makes its codes and reports the row it skipped", failures)
        # the registry keeps the Wi-Fi text with its password masked; scanning the real text still finds it
        wifi = payloads.build("wifi", {"ssid": "Cafe", "password": "selftest-secret"})["value"]
        joined = make_qr(db_path, wifi["text"], "#663399", "M", os.path.join(folder, "wifi.png"), 4, None, None, True)
        found = matches_for_text(db_path, wifi["text"], "")
        check(joined["ok"] and joined["value"]["link"] == wifi["stored"] and found["ok"] and len(found["value"]) == 1,
              "a Wi-Fi code keeps its password out of the registry, and is still found by scanning it", failures)
        found = search(db_path, "color", "blue", False, 20)
        check(found["ok"] and len(found["value"]) == 1 and found["value"][0]["path"] == made["value"]["path"],
              "found again by color, with its path", failures)
        found = search(db_path, "qr_code", "https://example.com/selftest", False, 20)
        check(found["ok"] and len(found["value"]) == 2, "found again by its link", failures)
        check(vote_color(db_path, "#3366cc", 1)["value"] == 1 and board(db_path, "mixer")["value"]["order"][0] == "#3366cc",
              "a Good vote moves the color to the top", failures)
        local = make_qr(db_path, "https://example.com/later", "#006633", "M", os.path.join(folder, "s.png"), 4,
                        short_request(shortlinks.new_code(app_settings.LINKS["id_digits"]), "local"))
        public = make_qr(db_path, "https://example.com/later", "#006633", "M", os.path.join(folder, "t.png"), 4,
                         short_request(shortlinks.new_code(app_settings.LINKS["id_digits"]), "nonlocal"))
        check(local["ok"] and public["ok"] and
              local["value"]["link"].startswith(app_settings.LINKS["local"]["base"]) and
              public["value"]["link"].startswith(app_settings.LINKS["nonlocal"]["base"]) and
              public["value"]["target"] == "https://example.com/later",
              "local and nonlocal short links are printed in the code, each with its destination", failures)
        exported = export_redirects(db_path, os.path.join(folder, "site"), "local")
        check(exported["ok"] and exported["value"]["written"] == 1 and len(exported["value"]["skipped"]) == 1,
              "the local section's redirect page is exported, and only that one", failures)
        code = local["value"]["short_code"]
        retarget_link(db_path, code, "https://example.com/later-still")
        schedule_link_change(db_path, code, "https://example.com/next-year", "2099-01-01")  # stays to come
        # "exampie" (i for l) only looks like the nonlocal base GO.EXAMPLE.COM, so it is called out
        tagged = fresh_code(db_path, 7)
        key = localkey.read_key(localkey.key_path(db_path))
        check(shortlinks.is_valid_code(tagged) and shortlinks.has_valid_tag(tagged, key) and
              tamper_verdict(db_path, local["value"]["link"])["warning"] is False and
              tamper_verdict(db_path, "https://go.exampie.com/1")["warning"],
              "new IDs carry a tag under the local key, and an address that only looks like yours is called out", failures)
        undone = undo_link_change(db_path, code)
        known = link_history(db_path, code)
        check(undone["ok"] and undone["value"] == "https://example.com/later" and known["ok"] and
              len(known["value"]["changes"]) == 2 and len(known["value"]["coming"]) == 1,
              "a short link keeps its history, undoes a change and schedules another", failures)
        outbox = os.path.join(folder, "synced")
        planned = publish.plan_pages(outbox, "folder", [{"code": code, "url": "HTTPS://GO.EXAMPLE.SHOP/" + code,
                                                         "target": "https://example.com/a", "hex": "#006633"}],
                                     "HTTPS://GO.EXAMPLE.SHOP/", {})
        check(planned["ok"] and code + "/index.html" in planned["value"]["added"] and not os.path.exists(outbox),
              "publishing says what would change first, with nothing touched", failures)
        report = os.path.join(folder, "report.csv")
        handle = open(report, "w", encoding="utf-8")
        handle.write("date,utm_content,count\n2026-10-28," + code + "-006633,5\n")
        handle.close()
        import_scan_file(db_path, report)  # twice on purpose: a source's day is replaced, not added to
        imported = import_scan_file(db_path, report)
        shown = search(db_path, "qr_code", code, False, 20, "2026-10-29")  # a fixed today: the 28th is recent
        check(imported["ok"] and shown["ok"] and shown["value"][0]["scans"] == {"total": 5, "recent": 5},
              "scans are imported per short link, and importing again changes nothing", failures)

        print("ecp and mcp")
        # port 1: nothing listens there, so no model can be chosen or asked
        engine = ecp.new_engine(db_path, "http://127.0.0.1:1", 1.0, __version__)
        asked = ecp.query(engine, "blue", "", ecp.new_call("selftest", {}, None))
        check(not asked["ok"] and asked["kind"] == "args_invalid", "no query before a local model is chosen", failures)
        check(not local_inference.parse_endpoint("http://example.com:11434")["ok"], "inference must be on loopback",
              failures)
        snapshot = ecp.read_environment(engine)
        asked_local = ecp.ground(dict(ecp.empty_plan(), section="local"), "my local codes")[0]
        ran = None
        if snapshot["ok"]:
            ran = ecp.run_plan(snapshot["value"], asked_local, swatch.DEFAULT_PRESET, app_settings.LINKS)
        check(ran is not None and len(ran["records"]) == 1 and ran["records"][0]["section"] == "local" and
              ecp.ground(dict(ecp.empty_plan(), section="local"), "every code")[0]["section"] == "",
              "ECP finds the local short links only when the question names the section", failures)
        # the MCP handshake: initialize, then the initialized notification (no id, so no answer), then
        # tools/list
        server = mcp_server.new_server(engine)
        mcp_server.handle(server, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                   "params": {"protocolVersion": "2025-11-25"}})
        mcp_server.handle(server, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        tools = mcp_server.handle(server, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        names = []
        for tool in tools["result"]["tools"]:
            names.append(tool["name"])
        check(names == ["ecp_list_models", "ecp_select_model", "ecp_query"], "ECP's MCP server lists its three tools",
              failures)
        check(option_value(["--db", "x.db"], "--db") == "x.db", "option value", failures)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    print("")
    if len(failures) == 0:
        print("all checks passed")
        return 0
    print(str(len(failures)) + " check(s) failed")
    return 1

# ==== stamp v1 | author=kjFriday | hmac-sha256=3173a3db13f8af4c9c4dea5edad87feff83dcf8e02211c7b0761e461ccbfdb2b ====
