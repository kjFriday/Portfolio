# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: shortlinks.py
# About: QR Palette short links: checked IDs, links.json, redirect pages and a local page server.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""QR Palette short links: checked IDs, links.json, redirect pages and a local page server.

A short link is a short address printed in a QR code, pointing at a destination that can change later
without reprinting the code. It is the base address plus an ID, for example HTTPS://GO.EXAMPLE.COM/73491205
(seven random digits and a check digit; with tags on, two tag digits sit before the check digit):
  * The ID is random digits, two tag digits and one Damm check digit, so a mistyped ID is caught.
    Digits cannot be misread as letters, and they have no case: static web hosts treat /ABC and /abc as
    different pages, so a typed fallback with letters breaks when someone types it in lower case.
  * The tag is cut from a keyed hash of the random digits (localkey.py), so the Read tab can tell your
    printed codes from a sticker put over them. Two digits are right by chance 1 time in 100: this
    catches casual swaps, and is no cryptographic guarantee. IDs without a tag stay valid.
  * The base is in capitals, so the whole address fits QR's alphanumeric mode: a smaller code, or
    more error correction at the same size.
  * The registry keeps ID -> destination. export_pages() writes one small redirect page per ID into
    a folder that any static web host can serve; changing a destination means exporting again.
  * Tracking tags are added to the destination when the pages are exported, never printed in a code.
links.json has two sections of short links, each with its own base and export folder:
  local     works on this computer or your own network, for trying codes before you have a domain
            (serve the exported folder from this computer)
  nonlocal  an internet address on a domain of your own, for codes you print for everyone
The window switches between them; which one is in use is remembered in settings.json (links.use).
links.json also holds the ID length, the tags and the link templates, shared by both sections.

Records
  Result     {"ok": bool, "error": str, "value": any}
  Links      {"about", "local": Section, "nonlocal": Section, "id_digits", "tag_ids", "short_by_default",
              "tags": {name: value}, "templates": {name: pattern}}           links.json, checked
  Section    {"about", "base", "export_folder"}; nonlocal also has "publish": {"kind": "" | "git" | "folder",
             "folder"}, where File > Publish nonlocal pages... writes them (publish.py)
  ShortLink  {"code", "url", "target", "hex", ...}               one short link from the registry
  Server     {"server", "thread", "address", "port", "folder", "base"}    the local pages, served

start_server() serves exported local pages from this computer, so local short links can be tried at
once; it binds to this computer alone unless the local base is a network address and the person allows
that.

Callers: short_link_ops.py (IDs, targets, pages, the tamper verdict), app_settings.py (load_links at
start), making.py, sheets.py and the gui tabs (captions, placeholders, templates, the local server),
ecp.py and registry_export.py (sections), scans.py, publish.py and the tests. This module calls localkey.py for the tag HMAC and textsafe.py to clean typed text; it never
touches the registry itself.

The sections below, in order: IDs (Damm check digit and tag), addresses that only look like yours
(homoglyphs and edit distance), bases and hosts, destinations with templates and tracking tags,
links.json, redirect pages, and serving the local pages. Start reading at new_code() and export_pages().
"""

import html
import http.server
import ipaddress
import json
import os
import re
import secrets
import threading
import urllib.parse

import localkey
import textsafe

# The Damm algorithm's table (H. Michael Damm, 2004): a check digit that catches every single
# mistyped digit and every swap of two neighbouring digits.
# The table is a quasigroup of order 10 (each digit appears once in every row and every column) that is
# also "weakly totally anti-symmetric": that property is what turns any neighbour swap into a different
# result. Reading a number feeds each digit through the table, starting from row 0:
#   interim = DAMM[interim][digit]
# The check digit is the interim left after the last digit; since every diagonal entry is 0, feeding the
# check digit itself brings the interim back to 0, so a valid ID always ends at 0. Unlike Luhn, no digit
# is weighted and no carry is needed, and it also catches swaps Luhn misses (such as 09 <-> 90).
DAMM = ("0317598642", "7092154863", "4206871359", "1750983426", "6123045978",
        "3674209581", "5869720134", "8945362017", "9438617205", "2581436790")
DIGITS = "0123456789"
# A base: HTTP or HTTPS, dot-separated host labels, an optional port, optional path folders, and a final
# slash, all in capitals. Capitals, digits, "-", ".", "/" and ":" are all in QR's alphanumeric set
# (ISO/IEC 18004, 45 characters: 0-9, A-Z, space and $ % * + - . / :), which packs two characters into
# 11 bits instead of 16 in byte mode, so a short address in capitals makes a smaller code.
BASE_RE = re.compile(r"^HTTPS?://[A-Z0-9-]+(\.[A-Z0-9-]+)*(:[0-9]{1,5})?/([A-Z0-9-]+/)*$")
SECTIONS = ("local", "nonlocal")  # the two sections of links.json, in the order they are read
# host endings that only a local network resolves (.HOME.ARPA is RFC 8375's home-network zone)
LOCAL_SUFFIXES = (".LOCAL", ".LAN", ".HOME", ".HOME.ARPA", ".INTERNAL", ".LOCALHOST")
SEGMENT_RE = re.compile(r"^[A-Z0-9-]+$")  # one path segment of a short link, which becomes one folder
FIELD_RE = re.compile(r"\{([a-z][a-z0-9_]*)\}")  # a {field} in a link template
TAG_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")  # a tracking tag's query parameter name
# RFC 2606 reserves these names for examples: a base on them can never be served
PLACEHOLDER_HOSTS = ("EXAMPLE.COM", "EXAMPLE.NET", "EXAMPLE.ORG")
MAX_TARGET = 2048  # the longest destination kept; older browsers and servers cut URLs near 2 KB
# characters that could end an HTML attribute or start a tag if a destination were written raw into a
# page; percent-encoding keeps the URL's meaning and makes it inert
UNSAFE = {'"': "%22", "'": "%27", "<": "%3C", ">": "%3E", "`": "%60"}

# The built-in links.json: used for any part of the file that is missing or not valid. The shipped
# links.json is exactly links_text(DEFAULT_LINKS) (a test pins that), so the "about" texts here are what
# a person editing links.json reads.

DEFAULT_LINKS = {
    "about": "Short links: what QR Palette prints in a code when Short link is ticked, and how the redirect "
             "pages are made. There are two sections, local and nonlocal, each with its own base (the address "
             "printed before the ID, in capitals and ending in /) and export_folder (where Export starts; empty "
             "means your home folder). The Make tab switches between them, and settings.json remembers which "
             "one is in use. id_digits: random digits per ID; one check digit is added. tag_ids: add two digits "
             "cut from a hash under this computer's key, so the Read tab can tell your codes from others. "
             "short_by_default: tick Short link when the window opens. tags: query parameters added to every "
             "destination when the "
             "pages are exported; {id} becomes the ID and {hex} the code's color without #. templates: links "
             "you build from fields with From template; {name} is a field you fill in. Edit, save and restart.",
    "local": {
        "about": "Short links that work on this computer or your own network, for trying codes before you have "
                 "a domain. Export the local pages and serve that folder from this computer (README.md shows "
                 "the command). LOCALHOST works in this computer's own browser; for phones on the same Wi-Fi, "
                 "put this computer's network address instead, such as HTTP://192.168.1.20:8000/.",
        "base": "HTTP://LOCALHOST:8000/",
        "export_folder": "",
    },
    "nonlocal": {
        "about": "Short links for codes you print for everyone: an internet address on a domain or subdomain "
                 "of your own, which will serve the exported nonlocal pages. GO.EXAMPLE.COM is only a "
                 "placeholder. Pick a domain you will keep: every printed code depends on it. publish: where File > "
                 "Publish nonlocal pages writes them, after showing what would change and asking. kind git: folder "
                 "is in a Git repository (GitHub Pages, say); the pages, CNAME and .nojekyll are committed and "
                 "pushed, never forced. kind folder: a folder something else syncs. Empty kind: not set up.",
        "base": "HTTPS://GO.EXAMPLE.COM/",
        "export_folder": "",
        "publish": {"kind": "", "folder": ""},
    },
    "id_digits": 7,
    "tag_ids": True,
    "short_by_default": False,
    "tags": {"utm_source": "qr", "utm_medium": "print", "utm_content": "{id}-{hex}"},
    "templates": {
        "page": "https://www.example.com/{page}",
        "product": "https://shop.example.com/p/{item}",
        "event": "https://www.example.com/events/{event}",
    },
}

# The three fixed files of every export: a home page for the bare base address, the page a static host
# shows for an unknown ID, and a robots.txt that keeps search engines out of the redirect pages.
HOME_PAGE = ("<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
             "<meta name=\"robots\" content=\"noindex\">\n<title>QR codes</title>\n</head>\n<body>\n"
             "<p>These addresses forward QR codes to their pages.</p>\n</body>\n</html>\n")
MISSING_PAGE = ("<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
                "<meta name=\"robots\" content=\"noindex\">\n<title>Unknown code</title>\n</head>\n<body>\n"
                "<p>This code is not known. If you typed it, check the digits under the QR code.</p>\n"
                "</body>\n</html>\n")
ROBOTS = "User-agent: *\nDisallow: /\n"


def ok_result(value):
    """A successful Result carrying `value`."""
    return {"ok": True, "error": "", "value": value}


def fail(error):
    """A failed Result with the short phrase `error` and no value."""
    return {"ok": False, "error": error, "value": None}


# --- IDs -------------------------------------------------------------------------------------------

def damm_interim(digits):
    """The Damm interim digit (0-9) after feeding every digit of `digits` through DAMM from row 0.

    `digits` must hold only 0-9 (DIGITS.index raises ValueError otherwise). 0 means a number that
    ends in its own check digit."""
    interim = 0
    for character in digits:
        interim = int(DAMM[interim][DIGITS.index(character)])
    return interim


def check_digit(digits):
    """The Damm check digit for a string of digits: "572" -> "4"."""
    return str(damm_interim(digits))


def is_valid_code(code):
    """True for an ID of digits whose last digit is its Damm check digit.

    The whole ID, check digit included, runs through the table: the interim lands on 0 only when the
    last digit is right. At least two digits are needed (one body digit and the check digit)."""
    if not isinstance(code, str) or len(code) < 2:
        return False
    for character in code:
        if character not in DIGITS:
            return False
    return damm_interim(code) == 0


def id_tag(key, body):
    """The two tag digits of an ID's random digits, under the local key.

    The tag is an HMAC-SHA-256 (RFC 2104) of `body` under purpose "id" (localkey.tag), read as one
    256-bit number and cut to its last two decimal digits. Without the key nobody can compute it, so a
    forged ID on your address has its tag right only by chance, 1 time in 100. The modulo bias of
    2**256 % 100 is far too small to matter."""
    return "%02d" % (int(localkey.tag(key, "id", body), 16) % 100)


def new_code(id_digits, key=None):
    """A fresh random ID: `id_digits` random digits, with a key their two tag digits, and the check digit.

    Layout: body (id_digits) + tag (2, only with a key) + check (1). The random digits come from
    secrets, so IDs cannot be guessed from earlier ones. The caller checks the ID is not already used
    (short_link_ops.plan_short_link)."""
    body = ""
    for index in range(id_digits):
        body = body + str(secrets.randbelow(10))
    if key is not None:
        body = body + id_tag(key, body)
    return body + check_digit(body)


def has_valid_tag(code, key):
    """True when an ID's two digits before its check digit are the tag of the digits before them. One
    ID in 100 that was never tagged passes by chance."""
    if key is None or not is_valid_code(code) or len(code) < 4:
        return False
    # code[:-3] is the random body, code[-3:-1] the tag, code[-1] the check digit
    return id_tag(key, code[:len(code) - 3]) == code[len(code) - 3:len(code) - 1]


def code_standing(code, key, known):
    """How an ID on one of your addresses stands -> "tagged" (made with your key), "untagged" (a short
    link in your registry without a tag: made before tags, or with another key), "unverified" (in your
    registry, with no key here to check it), "unknown" (not in this registry, with no key here to check
    it), or "foreign" (not in this registry, and its tag or its check digit is wrong). `known`: it is in
    this registry. Losing the key makes a tag unverifiable, never invalid.

    `key` is the local key as bytes, or None when there is no key file. The order matters: a wrong
    check digit is "foreign" before anything else, and a right tag is "tagged" whether or not the
    registry knows the ID (a scan on another computer with the same key)."""
    if not is_valid_code(code):
        return "foreign"
    if has_valid_tag(code, key):
        return "tagged"
    if known:
        if key is None:
            return "unverified"
        return "untagged"
    if key is None:
        return "unknown"
    return "foreign"


# --- Addresses that only look like yours --------------------------------------------------------------

# Letters of other alphabets that look like Latin capitals, and digits that look like letters. Written as
# code points: such characters are never written literally in this source.
# 0x04xx are Cyrillic and 0x03xx Greek, capitals and small letters alike. This is a small hand-picked
# cut of the "confusables" idea of Unicode Technical Standard #39, enough for host names. Hosts are put
# in capitals before the lookup, so a small "l" arrives as "L", which is why "L" maps to "I".
LOOKS_LIKE = {0x0410: "A", 0x0430: "A", 0x0412: "B", 0x0421: "C", 0x0441: "C", 0x0415: "E", 0x0435: "E", 0x041D: "H",
              0x0406: "I", 0x0456: "I", 0x0408: "J", 0x0458: "J", 0x041A: "K", 0x041C: "M", 0x041E: "O", 0x043E: "O",
              0x0420: "P", 0x0440: "P", 0x0405: "S", 0x0455: "S", 0x0422: "T", 0x0423: "Y", 0x0443: "Y", 0x0425: "X",
              0x0445: "X", 0x0391: "A", 0x0392: "B", 0x0395: "E", 0x0397: "H", 0x0399: "I", 0x039A: "K", 0x039C: "M",
              0x039D: "N", 0x039F: "O", 0x03BF: "O", 0x03A1: "P", 0x03A4: "T", 0x03A5: "Y", 0x03A7: "X",
              ord("0"): "O", ord("1"): "I", ord("L"): "I", ord("5"): "S"}
# bases shorter than this (LOCALHOST passes, "LAN" would not) are skipped: two edits turn almost any
# short name into another, so every link would look like an imitation
MIN_LOOKALIKE_HOST = 5


def plain_host(host):
    """A host in capitals, its xn-- labels (internationalized names) read back into their letters.

    Internationalized domain names travel as Punycode ("xn--" plus ASCII, IDNA 2003 / RFC 3490);
    decoding them lets skeleton() see the Cyrillic or Greek letters a lookalike hides behind. A label
    that does not decode is kept as written."""
    if "xn--" in host.lower():
        try:
            host = host.lower().encode("ascii").decode("idna")
        except UnicodeError:
            pass
    return host.upper()


def skeleton(host):
    """A host with every character that looks like another replaced by that one.

    Two hosts with the same skeleton read the same to a person, even when their characters differ."""
    kept = []
    for character in host:
        kept.append(LOOKS_LIKE.get(ord(character), character))
    return "".join(kept)


def letters_apart(first, second):
    """How many letters apart two texts are: changed, added, removed, or two neighbours swapped.

    This is the optimal string alignment form of the Damerau-Levenshtein distance. row[j] holds the
    edits that turn the first i letters of `first` into the first j letters of `second`; each cell is
    the cheapest of deleting a letter (the cell above + 1), inserting one (the cell to the left + 1),
    or changing one (the diagonal + 0 or 1). A swap of two neighbours costs 1 and looks two rows back.
    Only three rows are kept (`before`, `previous`, `row`), so memory grows with len(second) alone.

    Steps:
      1. Row 0 is 0..len(second): building a prefix of `second` from nothing takes that many inserts.
      2. For each letter of `first`, fill the new row from the one above and, for swaps, two above.
      3. The last cell is the distance."""
    previous = None
    row = list(range(len(second) + 1))
    for i in range(1, len(first) + 1):
        before = previous
        previous = row
        row = [i] + [0] * len(second)
        for j in range(1, len(second) + 1):
            cost = 0 if first[i - 1] == second[j - 1] else 1
            row[j] = min(previous[j] + 1, row[j - 1] + 1, previous[j - 1] + cost)
            if i > 1 and j > 1 and first[i - 1] == second[j - 2] and first[i - 2] == second[j - 1]:
                row[j] = min(row[j], before[j - 2] + 1)
    return row[len(second)]


def lookalike(url, bases):
    """The base host a link's host imitates, without being it -> that host, or "". Imitating is one or two
    letters off, letters from another alphabet or digits that look the same, your host as the start of
    a longer one (GO.EXAMPLE.COM.EXAMPLE.NET), or your host put before an @, where it means nothing.

    `bases` are the local and nonlocal bases. A link exactly on one of your hosts is not an imitation;
    bases on an IP address or shorter than MIN_LOOKALIKE_HOST are not compared at all. A link that does
    not parse gets "" (no verdict)."""
    try:
        parts = urllib.parse.urlsplit(url)
        host = plain_host(parts.hostname or "").rstrip(".")
        user = (parts.username or "").upper().rstrip(".")
    except ValueError:
        return ""
    if host == "":
        return ""
    for base in bases:
        theirs = host_of(base).split(":")[0]
        if host == theirs or len(theirs) < MIN_LOOKALIKE_HOST or is_ip_address(theirs):
            continue
        # HTTPS://GO.EXAMPLE.COM@EVIL.NET/ goes to EVIL.NET: the part before @ is only a user name
        if user == theirs or host.startswith(theirs + "."):
            return theirs
        if letters_apart(host, theirs) <= 2 or skeleton(host) == skeleton(theirs):
            return theirs
    return ""


def is_ip_address(host):
    """True when `host` is an IPv4 or IPv6 address rather than a name."""
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def short_url(base, code):
    """The printed address of short link `code` on `base` (which already ends in /)."""
    return base + code


def host_of(url):
    """The host (and port) of an address, in capitals: "HTTPS://GO.EXAMPLE.COM/1" -> "GO.EXAMPLE.COM".

    This is the URL's whole netloc, so a "user@" part would stay in; bases never have one. "" when
    the address does not parse."""
    try:
        return urllib.parse.urlsplit(url).netloc.upper()
    except ValueError:
        return ""


def caption(url):
    """The text printed under a code, for typing when a camera cannot scan it: the address without
    its scheme, "GO.EXAMPLE.COM/73491205"."""
    for scheme in ("HTTPS://", "HTTP://"):
        if url.upper().startswith(scheme):
            return url[len(scheme):]
    return url


def is_local_host(host):
    """True for a host that only this computer or its own network can reach: LOCALHOST, a name with
    no dot or a local-network ending (.LOCAL, .LAN, .HOME.ARPA, ...), or a loopback, private or
    link-local IP address. `host` may carry a port; IPv6 addresses are not used in a base.

    Private means the RFC 1918 ranges (10/8, 172.16/12, 192.168/16) among others; link-local is
    169.254/16, where a computer lands without a DHCP server."""
    # split(":") drops the port; it would also cut an IPv6 address apart, which BASE_RE never lets in
    name = host.upper().split(":")[0]
    if name == "LOCALHOST" or "." not in name:
        return True
    for suffix in LOCAL_SUFFIXES:
        if name.endswith(suffix):
            return True
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


def check_base(base, section):
    """"" when `base` can start a short link of `section` ("local" or "nonlocal"), else what is wrong:
    a nonlocal base must be an internet address, so that printed codes work for everyone.

    A local base may be any address that matches BASE_RE, including an internet one."""
    if not isinstance(base, str) or BASE_RE.match(base) is None:
        return ("the base must look like HTTPS://GO.EXAMPLE.COM/ : http or https, then a host and an optional "
                "path in capitals, digits, dots and dashes, ending in /")
    if section == "nonlocal" and is_local_host(host_of(base)):
        return ("the nonlocal base must be an internet address that phones anywhere can reach; this computer's "
                "or your network's address belongs in local")
    return ""


def is_placeholder(base):
    """True while the base is still an example address that nobody can serve.

    The Make tab warns before printing on such a base, and publish.py refuses to publish to one."""
    host = host_of(base).split(":")[0]
    for name in PLACEHOLDER_HOSTS:
        if host == name or host.endswith("." + name):
            return True
    return False


# --- Destinations, templates and tags ----------------------------------------------------------------

def check_target(text):
    """A destination as it may be stored and exported -> Result str: http or https with a host, no
    spaces or control characters, at most 2048 characters. Quotes and angle brackets are
    percent-encoded, so the address can never close the attribute it is written into.

    Steps:
      1. Clean the text (textsafe.clean takes out control characters, line separators and
         bidirectional overrides, but keeps tab and newline) and trim it.
      2. Refuse anything empty, not http(s), too long, or holding any whitespace (tab and newline too).
      3. Parse it and require an http or https scheme with a host.
      4. Percent-encode the UNSAFE characters and hand the result back.
    """
    value = textsafe.clean(text, None).strip()
    if value == "":
        return fail("type the link the code should open")
    if not value.lower().startswith("http://") and not value.lower().startswith("https://"):
        return fail("a short link can only open an http:// or https:// link")
    if len(value) > MAX_TARGET:
        return fail("a link may be at most " + str(MAX_TARGET) + " characters")
    for character in value:
        if character.isspace():
            return fail("a link has no spaces")
    try:
        parts = urllib.parse.urlsplit(value)
        host = parts.hostname
    except ValueError:
        return fail("not a valid link: " + value[:80])
    if parts.scheme.lower() not in ("http", "https") or not host:
        return fail("a short link can only open an http:// or https:// link")
    encoded = []
    for character in value:
        encoded.append(UNSAFE.get(character, character))
    return ok_result("".join(encoded))


def template_fields(pattern):
    """The fields a template asks for, in order: "https://x.example/{a}/{b}" -> ["a", "b"].

    A field written twice is listed once, where it first appears."""
    found = []
    for name in FIELD_RE.findall(pattern):
        if name not in found:
            found.append(name)
    return found


def fill_template(pattern, values):
    """A link from a template and the values of its fields -> Result link. Each value is one part of
    the link, so characters such as / and ? in it are percent-encoded.

    `values` maps field names to typed text; a missing or empty field fails with "fill in NAME". The
    filled link still has to pass check_target()."""
    link = pattern
    for name in template_fields(pattern):
        value = textsafe.clean(values.get(name, ""), None).strip()
        if value == "":
            return fail("fill in " + name)
        # safe="" encodes "/" as well, so a value can never add a path segment of its own
        link = link.replace("{" + name + "}", urllib.parse.quote(value, safe=""))
    return check_target(link)


def tagged(target, tags, code, color):
    """The destination with the tracking tags added (a tag the link already has is left as it is):
    {id} becomes the ID and {hex} the color without its #. The link's own query is kept as written.

    `tags` is links.json's tags ({name: value template}); a tag whose value comes out empty is left
    out. The added pairs are form-encoded after the existing query, and the fragment stays last. A
    target that does not parse comes back unchanged. These are the UTM parameters analytics tools read
    (utm_source, utm_medium, utm_content by default)."""
    try:
        parts = urllib.parse.urlsplit(target)
    except ValueError:
        return target
    present = []
    for pair in urllib.parse.parse_qsl(parts.query, keep_blank_values=True):
        present.append(pair[0])
    added = []
    for name in tags:
        value = tags[name].replace("{id}", code).replace("{hex}", color.lstrip("#"))
        if value == "" or name in present:
            continue
        added.append((name, value))
    if len(added) == 0:
        return target
    query = parts.query
    if query != "":
        query = query + "&"
    query = query + urllib.parse.urlencode(added)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


# --- links.json ------------------------------------------------------------------------------------

def read_text(path):
    """The whole text of a UTF-8 file; raises OSError when it cannot be read.

    "utf-8-sig" drops a byte-order mark if an editor (Notepad, for one) put one at the start, which
    json.loads would otherwise refuse."""
    handle = open(path, "r", encoding="utf-8-sig")
    try:
        return handle.read()
    finally:
        handle.close()


def expand(path):
    """A folder from links.json with ~ and environment variables expanded and normalized; "" stays ""
    (it means the home folder, chosen later)."""
    if path == "":
        return ""
    return os.path.normpath(os.path.expandvars(os.path.expanduser(path)))


def copy_links(links):
    """A copy of a Links record that can be changed without touching the original (two levels deep).

    Below the top level, each dict (a section, tags, templates) is copied, and so is each dict inside
    those (nonlocal's publish); strings, numbers and booleans are shared, which is safe since they
    cannot change."""
    copied = {}
    for key in links:
        value = links[key]
        if isinstance(value, dict):
            inner = {}
            for name in value:
                inner[name] = value[name]
                if isinstance(value[name], dict):
                    inner[name] = dict(value[name])
            value = inner
        copied[key] = value
    return copied


def read_section(links, data, section, warnings):
    """One section of links.json into `links`: its base (checked for the section) and export folder.

    `data` is the parsed file, `section` "local" or "nonlocal". Each part that is not valid keeps its
    default and appends a line to `warnings` (changed in place, as is `links`). Only nonlocal reads a
    publish part; its kind must be "", "git" or "folder"."""
    if section not in data:
        return
    found = data[section]
    if not isinstance(found, dict):
        warnings.append("links: " + section + " must be an object with a base and an export_folder")
        return
    if "base" in found:
        problem = check_base(found["base"], section)
        if problem == "":
            links[section]["base"] = found["base"]
        else:
            warnings.append("links: " + section + ".base: " + problem)
    if "export_folder" in found:
        if isinstance(found["export_folder"], str):
            links[section]["export_folder"] = expand(found["export_folder"])
        else:
            warnings.append("links: " + section + ".export_folder must be text")
    if section == "nonlocal" and "publish" in found:
        publish = found["publish"]
        if (isinstance(publish, dict) and publish.get("kind", "") in ("", "git", "folder") and
                isinstance(publish.get("folder", ""), str)):
            links[section]["publish"] = {"kind": publish.get("kind", ""), "folder": expand(publish.get("folder", ""))}
        else:
            warnings.append('links: nonlocal.publish must be {"kind": "git" or "folder", "folder": a folder}')


def load_links(path):
    """links.json -> {"links": Links, "warnings": [str]}. Parts that are missing or not valid keep
    their defaults (only the ones not valid add a warning); a file that cannot be read or is not
    valid JSON means the defaults, with one warning.

    Steps:
      1. Start from a copy of DEFAULT_LINKS and parse the file.
      2. Read both sections (read_section), then id_digits (4 to 12; a bool is refused even though
         Python counts True as an int), tag_ids, short_by_default, tags and templates.
      3. A template is kept only when filling every field with "x" gives a valid link and no stray
         brace is left once its {fields} are taken out.
    """
    links = copy_links(DEFAULT_LINKS)
    try:
        data = json.loads(read_text(path))
    except (OSError, ValueError) as error:
        return {"links": links, "warnings": ["cannot use " + path + " (" + str(error) + "); using the built-in "
                                             "short-link settings"]}
    if not isinstance(data, dict):
        return {"links": links, "warnings": [path + " must hold one JSON object; using the built-in short-link "
                                             "settings"]}
    warnings = []
    for section in SECTIONS:
        read_section(links, data, section, warnings)
    if "id_digits" in data:
        digits = data["id_digits"]
        if not isinstance(digits, bool) and isinstance(digits, int) and 4 <= digits <= 12:
            links["id_digits"] = digits
        else:
            warnings.append("links: id_digits must be a whole number from 4 to 12")
    if "tag_ids" in data:
        if isinstance(data["tag_ids"], bool):
            links["tag_ids"] = data["tag_ids"]
        else:
            warnings.append("links: tag_ids must be true or false")
    if "short_by_default" in data:
        if isinstance(data["short_by_default"], bool):
            links["short_by_default"] = data["short_by_default"]
        else:
            warnings.append("links: short_by_default must be true or false")
    # tags and templates replace the defaults as a whole; one bad entry is dropped, the rest kept
    if "tags" in data:
        tags = {}
        if isinstance(data["tags"], dict):
            for name in data["tags"]:
                value = data["tags"][name]
                if TAG_NAME_RE.match(name) is not None and isinstance(value, str) and len(value) <= 200:
                    tags[name] = value
                else:
                    warnings.append("links: tags: " + json.dumps(name) + " must be a short name with a text value")
            links["tags"] = tags
        else:
            warnings.append("links: tags must be an object of names and values")
    if "templates" in data:
        templates = {}
        if isinstance(data["templates"], dict):
            for name in data["templates"]:
                pattern = data["templates"][name]
                sample = {}
                rest = "{"  # a pattern that is not text keeps a brace here, so it fails below
                if isinstance(pattern, str):
                    for field in template_fields(pattern):
                        sample[field] = "x"
                    rest = FIELD_RE.sub("", pattern)
                if (isinstance(pattern, str) and name.strip() != "" and "{" not in rest and "}" not in rest and
                        fill_template(pattern, sample)["ok"]):
                    templates[name.strip()] = pattern
                else:
                    warnings.append("links: templates: " + json.dumps(name) + " must be an http(s) link whose "
                                    "fields are written {name}")
            links["templates"] = templates
        else:
            warnings.append("links: templates must be an object of names and links")
    return {"links": links, "warnings": warnings}


def section_of(links, url):
    """Which section a printed address belongs to ("local" or "nonlocal"), by the base it starts
    with; "" when neither (made before a base was changed).

    `links` is a Links record (app_settings.LINKS, or an engine's copy in ecp.py)."""
    for section in SECTIONS:
        if url.startswith(links[section]["base"]):
            return section
    return ""


def links_text(links):
    """links.json as people read it: indented, one setting per line.

    ensure_ascii=False keeps non-ASCII text readable instead of escaping it; the file ends in a newline."""
    return json.dumps(links, indent=2, ensure_ascii=False) + "\n"


# --- Redirect pages ----------------------------------------------------------------------------------

def redirect_page(target):
    """One redirect page: it sends the browser straight on, and shows the link for any browser that
    does not follow it. Search engines are asked to leave it out.

    A static host cannot send an HTTP 301/302, so the page redirects itself: <meta http-equiv="refresh"
    content="0; url=..."> tells the browser to load the target after 0 seconds. rel="canonical" points
    search engines at the destination, and the visible link is the fallback for browsers with
    refresh turned off. The target is HTML-escaped, on top of check_target's percent-encoding."""
    shown = html.escape(target, quote=True)
    return ("<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"robots\" content=\"noindex\">\n"
            "<meta http-equiv=\"refresh\" content=\"0; url=" + shown + "\">\n"
            "<link rel=\"canonical\" href=\"" + shown + "\">\n"
            "<title>Opening the link</title>\n</head>\n<body>\n"
            "<p><a href=\"" + shown + "\">Open " + shown + "</a></p>\n</body>\n</html>\n")


def page_parts(url):
    """Where a short link's page goes inside the export folder: "HTTPS://GO.EXAMPLE.COM/Q/12" ->
    ["Q", "12", "index.html"], or None when its path is not plain capitals, digits and dashes.

    Each short link becomes a folder holding index.html because static hosts answer /12 with the
    folder's index page; a file named "12" with no extension would be sent with the wrong type. The
    strict segment pattern also keeps ".." and other path tricks out of the export folder."""
    try:
        path = urllib.parse.urlsplit(url).path
    except ValueError:
        return None
    segments = path.strip("/").split("/")
    for segment in segments:
        if SEGMENT_RE.match(segment) is None:
            return None
    return segments + ["index.html"]


def write_text(path, text):
    """Write a file next to its place first, then move it in, so a page is never half written.

    Makes the folder when needed. os.replace is atomic on one volume, so a web server serving the
    folder sees the old page or the new one, never part of one. Lines end in LF; raises OSError."""
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    temporary = path + ".part"
    handle = open(temporary, "w", encoding="utf-8", newline="\n")
    try:
        handle.write(text)
    finally:
        handle.close()
    os.replace(temporary, path)


def export_pages(folder, rows, base, tags):
    """Write a redirect page for every short link on `base`'s host (one section's), plus index.html,
    404.html and robots.txt -> Result {"folder", "written", "skipped": [ID]}. Short links on another
    host (the other section's, or made before a base changed) and destinations that are no longer
    valid are skipped.

    `rows` are ShortLink records with the destination for the day wanted (registry.short_links_on),
    `tags` links.json's tracking tags. Pages of short links no longer in `rows` are not deleted.

    Steps:
      1. Build every page in memory first: one per row on this host, with its target checked again
         and tagged.
      2. Add the three fixed files.
      3. Write them all (write_text); "written" counts the redirect pages only."""
    if folder == "":
        return fail("choose a folder for the redirect pages")
    host = host_of(base)
    pages = []
    skipped = []
    for row in rows:
        parts = page_parts(row["url"])
        target = check_target(row["target"])
        if host_of(row["url"]) != host or parts is None or not target["ok"]:
            skipped.append(row["code"])
            continue
        pages.append((parts, redirect_page(tagged(target["value"], tags, row["code"], row["hex"]))))
    pages.append((["index.html"], HOME_PAGE))
    pages.append((["404.html"], MISSING_PAGE))
    pages.append((["robots.txt"], ROBOTS))
    try:
        for parts, text in pages:
            write_text(os.path.join(folder, *parts), text)
    except OSError as error:
        return fail("cannot write the redirect pages: " + str(error))
    return ok_result({"folder": folder, "written": len(pages) - 3, "skipped": skipped})


# --- Serving the local pages from this computer -------------------------------------------------------

def serve_address(base, network):
    """Where the local pages are served -> Result (address, port), from the local section's base. Only
    http (there is no certificate here). LOCALHOST and loopback addresses bind to this computer alone;
    any other address reaches your network, so it needs `network` (the person said yes to that).

    A host name other than LOCALHOST binds to 0.0.0.0 (every interface of this computer), since the
    name itself cannot be bound; an IP address binds to that address alone."""
    try:
        parts = urllib.parse.urlsplit(base)
        port = parts.port or 80  # http's default port when the base names none
        host = (parts.hostname or "").lower()
    except ValueError:
        return fail("the local base is not a valid address")
    if parts.scheme.lower() != "http":
        return fail("only an http:// local base can be served from this computer")
    if host == "localhost":
        return ok_result(("127.0.0.1", port))
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and address.is_loopback:
        return ok_result((str(address), port))
    if not network:
        return fail("the local base " + base + " is on your network: allow phones on your network first")
    if address is not None:
        return ok_result((str(address), port))
    return ok_result(("0.0.0.0", port))


def page_handler(folder):
    """A request handler for the exported pages: GET and HEAD of files in `folder` only, never a list
    of files, the folder's own 404.html for anything missing, and nothing logged.

    Returns a class, not an instance: the server makes one handler per request. The class closes over
    `folder` because SimpleHTTPRequestHandler takes its root as a constructor argument, which the server
    does not pass."""
    missing = os.path.join(folder, "404.html")

    class PageHandler(http.server.SimpleHTTPRequestHandler):
        """SimpleHTTPRequestHandler rooted at `folder`, quiet, with no folder listings."""

        def __init__(self, *arguments, **options):
            """Handle one request with `folder` as the web root (the base class serves it at once)."""
            super().__init__(*arguments, directory=folder, **options)

        def log_message(self, *arguments):
            """Log nothing (the base class writes a line per request to stderr)."""
            pass

        def list_directory(self, path):
            """Refuse to list a folder that has no index.html: answer 404 instead -> None (no body)."""
            self.send_error(404)
            return None

        def send_error(self, code, message=None, explain=None):
            """Answer an error; a 404 sends the folder's own 404.html when there is one.

            Other codes, or a folder without 404.html, get the base class's plain error page. A HEAD
            request gets the headers alone."""
            if code != 404 or not os.path.isfile(missing):
                super().send_error(code, message, explain)
                return
            handle = open(missing, "rb")
            try:
                body = handle.read()
            finally:
                handle.close()
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

    return PageHandler


class PageServer(http.server.ThreadingHTTPServer):
    """The local page server: one thread per request, and no port sharing on Windows."""

    # On Windows, SO_REUSEADDR lets a second server take a port that is already in use; never ask for it there.
    allow_reuse_address = os.name != "nt"


def start_server(folder, base, network):
    """Serve the exported local pages in `folder` at the local base -> Result Server {"server",
    "thread", "address", "port", "folder", "base"}. Stop it with stop_server().

    `network` is the person's yes to serving on the network (see serve_address). Fails when the base
    cannot be served, when `folder` has no index.html yet (nothing exported), or when the port is
    taken. Side effects: a listening socket, and a daemon thread running serve_forever, so it never
    keeps the program alive on exit."""
    where = serve_address(base, network)
    if not where["ok"]:
        return where
    if not os.path.isfile(os.path.join(folder, "index.html")):
        return fail("export the local pages into " + folder + " first")
    try:
        server = PageServer(where["value"], page_handler(folder))
    except OSError as error:
        return fail("cannot serve on " + where["value"][0] + " port " + str(where["value"][1]) + ": " + str(error))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return ok_result({"server": server, "thread": thread, "address": where["value"][0], "port": where["value"][1],
                      "folder": folder, "base": base})


def stop_server(running):
    """Stop a Server from start_server(): end its loop, close its socket, and wait up to 5 seconds
    for its thread.

    shutdown() must come first: it waits for serve_forever to return, after which server_close()
    frees the port."""
    running["server"].shutdown()
    running["server"].server_close()
    running["thread"].join(5)

# ==== stamp v1 | author=kjFriday | hmac-sha256=b830c6aef32a0e2ccd46a72cec64e6c05e5022b1f8275b2688712c6d3346bd95 ====
