# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: qr_color_registry/test_shortlinks.py
# About: Tests for short links: the IDs and their check digit, the base address, destinations...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""Tests for short links: the IDs and their check digit, the base address, destinations, templates,
tags, links.json and the exported redirect pages."""

import http.client
import json
import os
import shutil
import socket
import tempfile
import unittest

import qr_codec
import shortlinks

HERE = os.path.dirname(os.path.abspath(__file__))


def valid_code(body):
    return body + shortlinks.check_digit(body)


def read(path):
    handle = open(path, "r", encoding="utf-8")
    try:
        return handle.read()
    finally:
        handle.close()


class IdTests(unittest.TestCase):
    def test_the_damm_check_digit(self):
        self.assertEqual(shortlinks.check_digit("572"), "4")
        self.assertTrue(shortlinks.is_valid_code("5724"))
        self.assertFalse(shortlinks.is_valid_code("5723"))
        for bad in ("", "4", "57a4", "57 24", None, 5724, chr(0x0662) + "1"):
            self.assertFalse(shortlinks.is_valid_code(bad), bad)

    def test_every_single_typo_and_neighbour_swap_is_caught(self):
        for attempt in range(40):
            code = shortlinks.new_code(7)
            self.assertEqual(len(code), 8)
            self.assertTrue(shortlinks.is_valid_code(code))
            for place in range(len(code)):
                for digit in "0123456789":
                    if digit != code[place]:
                        typo = code[:place] + digit + code[place + 1:]
                        self.assertFalse(shortlinks.is_valid_code(typo), typo)
            for place in range(len(code) - 1):
                if code[place] != code[place + 1]:
                    swapped = code[:place] + code[place + 1] + code[place] + code[place + 2:]
                    self.assertFalse(shortlinks.is_valid_code(swapped), swapped)

    def test_short_links_fit_qr_alphanumeric_mode(self):
        url = shortlinks.short_url("HTTPS://GO.EXAMPLE.COM/", shortlinks.new_code(7))
        self.assertEqual(qr_codec.choose_mode(url), qr_codec.MODE_ALPHANUMERIC)
        self.assertEqual(qr_codec.encode_text(url, "M", 1, -1)["value"]["version"], 2)
        self.assertEqual(shortlinks.caption(url), url[len("HTTPS://"):])
        self.assertEqual(shortlinks.host_of(url), "GO.EXAMPLE.COM")

    def test_the_base(self):
        for good in ("HTTPS://GO.EXAMPLE.COM/", "HTTP://EXAMPLE.ORG/Q/", "HTTPS://A-B.EXAMPLE.NET:8443/X-1/"):
            self.assertEqual(shortlinks.check_base(good, "nonlocal"), "", good)
            self.assertEqual(shortlinks.check_base(good, "local"), "", good)
        for bad in ("https://go.example.com/", "HTTPS://GO.EXAMPLE.COM", "HTTPS://GO.EXAMPLE.COM/q/",
                    "FTP://GO.EXAMPLE.COM/", "HTTPS://GO.EXAMPLE.COM/A B/", "", None):
            self.assertNotEqual(shortlinks.check_base(bad, "local"), "", bad)
        self.assertTrue(shortlinks.is_placeholder("HTTPS://GO.EXAMPLE.COM/"))
        self.assertFalse(shortlinks.is_placeholder("HTTPS://GO.SHOP.TEST/"))

    def test_local_addresses_belong_in_the_local_section(self):
        for local in ("HTTP://LOCALHOST:8000/", "HTTP://192.168.1.20:8000/", "HTTP://10.0.0.5/", "HTTP://127.0.0.1:8000/",
                      "HTTP://MY-PC.LOCAL/", "HTTP://PRINTER.HOME.ARPA/", "HTTP://NAS/"):
            self.assertEqual(shortlinks.check_base(local, "local"), "", local)
            self.assertIn("internet address", shortlinks.check_base(local, "nonlocal"), local)
            self.assertTrue(shortlinks.is_local_host(shortlinks.host_of(local)), local)
        for public in ("GO.EXAMPLE.COM", "8.8.4.4", "SHOP.EXAMPLE.NET:8443"):
            self.assertFalse(shortlinks.is_local_host(public), public)

    def test_which_section_an_address_is_in(self):
        links = shortlinks.DEFAULT_LINKS
        self.assertEqual(shortlinks.section_of(links, "HTTP://LOCALHOST:8000/12345674"), "local")
        self.assertEqual(shortlinks.section_of(links, "HTTPS://GO.EXAMPLE.COM/12345674"), "nonlocal")
        self.assertEqual(shortlinks.section_of(links, "HTTPS://OLD.EXAMPLE.NET/12345674"), "")


class DestinationTests(unittest.TestCase):
    def test_only_web_links_with_a_host(self):
        self.assertEqual(shortlinks.check_target("  https://shop.example.com/hours ")["value"],
                         "https://shop.example.com/hours")
        for bad in ("", "file:///C:/notes.txt", "data:text/plain,hello", "ftp://example.com/x", "https://",
                    "shop.example.com", "https://exa mple.com", "https://example.com/" + "x" * 2050,
                    "mailto:shop@example.com"):
            self.assertFalse(shortlinks.check_target(bad)["ok"], bad)

    def test_quotes_and_brackets_cannot_close_an_attribute(self):
        checked = shortlinks.check_target("https://example.com/a\"b'c<d>e`f")
        self.assertEqual(checked["value"], "https://example.com/a%22b%27c%3Cd%3Ee%60f")

    def test_control_and_direction_characters_are_dropped(self):
        checked = shortlinks.check_target("https://example.com/a" + chr(0x202E) + "b" + chr(7))
        self.assertEqual(checked["value"], "https://example.com/ab")


class TemplateAndTagTests(unittest.TestCase):
    def test_fields_and_filling(self):
        pattern = "https://shop.example.com/p/{item}?size={size}"
        self.assertEqual(shortlinks.template_fields(pattern), ["item", "size"])
        filled = shortlinks.fill_template(pattern, {"item": "blue mug", "size": "M/L"})
        self.assertEqual(filled["value"], "https://shop.example.com/p/blue%20mug?size=M%2FL")
        self.assertIn("size", shortlinks.fill_template(pattern, {"item": "x"})["error"])

    def test_tags_are_added_but_never_replace_the_links_own(self):
        tags = {"utm_source": "qr", "utm_content": "{id}-{hex}", "empty": ""}
        self.assertEqual(shortlinks.tagged("https://example.com/a?utm_source=mine&x=1#top", tags, "12345678", "#3366cc"),
                         "https://example.com/a?utm_source=mine&x=1&utm_content=12345678-3366cc#top")
        self.assertEqual(shortlinks.tagged("https://example.com/a", {}, "1", "#000000"), "https://example.com/a")
        self.assertEqual(shortlinks.tagged("https://example.com/a", {"ref": "qr"}, "1", "#000000"),
                         "https://example.com/a?ref=qr")


class LinksFileTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="qr_palette_links_")
        self.path = os.path.join(self.folder, "links.json")

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def write(self, text):
        handle = open(self.path, "w", encoding="utf-8")
        handle.write(text)
        handle.close()

    def test_the_shipped_file_shows_the_defaults(self):
        self.assertEqual(read(os.path.join(HERE, "links.json")), shortlinks.links_text(shortlinks.DEFAULT_LINKS))
        self.assertEqual(shortlinks.load_links(os.path.join(HERE, "links.json"))["warnings"], [])

    def test_good_values_are_used(self):
        self.write(json.dumps({"local": {"base": "HTTP://192.168.1.20:8000/", "export_folder": os.path.join("~", "lan")},
                               "nonlocal": {"base": "HTTPS://GO.SHOP.TEST/", "export_folder": os.path.join("~", "site")},
                               "id_digits": 9, "tags": {}, "short_by_default": True,
                               "templates": {"menu": "https://www.example.com/menu/{day}"}}))
        loaded = shortlinks.load_links(self.path)
        self.assertEqual(loaded["warnings"], [])
        links = loaded["links"]
        self.assertEqual((links["local"]["base"], links["nonlocal"]["base"]),
                         ("HTTP://192.168.1.20:8000/", "HTTPS://GO.SHOP.TEST/"))
        self.assertEqual((links["id_digits"], links["tags"], links["short_by_default"]), (9, {}, True))
        self.assertEqual(links["templates"], {"menu": "https://www.example.com/menu/{day}"})
        self.assertEqual(links["nonlocal"]["export_folder"], os.path.join(os.path.expanduser("~"), "site"))
        self.assertEqual(links["local"]["export_folder"], os.path.join(os.path.expanduser("~"), "lan"))

    def test_values_that_cannot_be_used_keep_their_defaults(self):
        self.write(json.dumps({"local": {"base": "http://localhost/", "export_folder": 5},
                               "nonlocal": {"base": "HTTP://LOCALHOST:8000/"}, "id_digits": 3,
                               "short_by_default": "yes", "tags": {"bad name": "x", "ok": 1},
                               "templates": {"other": "ftp://x.example/{a}", "braces": "https://x.example/{a}}"}}))
        loaded = shortlinks.load_links(self.path)
        self.assertEqual(len(loaded["warnings"]), 9)
        links = loaded["links"]
        self.assertEqual((links["local"]["base"], links["nonlocal"]["base"], links["local"]["export_folder"]),
                         ("HTTP://LOCALHOST:8000/", "HTTPS://GO.EXAMPLE.COM/", ""))
        self.assertEqual((links["id_digits"], links["short_by_default"]), (7, False))
        self.assertEqual((links["tags"], links["templates"]), ({}, {}))
        self.write(json.dumps({"local": "here"}))
        self.assertEqual(len(shortlinks.load_links(self.path)["warnings"]), 1)

    def test_a_broken_file_means_the_defaults(self):
        self.write("[1,")
        loaded = shortlinks.load_links(self.path)
        self.assertEqual(len(loaded["warnings"]), 1)
        self.assertEqual(loaded["links"], shortlinks.DEFAULT_LINKS)


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="qr_palette_site_")
        self.first = valid_code("1234567")
        self.second = valid_code("7654321")
        self.other = valid_code("5555555")

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def rows(self):
        return [{"code": self.first, "url": "HTTPS://GO.EXAMPLE.COM/" + self.first,
                 "target": "https://shop.example.com/hours", "hex": "#3366cc"},
                {"code": self.second, "url": "HTTPS://GO.EXAMPLE.COM/Q/" + self.second,
                 "target": "https://example.com/a?b=1&c=\"2\"", "hex": "#006633"},
                {"code": self.other, "url": "HTTPS://OLD.EXAMPLE.NET/" + self.other,
                 "target": "https://example.com/old", "hex": "#cc0000"}]

    def export(self, rows):
        return shortlinks.export_pages(self.folder, rows, shortlinks.DEFAULT_LINKS["nonlocal"]["base"],
                                       shortlinks.DEFAULT_LINKS["tags"])

    def test_one_page_per_short_link_on_the_base_host(self):
        exported = self.export(self.rows())
        self.assertTrue(exported["ok"], exported["error"])
        self.assertEqual((exported["value"]["written"], exported["value"]["skipped"]), (2, [self.other]))
        page = read(os.path.join(self.folder, self.first, "index.html"))
        self.assertIn('content="0; url=https://shop.example.com/hours?utm_source=qr&amp;utm_medium=print&amp;'
                      'utm_content=' + self.first + '-3366cc"', page)
        self.assertIn('<meta name="robots" content="noindex">', page)
        second = read(os.path.join(self.folder, "Q", self.second, "index.html"))
        self.assertIn("c=%222%22", second)
        self.assertNotIn('"2"', second)
        self.assertFalse(os.path.exists(os.path.join(self.folder, self.other)))
        for name in ("index.html", "404.html"):
            self.assertIn("noindex", read(os.path.join(self.folder, name)))
        self.assertEqual(read(os.path.join(self.folder, "robots.txt")), "User-agent: *\nDisallow: /\n")

    def test_unsafe_paths_and_bad_destinations_are_skipped(self):
        rows = [{"code": "1", "url": "HTTPS://GO.EXAMPLE.COM/../X", "target": "https://example.com/", "hex": "#000000"},
                {"code": self.first, "url": "HTTPS://GO.EXAMPLE.COM/" + self.first, "target": "file:///C:/x",
                 "hex": "#000000"}]
        exported = self.export(rows)
        self.assertEqual((exported["value"]["written"], exported["value"]["skipped"]), (0, ["1", self.first]))
        self.assertEqual(sorted(os.listdir(self.folder)), ["404.html", "index.html", "robots.txt"])
        self.assertFalse(shortlinks.export_pages("", rows, "HTTPS://GO.EXAMPLE.COM/", {})["ok"])

    def test_each_section_exports_its_own_pages(self):
        local = valid_code("2222222")
        rows = self.rows() + [{"code": local, "url": "HTTP://LOCALHOST:8000/" + local,
                               "target": "https://example.com/try", "hex": "#000000"}]
        exported = shortlinks.export_pages(self.folder, rows, shortlinks.DEFAULT_LINKS["local"]["base"], {})
        self.assertEqual(exported["value"]["written"], 1)
        self.assertEqual(len(exported["value"]["skipped"]), 3)
        self.assertIn("url=https://example.com/try\"", read(os.path.join(self.folder, local, "index.html")))


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="qr_palette_serve_")
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        self.port = probe.getsockname()[1]
        probe.close()
        self.base = "HTTP://LOCALHOST:" + str(self.port) + "/"
        self.code = valid_code("1234567")
        shortlinks.export_pages(self.folder, [{"code": self.code, "url": self.base + self.code,
                                               "target": "https://example.com/try", "hex": "#000000"}], self.base, {})
        self.running = []

    def tearDown(self):
        for running in self.running:
            shortlinks.stop_server(running)
        shutil.rmtree(self.folder, ignore_errors=True)

    def start(self):
        started = shortlinks.start_server(self.folder, self.base, False)
        self.assertTrue(started["ok"], started["error"])
        self.running.append(started["value"])
        return started["value"]

    def get(self, path, method="GET"):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request(method, path)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_the_pages_are_served_on_this_computer_only(self):
        self.assertEqual(self.start()["address"], "127.0.0.1")
        status, body = self.get("/" + self.code + "/")
        self.assertEqual(status, 200)
        self.assertIn(b"url=https://example.com/try", body)
        self.assertEqual(self.get("/" + self.code)[0], 301)  # on to the folder, as static hosts do
        status, body = self.get("/0000000000/")
        self.assertEqual(status, 404)
        self.assertIn(b"This code is not known", body)
        self.assertEqual(self.get("/../../../windows/win.ini")[0], 404)
        self.assertEqual(self.get("/" + self.code + "/", "HEAD"), (200, b""))
        self.assertEqual(self.get("/" + self.code + "/", "POST")[0], 501)

    def test_where_the_pages_are_served(self):
        self.assertEqual(shortlinks.serve_address("HTTP://LOCALHOST:8000/", False)["value"], ("127.0.0.1", 8000))
        self.assertEqual(shortlinks.serve_address("HTTP://127.0.0.1/", False)["value"], ("127.0.0.1", 80))
        self.assertIn("network", shortlinks.serve_address("HTTP://192.168.1.20:8000/", False)["error"])
        self.assertEqual(shortlinks.serve_address("HTTP://192.168.1.20:8000/", True)["value"], ("192.168.1.20", 8000))
        self.assertEqual(shortlinks.serve_address("HTTP://MY-PC.LOCAL:8000/", True)["value"], ("0.0.0.0", 8000))
        self.assertIn("http://", shortlinks.serve_address("HTTPS://LOCALHOST:8443/", False)["error"])

    def test_nothing_to_serve_and_a_port_in_use(self):
        empty = tempfile.mkdtemp(prefix="qr_palette_serve_empty_")
        try:
            self.assertIn("export", shortlinks.start_server(empty, self.base, False)["error"])
        finally:
            shutil.rmtree(empty, ignore_errors=True)
        self.start()
        again = shortlinks.start_server(self.folder, self.base, False)
        if again["ok"]:
            self.running.append(again["value"])
        self.assertFalse(again["ok"])
        self.assertIn("cannot serve", again["error"])


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=77a219dd37117453feaa7c8b8500a033a01bd3d756d675283847a3ae72bd8343 ====
