# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: tests/test_shortlinks.py
# About: Tests for short links: the IDs and their check digit, the base address, destinations...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Tests for short links: IDs and check digits, bases, destinations, templates, tags, pages.

A short link is a base address in capitals plus a numeric ID (random digits, two optional tag digits
cut from an HMAC under the local key, and a Damm check digit). shortlinks.py checks IDs and bases,
cleans destinations, fills link templates, adds tracking tags, reads links.json, exports one redirect
page per short link and serves the local pages from this computer.

What the classes pin:
  1. IdTests: the Damm digit catches every single typo and neighbour swap; tags verify; lookalike
     hosts are caught; bases and local hosts are told apart.
  2. DestinationTests: only http(s) links with a host, made safe to write into HTML.
  3. TemplateAndTagTests: template fields and tracking tags.
  4. LinksFileTests: links.json, its defaults and its warnings.
  5. ExportTests and ServerTests: the redirect pages and the local server, on a free port of 127.0.0.1.

Run with the rest of the suite: python -m unittest discover -s tests, in the program folder.
"""

import http.client
import json
import os
import shutil
import socket
import tempfile
import unittest

import qr_codec
import shortlinks

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the program folder, above tests/


def valid_code(body):
    """A valid ID: `body` with its Damm check digit added."""
    return body + shortlinks.check_digit(body)


def read(path):
    """The whole text of a UTF-8 file."""
    handle = open(path, "r", encoding="utf-8")
    try:
        return handle.read()
    finally:
        handle.close()


class IdTests(unittest.TestCase):
    """IDs, tags, lookalike hosts, and bases."""

    def test_the_damm_check_digit(self):
        """572 gets check digit 4 (the usual worked example of the Damm algorithm); malformed IDs are refused.

        Refused: empty, one digit alone, letters, a space, None, an int rather than text, and an
        Arabic-Indic digit two (U+0662), which Python's isdigit accepts but an ID must not."""
        self.assertEqual(shortlinks.check_digit("572"), "4")
        self.assertTrue(shortlinks.is_valid_code("5724"))
        self.assertFalse(shortlinks.is_valid_code("5723"))
        for bad in ("", "4", "57a4", "57 24", None, 5724, chr(0x0662) + "1"):
            self.assertFalse(shortlinks.is_valid_code(bad), bad)

    def test_every_single_typo_and_neighbour_swap_is_caught(self):
        """For 40 random IDs, every one-digit change and every swap of two different neighbours fails the check.

        This is the Damm algorithm's promise; with random IDs a broken table would soon show."""
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

    def test_tags_verify_and_the_check_digit_still_holds(self):
        """Tagged IDs are 10 digits (7 + 2 tag + 1 check), pass the check digit, and verify under their own key.

        Under another key a tag is right about 1 time in 100, so of 200 IDs about 198 fail; 180 leaves
        room for chance. No key, or an ID too short to hold a tag, never verifies; the tag of the same
        digits is always the same."""
        key = b"k" * 32
        other = b"j" * 32
        for attempt in range(40):
            code = shortlinks.new_code(7, key)
            self.assertEqual(len(code), 10)
            self.assertTrue(shortlinks.is_valid_code(code))
            self.assertTrue(shortlinks.has_valid_tag(code, key))
        wrong = 0
        for attempt in range(200):
            if not shortlinks.has_valid_tag(shortlinks.new_code(7, other), key):
                wrong = wrong + 1
        self.assertGreater(wrong, 180)  # another key's tags pass only by chance, about 1 time in 100
        self.assertFalse(shortlinks.has_valid_tag("5724", None))
        self.assertFalse(shortlinks.has_valid_tag("123", key))
        self.assertEqual(shortlinks.id_tag(key, "1234567"), shortlinks.id_tag(key, "1234567"))

    def test_how_an_id_stands(self):
        """code_standing for each case of tag, key and registry: tagged, untagged, foreign, unverified, unknown.

        The plain ID is swapped for another when it happens to carry a valid tag (the 1 in 100). The
        typo bumps the last digit of a tagged ID, so its check digit is wrong and it is foreign even
        with no key."""
        key = b"k" * 32
        tagged = shortlinks.new_code(7, key)
        body = "1234567"
        plain = body + shortlinks.check_digit(body)
        if shortlinks.has_valid_tag(plain, key):
            plain = "7654321" + shortlinks.check_digit("7654321")  # the 1 in 100
        typo = tagged[:len(tagged) - 1] + str((int(tagged[len(tagged) - 1]) + 1) % 10)
        for code, the_key, known, standing in ((tagged, key, True, "tagged"), (tagged, key, False, "tagged"),
                                               (plain, key, True, "untagged"), (plain, key, False, "foreign"),
                                               (tagged, None, True, "unverified"), (tagged, None, False, "unknown"),
                                               (typo, key, True, "foreign"), (typo, None, False, "foreign")):
            self.assertEqual(shortlinks.code_standing(code, the_key, known), standing, (code, known))

    def test_a_tagged_short_link_is_still_small(self):
        """A tagged short link (33 characters) stays in alphanumeric mode: version 2 at level M, version 3 at level H.

        In alphanumeric mode version 2-M holds 38 characters and version 3-H holds 35 (ISO/IEC 18004
        capacity tables), so the two tag digits cost no version at either level."""
        url = shortlinks.short_url("HTTPS://GO.EXAMPLE.COM/", shortlinks.new_code(7, b"k" * 32))
        self.assertEqual(qr_codec.choose_mode(url), qr_codec.MODE_ALPHANUMERIC)
        self.assertEqual(qr_codec.encode_text(url, "M", 1, -1)["value"]["version"], 2)
        self.assertEqual(qr_codec.encode_text(url, "H", 1, -1)["value"]["version"], 3)

    def test_addresses_that_only_look_like_yours(self):
        """Hosts that imitate GO.EXAMPLE.COM are named; the real host, other hosts and junk give "".

        Imitations: one or two letters off (exampie, CON, exmaple, co, goo), digits for letters (1 for
        l, 0 for o), your host as the start of a longer one, your host before an @ (only a user name),
        Cyrillic o, a and e mixed in, and the same in Punycode (xn--). Not imitations: the host itself
        in any case or with its port, a subdomain of it, unrelated hosts, LOCALHOST (an exact base),
        and text that is no link. A base on an IP address is never compared."""
        bases = ("HTTP://LOCALHOST:8000/", "HTTPS://GO.EXAMPLE.COM/")
        for url in ("https://go.exampie.com/12345678", "HTTPS://GO.EXAMPLE.CON/1", "https://go.exmaple.com/1",
                    "https://go.example.co/1", "https://goo.example.com/1", "https://go.examp1e.com/1",
                    "https://g0.example.com/1", "https://go.example.com.example.net/1",
                    "https://go.example.com@example.net/1", "https://GO.EXAMPLE.COM.:443@example.net/1",
                    "https://g" + chr(0x043E) + ".example.com/1", "https://g" + chr(0x043E) + ".ex" + chr(0x0430) + "mple.com/1",
                    "https://g" + chr(0x043E) + "." + chr(0x0435) + "x" + chr(0x0430) + "mpl" + chr(0x0435) + ".c" + chr(0x043E) + "m/1",
                    "https://xn--g-0tb.example.com/1"):
            self.assertEqual(shortlinks.lookalike(url, bases), "GO.EXAMPLE.COM", url)
        for url in ("https://go.example.com/12345678", "HTTPS://GO.EXAMPLE.COM/1", "https://go.example.com:443/1",
                    "https://www.go.example.com/1", "https://shop.example.net/1", "https://example.org/",
                    "http://localhost:8000/1", "not a link", "https://"):
            self.assertEqual(shortlinks.lookalike(url, bases), "", url)
        self.assertEqual(shortlinks.lookalike("http://192.168.1.21:8000/1", ("HTTP://192.168.1.20:8000/",)), "")

    def test_letters_apart(self):
        """letters_apart counts changes, insertions, deletions and neighbour swaps (optimal string alignment distance).

        "ABCD" to "BADC" is two swaps, and "EXAMPLE" to "EXMAPLE" one."""
        for first, second, apart in (("ABC", "ABC", 0), ("ABC", "ABD", 1), ("ABC", "AB", 1), ("ABC", "ACB", 1),
                                     ("ABCD", "BADC", 2), ("", "AB", 2), ("EXAMPLE", "EXMAPLE", 1)):
            self.assertEqual(shortlinks.letters_apart(first, second), apart, (first, second))

    def test_short_links_fit_qr_alphanumeric_mode(self):
        """An untagged short link is alphanumeric, fits version 2-M, and its caption and host drop the scheme."""
        url = shortlinks.short_url("HTTPS://GO.EXAMPLE.COM/", shortlinks.new_code(7))
        self.assertEqual(qr_codec.choose_mode(url), qr_codec.MODE_ALPHANUMERIC)
        self.assertEqual(qr_codec.encode_text(url, "M", 1, -1)["value"]["version"], 2)
        self.assertEqual(shortlinks.caption(url), url[len("HTTPS://"):])
        self.assertEqual(shortlinks.host_of(url), "GO.EXAMPLE.COM")

    def test_the_base(self):
        """A base is http(s), all capitals, with an optional port and path, ending in /; example.com hosts are placeholders.

        Refused: lower case (it would leave alphanumeric mode), no final slash, a lower-case path,
        FTP, a space, empty text and None."""
        for good in ("HTTPS://GO.EXAMPLE.COM/", "HTTP://EXAMPLE.ORG/Q/", "HTTPS://A-B.EXAMPLE.NET:8443/X-1/"):
            self.assertEqual(shortlinks.check_base(good, "nonlocal"), "", good)
            self.assertEqual(shortlinks.check_base(good, "local"), "", good)
        for bad in ("https://go.example.com/", "HTTPS://GO.EXAMPLE.COM", "HTTPS://GO.EXAMPLE.COM/q/",
                    "FTP://GO.EXAMPLE.COM/", "HTTPS://GO.EXAMPLE.COM/A B/", "", None):
            self.assertNotEqual(shortlinks.check_base(bad, "local"), "", bad)
        self.assertTrue(shortlinks.is_placeholder("HTTPS://GO.EXAMPLE.COM/"))
        self.assertFalse(shortlinks.is_placeholder("HTTPS://GO.SHOP.TEST/"))

    def test_local_addresses_belong_in_the_local_section(self):
        """LOCALHOST, private and loopback IPs, .LOCAL and .HOME.ARPA names and dotless names are local only; public hosts are not local.

        A local address is refused as a nonlocal base, which must be reachable from anywhere."""
        for local in ("HTTP://LOCALHOST:8000/", "HTTP://192.168.1.20:8000/", "HTTP://10.0.0.5/", "HTTP://127.0.0.1:8000/",
                      "HTTP://MY-PC.LOCAL/", "HTTP://PRINTER.HOME.ARPA/", "HTTP://NAS/"):
            self.assertEqual(shortlinks.check_base(local, "local"), "", local)
            self.assertIn("internet address", shortlinks.check_base(local, "nonlocal"), local)
            self.assertTrue(shortlinks.is_local_host(shortlinks.host_of(local)), local)
        for public in ("GO.EXAMPLE.COM", "8.8.4.4", "SHOP.EXAMPLE.NET:8443"):
            self.assertFalse(shortlinks.is_local_host(public), public)

    def test_which_section_an_address_is_in(self):
        """section_of tells local from nonlocal by base; an address on neither base (an old one) gives ""."""
        links = shortlinks.DEFAULT_LINKS
        self.assertEqual(shortlinks.section_of(links, "HTTP://LOCALHOST:8000/12345674"), "local")
        self.assertEqual(shortlinks.section_of(links, "HTTPS://GO.EXAMPLE.COM/12345674"), "nonlocal")
        self.assertEqual(shortlinks.section_of(links, "HTTPS://OLD.EXAMPLE.NET/12345674"), "")


class DestinationTests(unittest.TestCase):
    """check_target: where a short link may send people."""

    def test_only_web_links_with_a_host(self):
        """Surrounding spaces are trimmed; anything but an http(s) link with a host, no spaces, and at most 2048 characters is refused.

        Refused: empty, file:, data:, ftp:, no host, no scheme, a space in the host, 2070 characters,
        and mailto:."""
        self.assertEqual(shortlinks.check_target("  https://shop.example.com/hours ")["value"],
                         "https://shop.example.com/hours")
        for bad in ("", "file:///C:/notes.txt", "data:text/plain,hello", "ftp://example.com/x", "https://",
                    "shop.example.com", "https://exa mple.com", "https://example.com/" + "x" * 2050,
                    "mailto:shop@example.com"):
            self.assertFalse(shortlinks.check_target(bad)["ok"], bad)

    def test_quotes_and_brackets_cannot_close_an_attribute(self):
        """" ' < > and ` are percent-encoded, so a destination written into a redirect page cannot end its attribute."""
        checked = shortlinks.check_target("https://example.com/a\"b'c<d>e`f")
        self.assertEqual(checked["value"], "https://example.com/a%22b%27c%3Cd%3Ee%60f")

    def test_control_and_direction_characters_are_dropped(self):
        """A right-to-left override (U+202E) and a bell (7) are taken out of a destination."""
        checked = shortlinks.check_target("https://example.com/a" + chr(0x202E) + "b" + chr(7))
        self.assertEqual(checked["value"], "https://example.com/ab")


class TemplateAndTagTests(unittest.TestCase):
    """Link templates and tracking tags."""

    def test_fields_and_filling(self):
        """A template lists its {fields} in order; each value is percent-encoded whole (a space, a /), and a missing field is named."""
        pattern = "https://shop.example.com/p/{item}?size={size}"
        self.assertEqual(shortlinks.template_fields(pattern), ["item", "size"])
        filled = shortlinks.fill_template(pattern, {"item": "blue mug", "size": "M/L"})
        self.assertEqual(filled["value"], "https://shop.example.com/p/blue%20mug?size=M%2FL")
        self.assertIn("size", shortlinks.fill_template(pattern, {"item": "x"})["error"])

    def test_tags_are_added_but_never_replace_the_links_own(self):
        """Tags go after the link's own query and before its #fragment; a tag the link already has, or an empty one, is not added.

        {id} becomes the ID and {hex} the color without its #."""
        tags = {"utm_source": "qr", "utm_content": "{id}-{hex}", "empty": ""}
        self.assertEqual(shortlinks.tagged("https://example.com/a?utm_source=mine&x=1#top", tags, "12345678", "#3366cc"),
                         "https://example.com/a?utm_source=mine&x=1&utm_content=12345678-3366cc#top")
        self.assertEqual(shortlinks.tagged("https://example.com/a", {}, "1", "#000000"), "https://example.com/a")
        self.assertEqual(shortlinks.tagged("https://example.com/a", {"ref": "qr"}, "1", "#000000"),
                         "https://example.com/a?ref=qr")


class LinksFileTests(unittest.TestCase):
    """load_links on links.json files written into a temporary folder."""

    def setUp(self):
        """Make the folder and name links.json in it."""
        self.folder = tempfile.mkdtemp(prefix="qr_palette_links_")
        self.path = os.path.join(self.folder, "links.json")

    def tearDown(self):
        """Remove the folder."""
        shutil.rmtree(self.folder, ignore_errors=True)

    def write(self, text):
        """Write `text` as the test's links.json."""
        handle = open(self.path, "w", encoding="utf-8")
        handle.write(text)
        handle.close()

    def test_the_shipped_file_shows_the_defaults(self):
        """The links.json beside the program is exactly links_text(DEFAULT_LINKS) and loads without warnings."""
        self.assertEqual(read(os.path.join(HERE, "links.json")), shortlinks.links_text(shortlinks.DEFAULT_LINKS))
        self.assertEqual(shortlinks.load_links(os.path.join(HERE, "links.json"))["warnings"], [])

    def test_good_values_are_used(self):
        """Valid bases, ID length, tags, switch and templates are used as given, and ~ in export folders is expanded."""
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
        """Nine unusable values give nine warnings and keep their defaults; bad tags and templates are dropped one by one.

        The nine: a lower-case local base, an export folder that is a number, a local address as the
        nonlocal base, 3 ID digits (4 to 12 allowed), "yes" for a bool, a tag name with a space, a tag
        value that is not text, an ftp template and a template with a stray brace. A section that is
        not an object is one warning more on its own."""
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
        self.assertIs(links["tag_ids"], True)
        self.assertEqual((links["tags"], links["templates"]), ({}, {}))
        self.write(json.dumps({"local": "here"}))
        self.assertEqual(len(shortlinks.load_links(self.path)["warnings"]), 1)

    def test_a_broken_file_means_the_defaults(self):
        """A file that is not valid JSON means every default, with one warning."""
        self.write("[1,")
        loaded = shortlinks.load_links(self.path)
        self.assertEqual(len(loaded["warnings"]), 1)
        self.assertEqual(loaded["links"], shortlinks.DEFAULT_LINKS)


class ExportTests(unittest.TestCase):
    """export_pages: redirect pages written into a temporary folder."""

    def setUp(self):
        """Make the folder and three valid IDs."""
        self.folder = tempfile.mkdtemp(prefix="qr_palette_site_")
        self.first = valid_code("1234567")
        self.second = valid_code("7654321")
        self.other = valid_code("5555555")

    def tearDown(self):
        """Remove the folder."""
        shutil.rmtree(self.folder, ignore_errors=True)

    def rows(self):
        """Three ShortLink rows: two on the nonlocal base (one under a Q/ folder, its target holding quotes) and one on an old host."""
        return [{"code": self.first, "url": "HTTPS://GO.EXAMPLE.COM/" + self.first,
                 "target": "https://shop.example.com/hours", "hex": "#3366cc"},
                {"code": self.second, "url": "HTTPS://GO.EXAMPLE.COM/Q/" + self.second,
                 "target": "https://example.com/a?b=1&c=\"2\"", "hex": "#006633"},
                {"code": self.other, "url": "HTTPS://OLD.EXAMPLE.NET/" + self.other,
                 "target": "https://example.com/old", "hex": "#cc0000"}]

    def export(self, rows):
        """Export `rows` for the default nonlocal base with the default tracking tags -> export_pages' Result."""
        return shortlinks.export_pages(self.folder, rows, shortlinks.DEFAULT_LINKS["nonlocal"]["base"],
                                       shortlinks.DEFAULT_LINKS["tags"])

    def test_one_page_per_short_link_on_the_base_host(self):
        """Each short link on the base's host gets ID/index.html with a tagged, escaped meta refresh; the old host's is skipped.

        In HTML the & between tags is written &amp;; the quotes in the second target arrive as %22.
        index.html, 404.html and robots.txt keep search engines out."""
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
        """A ".." in the address and a file: destination are skipped, so only the three fixed files are written; no folder fails."""
        rows = [{"code": "1", "url": "HTTPS://GO.EXAMPLE.COM/../X", "target": "https://example.com/", "hex": "#000000"},
                {"code": self.first, "url": "HTTPS://GO.EXAMPLE.COM/" + self.first, "target": "file:///C:/x",
                 "hex": "#000000"}]
        exported = self.export(rows)
        self.assertEqual((exported["value"]["written"], exported["value"]["skipped"]), (0, ["1", self.first]))
        self.assertEqual(sorted(os.listdir(self.folder)), ["404.html", "index.html", "robots.txt"])
        self.assertFalse(shortlinks.export_pages("", rows, "HTTPS://GO.EXAMPLE.COM/", {})["ok"])

    def test_each_section_exports_its_own_pages(self):
        """Exporting for the local base writes only the local short link and skips the three nonlocal ones; with no tags the target is unchanged."""
        local = valid_code("2222222")
        rows = self.rows() + [{"code": local, "url": "HTTP://LOCALHOST:8000/" + local,
                               "target": "https://example.com/try", "hex": "#000000"}]
        exported = shortlinks.export_pages(self.folder, rows, shortlinks.DEFAULT_LINKS["local"]["base"], {})
        self.assertEqual(exported["value"]["written"], 1)
        self.assertEqual(len(exported["value"]["skipped"]), 3)
        self.assertIn("url=https://example.com/try\"", read(os.path.join(self.folder, local, "index.html")))


class ServerTests(unittest.TestCase):
    """start_server, serve_address and stop_server, talking HTTP to 127.0.0.1."""

    def setUp(self):
        """Export one local page for a base on a free port, chosen by binding port 0 and closing again.

        Another program could take the port in between; that race is accepted for a test."""
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
        """Stop every server started, then remove the folder."""
        for running in self.running:
            shortlinks.stop_server(running)
        shutil.rmtree(self.folder, ignore_errors=True)

    def start(self):
        """Start the server on this computer only (network not allowed) -> the Server record."""
        started = shortlinks.start_server(self.folder, self.base, False)
        self.assertTrue(started["ok"], started["error"])
        self.running.append(started["value"])
        return started["value"]

    def get(self, path, method="GET"):
        """Send one request to the test port -> (status, body)."""
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request(method, path)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_the_pages_are_served_on_this_computer_only(self):
        """A LOCALHOST base binds 127.0.0.1 and serves the page; other requests get what a static host answers.

        /ID without a slash is redirected to the folder (301); an unknown ID and a climb out of the
        folder get the 404 page; HEAD gets headers only; POST is not implemented (501)."""
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
        """serve_address binds loopback bases at once, network ones only when allowed (a name on every interface), and http only.

        Port 80 is http's default when the base names none."""
        self.assertEqual(shortlinks.serve_address("HTTP://LOCALHOST:8000/", False)["value"], ("127.0.0.1", 8000))
        self.assertEqual(shortlinks.serve_address("HTTP://127.0.0.1/", False)["value"], ("127.0.0.1", 80))
        self.assertIn("network", shortlinks.serve_address("HTTP://192.168.1.20:8000/", False)["error"])
        self.assertEqual(shortlinks.serve_address("HTTP://192.168.1.20:8000/", True)["value"], ("192.168.1.20", 8000))
        self.assertEqual(shortlinks.serve_address("HTTP://MY-PC.LOCAL:8000/", True)["value"], ("0.0.0.0", 8000))
        self.assertIn("http://", shortlinks.serve_address("HTTPS://LOCALHOST:8443/", False)["error"])

    def test_nothing_to_serve_and_a_port_in_use(self):
        """A folder with nothing exported is refused, and a second server on a port already served cannot start.

        Should the second start succeed anyway, it is kept in self.running so tearDown stops it."""
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

# ==== stamp v1 | author=kjFriday | hmac-sha256=f28942f2401a19de8b3adbc8034551ab04f58bafd91542e7953ac050ba2bcad0 ====
