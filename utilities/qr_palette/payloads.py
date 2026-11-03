# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: payloads.py
# About: QR Palette code kinds: what a QR code can hold other than a web link, built from a small...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""QR Palette code kinds: what a QR code can hold other than a web link, built from a small form.

  wifi     WIFI:T:WPA;S:name;P:password;;      joins a network (\\ ; , : and " are escaped)
  contact  a vCard 3.0                         adds a contact
  event    an iCalendar VEVENT                 adds a calendar event, on this device's clock
  place    geo:52.37,4.89                      opens a map
  email    mailto:shop@example.com?subject=…   starts an email
  phone    tel:+15550100                       starts a call
  text     SMSTO:+15550100:message             starts a text message

A Wi-Fi password must not be kept in the registry. stored_form() gives the text to keep instead, with the
password masked; the registry adds a keyed hash of the real text, so a scanned code still finds its
record (localkey.py). This applies however the text arrived: built here, typed as a link, in a list of
codes, or read from a picture.

vCard and iCalendar lines end in CRLF, as their standards say, and long lines are folded at 75 bytes.
So a built payload must reach the encoder exactly as it is: textsafe.clean would take the CRs out.

Records
  Result   {"ok": bool, "error": str, "value": any}
  Payload  {"kind", "text": what the code holds, "stored": what the registry keeps, "masked": bool,
            "name": a file-name part that holds no secret}
  Field    (key, label, hidden while typed, the choices it offers or None) in FIELDS
"""

import re
import urllib.parse

import textsafe

KINDS = ("link", "wifi", "contact", "event", "place", "email", "phone", "text")
TITLES = {"link": "Web link", "wifi": "Wi-Fi join", "contact": "Contact card", "event": "Calendar event",
          "place": "Map location", "email": "Email", "phone": "Phone call", "text": "Text message"}
FIELDS = {
    "link": (),
    "wifi": (("ssid", "Network name", False, None), ("password", "Password", True, None),
             ("security", "Security", False, ("WPA", "WEP", "none")), ("hidden", "Hidden network", False, ("no", "yes"))),
    "contact": (("first", "First name", False, None), ("last", "Last name", False, None),
                ("org", "Organization", False, None), ("phone", "Phone", False, None), ("email", "Email", False, None),
                ("url", "Web page", False, None)),
    "event": (("title", "Title", False, None), ("start", "Starts", False, None),
              ("end", "Ends", False, None), ("place", "Where", False, None), ("about", "About", False, None)),
    "place": (("latitude", "Latitude", False, None), ("longitude", "Longitude", False, None)),
    "email": (("to", "To", False, None), ("subject", "Subject", False, None), ("body", "Message", False, None)),
    "phone": (("number", "Number", False, None),),
    "text": (("number", "Number", False, None), ("message", "Message", False, None)),
}
MASK = "********"
FOLD_AT = 75
DAY_TIME = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})(?:[ T]([0-9]{1,2}):([0-9]{2}))?$")
NUMBER_CHARACTERS = " -()."


def ok_result(value):
    return {"ok": True, "error": "", "value": value}


def fail(error):
    return {"ok": False, "error": error, "value": None}


def clean_fields(fields):
    """The form's values, without control or direction characters. Newlines stay for the kinds that
    can hold them (they are escaped there)."""
    cleaned = {}
    for key in fields:
        value = fields[key]
        if not isinstance(value, str):
            value = ""
        cleaned[key] = textsafe.clean(value, None)
    return cleaned


# --- Wi-Fi -------------------------------------------------------------------------------------------

def wifi_escape(value):
    """A Wi-Fi field's text with the five special characters escaped."""
    escaped = []
    for character in value:
        if character in '\\;,:"':
            escaped.append("\\")
        escaped.append(character)
    return "".join(escaped)


def wifi_fields(text):
    """The fields of a WIFI: text, split at unescaped semicolons -> ["T:WPA", "S:name", ...] or None."""
    if not text.upper().startswith("WIFI:"):
        return None
    parts = []
    current = []
    index = 5
    while index < len(text):
        character = text[index]
        if character == "\\" and index + 1 < len(text):
            current.append(text[index:index + 2])
            index = index + 2
            continue
        if character == ";":
            parts.append("".join(current))
            current = []
        else:
            current.append(character)
        index = index + 1
    if len(current) > 0:
        parts.append("".join(current))
    return parts


def stored_form(text):
    """What the registry may keep of a code's text -> (text to keep, masked). A Wi-Fi password is
    replaced by MASK, always the same length; any other text is kept as it is."""
    parts = wifi_fields(text)
    if parts is None:
        return text, False
    masked = False
    kept = []
    for part in parts:
        if part.upper().startswith("P:") and len(part) > 2:
            kept.append(part[:2] + MASK)
            masked = True
        elif part != "":
            kept.append(part)
    if not masked:
        return text, False
    return "WIFI:" + ";".join(kept) + ";;", True


def is_masked(text):
    """True for stored text whose secret was masked: the registry cannot draw this code again."""
    parts = wifi_fields(text)
    if parts is None:
        return False
    return "P:" + MASK in parts


def build_wifi(fields):
    ssid = fields.get("ssid", "").replace("\n", "").replace("\t", "")
    password = fields.get("password", "").replace("\n", "").replace("\t", "")
    if ssid.strip() == "":
        return fail("type the network name")
    security = fields.get("security", "").strip().upper()
    if security == "":
        security = "WPA" if password != "" else "NOPASS"
    if security in ("NONE", "OPEN", "NOPASS"):
        security = "nopass"
    elif security in ("WPA2", "WPA3", "WPA2/WPA3"):
        security = "WPA"
    elif security not in ("WPA", "WEP"):
        return fail("security is WPA, WEP or none")
    if security != "nopass" and password == "":
        return fail("type the password, or set security to none")
    if security == "nopass" and password != "":
        return fail("an open network has no password: set security to WPA, or clear the password")
    text = "WIFI:T:" + security + ";S:" + wifi_escape(ssid) + ";"
    if security != "nopass":
        text = text + "P:" + wifi_escape(password) + ";"
    if fields.get("hidden", "").strip().lower() in ("yes", "y", "true", "1"):
        text = text + "H:true;"
    return ok_result((text + ";", "wifi-" + ssid))


# --- vCard and iCalendar -----------------------------------------------------------------------------

def text_escape(value):
    """A vCard or iCalendar text value: backslash, comma, semicolon and line breaks escaped."""
    return (value.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\r\n", "\\n")
            .replace("\n", "\\n"))


def fold(line):
    """A content line folded at FOLD_AT bytes, never inside a character: continuation lines start with
    a space, which counts."""
    if len(line.encode("utf-8")) <= FOLD_AT:
        return line
    parts = []
    current = ""
    size = 0
    for character in line:
        width = len(character.encode("utf-8"))
        if size + width > FOLD_AT:
            parts.append(current)
            current = " "
            size = 1
        current = current + character
        size = size + width
    parts.append(current)
    return "\r\n".join(parts)


def content_lines(lines):
    """Content lines as one text: folded, each ending in CRLF."""
    folded = []
    for line in lines:
        folded.append(fold(line))
    return "\r\n".join(folded) + "\r\n"


def clean_number(value):
    """A phone number as digits and a leading + -> the number, or "" when it is not one."""
    kept = ""
    for character in value.strip():
        if character in NUMBER_CHARACTERS:
            continue
        kept = kept + character
    digits = kept
    if digits.startswith("+"):
        digits = digits[1:]
    if len(digits) < 3 or len(digits) > 20 or not digits.isdigit() or not digits.isascii():
        return ""
    return kept


def build_contact(fields):
    first = fields.get("first", "").strip()
    last = fields.get("last", "").strip()
    org = fields.get("org", "").strip()
    if first == "" and last == "" and org == "":
        return fail("type a name or an organization")
    shown = (first + " " + last).strip() or org
    lines = ["BEGIN:VCARD", "VERSION:3.0", "N:" + text_escape(last) + ";" + text_escape(first) + ";;;",
             "FN:" + text_escape(shown)]
    if org != "":
        lines.append("ORG:" + text_escape(org))
    phone = fields.get("phone", "").strip()
    if phone != "":
        number = clean_number(phone)
        if number == "":
            return fail("the phone is a number, such as +1 555 0100")
        lines.append("TEL:" + number)
    email = fields.get("email", "").strip()
    if email != "":
        if not is_email(email):
            return fail("the email is an address, such as shop@example.com")
        lines.append("EMAIL:" + email)
    url = fields.get("url", "").strip()
    if url != "":
        lines.append("URL:" + url.replace("\n", ""))
    lines.append("END:VCARD")
    return ok_result((content_lines(lines), "contact-" + shown))


def calendar_time(value):
    """A day and time typed in the form -> (value, is a whole day), or None when it is not one."""
    match = DAY_TIME.match(value.strip())
    if match is None:
        return None
    year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        return None
    if match.group(4) is None:
        return "%04d%02d%02d" % (year, month, day), True
    hour, minute = int(match.group(4)), int(match.group(5))
    if hour > 23 or minute > 59:
        return None
    return "%04d%02d%02dT%02d%02d00" % (year, month, day, hour, minute), False


def build_event(fields):
    title = fields.get("title", "").strip()
    if title == "":
        return fail("type a title")
    start = calendar_time(fields.get("start", ""))
    if start is None:
        return fail("the start is written YYYY-MM-DD HH:MM, or YYYY-MM-DD for a whole day")
    lines = ["BEGIN:VEVENT", "SUMMARY:" + text_escape(title)]
    lines.append(("DTSTART;VALUE=DATE:" if start[1] else "DTSTART:") + start[0])
    if fields.get("end", "").strip() != "":
        end = calendar_time(fields["end"])
        if end is None:
            return fail("the end is written YYYY-MM-DD HH:MM, or YYYY-MM-DD for a whole day")
        if end[1] != start[1]:
            return fail("the start and the end must both have a time, or neither")
        if end[0] < start[0]:
            return fail("the event ends before it starts")
        lines.append(("DTEND;VALUE=DATE:" if end[1] else "DTEND:") + end[0])
    if fields.get("place", "").strip() != "":
        lines.append("LOCATION:" + text_escape(fields["place"].strip()))
    if fields.get("about", "").strip() != "":
        lines.append("DESCRIPTION:" + text_escape(fields["about"].strip()))
    lines.append("END:VEVENT")
    return ok_result((content_lines(lines), "event-" + title))


# --- The one-line kinds ------------------------------------------------------------------------------

def degrees(value, limit):
    """A coordinate as typed -> its text, or "" when it is not a number within +-limit."""
    text = value.strip().replace(",", ".")
    if re.match(r"^[+-]?[0-9]{1,3}(\.[0-9]{1,8})?$", text) is None or abs(float(text)) > limit:
        return ""
    return text.lstrip("+")


def build_place(fields):
    latitude = degrees(fields.get("latitude", ""), 90)
    longitude = degrees(fields.get("longitude", ""), 180)
    if latitude == "" or longitude == "":
        return fail("latitude is a number from -90 to 90 and longitude one from -180 to 180")
    return ok_result(("geo:" + latitude + "," + longitude, "place-" + latitude + "-" + longitude))


def is_email(value):
    """True for text shaped like one email address (the mail server has the last word)."""
    return re.match(r"^[^@\s<>\"',;:]+@[^@\s<>\"',;:]+$", value) is not None


def build_email(fields):
    to = fields.get("to", "").strip()
    if not is_email(to):
        return fail("type an address, such as shop@example.com")
    text = "mailto:" + urllib.parse.quote(to, safe="@+")
    query = []
    for key, name in (("subject", "subject"), ("body", "body")):
        value = fields.get(key, "").strip()
        if value != "":
            query.append(name + "=" + urllib.parse.quote(value.replace("\r\n", "\n").replace("\n", "\r\n"), safe=""))
    if len(query) > 0:
        text = text + "?" + "&".join(query)
    return ok_result((text, "email-" + to))


def build_phone(fields):
    number = clean_number(fields.get("number", ""))
    if number == "":
        return fail("type a number, such as +1 555 0100")
    return ok_result(("tel:" + number, "phone-" + number))


def build_text(fields):
    number = clean_number(fields.get("number", ""))
    if number == "":
        return fail("type a number, such as +1 555 0100")
    return ok_result(("SMSTO:" + number + ":" + fields.get("message", "").strip(), "text-" + number))


BUILDERS = {"wifi": build_wifi, "contact": build_contact, "event": build_event, "place": build_place,
            "email": build_email, "phone": build_phone, "text": build_text}


def build(kind, fields):
    """A code of a kind from the form's fields -> Result Payload."""
    if kind not in BUILDERS:
        return fail("unknown kind of code")
    built = BUILDERS[kind](clean_fields(fields))
    if not built["ok"]:
        return built
    text, name = built["value"]
    stored, masked = stored_form(text)
    return ok_result({"kind": kind, "text": text, "stored": stored, "masked": masked, "name": name})


def one_line(text):
    """A payload for showing on one line: its line breaks as " / "."""
    return text.replace("\r\n", "\n").rstrip("\n").replace("\n", " / ")


def kind_of(text):
    """Which kind of code a text is -> one of KINDS, or "" for plain text."""
    lowered = text.strip().lower()
    for prefix, kind in (("http://", "link"), ("https://", "link"), ("wifi:", "wifi"), ("begin:vcard", "contact"),
                         ("begin:vevent", "event"), ("begin:vcalendar", "event"), ("geo:", "place"),
                         ("mailto:", "email"), ("tel:", "phone"), ("smsto:", "text"), ("sms:", "text")):
        if lowered.startswith(prefix):
            return kind
    return ""

# ==== stamp v1 | author=kjFriday | hmac-sha256=5eebd9fdb65de1bc0a88398093ec96ef5be07f8ea1fbb51eed4890507d30e5a4 ====
