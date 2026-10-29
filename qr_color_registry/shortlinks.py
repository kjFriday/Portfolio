# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: qr_color_registry/shortlinks.py
# About: QR Palette short links: a short address printed in a QR code, pointing at a destination...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""QR Palette short links: a short address printed in a QR code, pointing at a destination that can
change later without reprinting the code.

A short link is the base address plus an ID, for example HTTPS://GO.EXAMPLE.COM/73491205:
  * The ID is random digits and one Damm check digit, so a mistyped ID is caught. Digits cannot be
    misread as letters, and they have no case: static web hosts treat /ABC and /abc as different
    pages, so a typed fallback with letters breaks when someone types it in lower case.
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
  Links      {"about", "local": Section, "nonlocal": Section, "id_digits", "short_by_default",
              "tags": {name: value}, "templates": {name: pattern}}           links.json, checked
  Section    {"about", "base", "export_folder"}
  ShortLink  {"code", "url", "target", "hex", ...}               one short link from the registry
"""

import html
import ipaddress
import json
import os
import re
import secrets
import urllib.parse

import textsafe

# The Damm algorithm's table (H. Michael Damm, 2004): a check digit that catches every single
# mistyped digit and every swap of two neighbouring digits.
DAMM = ("0317598642", "7092154863", "4206871359", "1750983426", "6123045978",
        "3674209581", "5869720134", "8945362017", "9438617205", "2581436790")
DIGITS = "0123456789"
BASE_RE = re.compile(r"^HTTPS?://[A-Z0-9-]+(\.[A-Z0-9-]+)*(:[0-9]{1,5})?/([A-Z0-9-]+/)*$")
SECTIONS = ("local", "nonlocal")
LOCAL_SUFFIXES = (".LOCAL", ".LAN", ".HOME", ".HOME.ARPA", ".INTERNAL", ".LOCALHOST")
SEGMENT_RE = re.compile(r"^[A-Z0-9-]+$")
FIELD_RE = re.compile(r"\{([a-z][a-z0-9_]*)\}")
TAG_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
PLACEHOLDER_HOSTS = ("EXAMPLE.COM", "EXAMPLE.NET", "EXAMPLE.ORG")
MAX_TARGET = 2048
UNSAFE = {'"': "%22", "'": "%27", "<": "%3C", ">": "%3E", "`": "%60"}

DEFAULT_LINKS = {
    "about": "Short links: what QR Palette prints in a code when Short link is ticked, and how the redirect "
             "pages are made. There are two sections, local and nonlocal, each with its own base (the address "
             "printed before the ID, in capitals and ending in /) and export_folder (where Export starts; empty "
             "means your home folder). The Make tab switches between them, and settings.json remembers which "
             "one is in use. id_digits: random digits per ID; one check digit is added. short_by_default: tick "
             "Short link when the window opens. tags: query parameters added to every destination when the "
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
                 "placeholder. Pick a domain you will keep: every printed code depends on it.",
        "base": "HTTPS://GO.EXAMPLE.COM/",
        "export_folder": "",
    },
    "id_digits": 7,
    "short_by_default": False,
    "tags": {"utm_source": "qr", "utm_medium": "print", "utm_content": "{id}-{hex}"},
    "templates": {
        "page": "https://www.example.com/{page}",
        "product": "https://shop.example.com/p/{item}",
        "event": "https://www.example.com/events/{event}",
    },
}

HOME_PAGE = ("<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
             "<meta name=\"robots\" content=\"noindex\">\n<title>QR codes</title>\n</head>\n<body>\n"
             "<p>These addresses forward QR codes to their pages.</p>\n</body>\n</html>\n")
MISSING_PAGE = ("<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
                "<meta name=\"robots\" content=\"noindex\">\n<title>Unknown code</title>\n</head>\n<body>\n"
                "<p>This code is not known. If you typed it, check the digits under the QR code.</p>\n"
                "</body>\n</html>\n")
ROBOTS = "User-agent: *\nDisallow: /\n"


def ok_result(value):
    return {"ok": True, "error": "", "value": value}


def fail(error):
    return {"ok": False, "error": error, "value": None}


# --- IDs -------------------------------------------------------------------------------------------

def damm_interim(digits):
    interim = 0
    for character in digits:
        interim = int(DAMM[interim][DIGITS.index(character)])
    return interim


def check_digit(digits):
    """The Damm check digit for a string of digits: "572" -> "4"."""
    return str(damm_interim(digits))


def is_valid_code(code):
    """True for an ID of digits whose last digit is its Damm check digit."""
    if not isinstance(code, str) or len(code) < 2:
        return False
    for character in code:
        if character not in DIGITS:
            return False
    return damm_interim(code) == 0


def new_code(id_digits):
    """A fresh random ID: `id_digits` random digits and the check digit."""
    body = ""
    for index in range(id_digits):
        body = body + str(secrets.randbelow(10))
    return body + check_digit(body)


def short_url(base, code):
    return base + code


def host_of(url):
    """The host (and port) of an address, in capitals: "HTTPS://GO.EXAMPLE.COM/1" -> "GO.EXAMPLE.COM"."""
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
    link-local IP address. `host` may carry a port; IPv6 addresses are not used in a base."""
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
    a nonlocal base must be an internet address, so that printed codes work for everyone."""
    if not isinstance(base, str) or BASE_RE.match(base) is None:
        return ("the base must look like HTTPS://GO.EXAMPLE.COM/ : http or https, then a host and an optional "
                "path in capitals, digits, dots and dashes, ending in /")
    if section == "nonlocal" and is_local_host(host_of(base)):
        return ("the nonlocal base must be an internet address that phones anywhere can reach; this computer's "
                "or your network's address belongs in local")
    return ""


def is_placeholder(base):
    """True while the base is still an example address that nobody can serve."""
    host = host_of(base).split(":")[0]
    for name in PLACEHOLDER_HOSTS:
        if host == name or host.endswith("." + name):
            return True
    return False


# --- Destinations, templates and tags ----------------------------------------------------------------

def check_target(text):
    """A destination as it may be stored and exported -> Result str: http or https with a host, no
    spaces or control characters, at most 2048 characters. Quotes and angle brackets are
    percent-encoded, so the address can never close the attribute it is written into."""
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
    """The fields a template asks for, in order: "https://x.example/{a}/{b}" -> ["a", "b"]."""
    found = []
    for name in FIELD_RE.findall(pattern):
        if name not in found:
            found.append(name)
    return found


def fill_template(pattern, values):
    """A link from a template and the values of its fields -> Result link. Each value is one part of
    the link, so characters such as / and ? in it are percent-encoded."""
    link = pattern
    for name in template_fields(pattern):
        value = textsafe.clean(values.get(name, ""), None).strip()
        if value == "":
            return fail("fill in " + name)
        link = link.replace("{" + name + "}", urllib.parse.quote(value, safe=""))
    return check_target(link)


def tagged(target, tags, code, color):
    """The destination with the tracking tags added (a tag the link already has is left as it is):
    {id} becomes the ID and {hex} the color without its #. The link's own query is kept as written."""
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
    handle = open(path, "r", encoding="utf-8-sig")
    try:
        return handle.read()
    finally:
        handle.close()


def expand(path):
    if path == "":
        return ""
    return os.path.normpath(os.path.expandvars(os.path.expanduser(path)))


def copy_links(links):
    """A copy of a Links record that can be changed without touching the original (two levels deep)."""
    copied = {}
    for key in links:
        value = links[key]
        if isinstance(value, dict):
            inner = {}
            for name in value:
                inner[name] = value[name]
            value = inner
        copied[key] = value
    return copied


def read_section(links, data, section, warnings):
    """One section of links.json into `links`: its base (checked for the section) and export folder."""
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


def load_links(path):
    """links.json -> {"links": Links, "warnings": [str]}. Parts that are missing or not valid keep
    their defaults, and say so; a file that is not valid JSON means the defaults."""
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
    if "short_by_default" in data:
        if isinstance(data["short_by_default"], bool):
            links["short_by_default"] = data["short_by_default"]
        else:
            warnings.append("links: short_by_default must be true or false")
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
                rest = "{"
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
    with; "" when neither (made before a base was changed)."""
    for section in SECTIONS:
        if url.startswith(links[section]["base"]):
            return section
    return ""


def links_text(links):
    """links.json as people read it: indented, one setting per line."""
    return json.dumps(links, indent=2, ensure_ascii=False) + "\n"


# --- Redirect pages ----------------------------------------------------------------------------------

def redirect_page(target):
    """One redirect page: it sends the browser straight on, and shows the link for any browser that
    does not follow it. Search engines are asked to leave it out."""
    shown = html.escape(target, quote=True)
    return ("<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"robots\" content=\"noindex\">\n"
            "<meta http-equiv=\"refresh\" content=\"0; url=" + shown + "\">\n"
            "<link rel=\"canonical\" href=\"" + shown + "\">\n"
            "<title>Opening the link</title>\n</head>\n<body>\n"
            "<p><a href=\"" + shown + "\">Open " + shown + "</a></p>\n</body>\n</html>\n")


def page_parts(url):
    """Where a short link's page goes inside the export folder: "HTTPS://GO.EXAMPLE.COM/Q/12" ->
    ["Q", "12", "index.html"], or None when its path is not plain capitals, digits and dashes."""
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
    """Write a file next to its place first, then move it in, so a page is never half written."""
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
    valid are skipped."""
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

# ==== stamp v1 | author=kjFriday | hmac-sha256=c95f98d4ed15aa90e8857e951fdf76e713a7650c2848a60ed2105be525d4947f ====
