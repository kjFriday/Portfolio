# QR Palette: handoff for features 6-15

Ten proposed features, written so that another session or developer can pick any one up without this
conversation. Features 1-5 (serving local pages, backup and CSV/JSON export, the print-size advisor, bulk
actions in Find, the audit log viewer with an outside anchor) are built and on main; see the LOG.

Started: features 15 (done) and 12, 7 and 10 (their core) are on branch `worktree-qr-palette-6-15`, not yet on
main. Check that branch and the LOG before starting, so as not to redo them.

## What to read first

| File | What it is |
|---|---|
| `README.md` | What the program does, every setting, short links (local and nonlocal) |
| `ECP.md` | The Environment Context Protocol: the MCP server, planning, the read-only rail, the audit log |
| `qr_palette.py` | Identity, CORE (make, register, find, short links), SELF-TEST, GUI (`run_gui`), CLI (`main`) |
| `qr_codec.py` | QR encoder and decoder, PNG/SVG writers and readers, the caption font (`GLYPHS`) |
| `registry.py` | SQLite schema (version 2: `colors`, `links`, `qr_codes`, `short_links`, `votes`), the read-only rail |
| `shortlinks.py` | Short-link IDs (digits + Damm check digit), `links.json` (sections `local` and `nonlocal`), redirect pages |
| `ecp.py`, `mcp_server.py`, `local_inference.py`, `audit.py` | ECP's engine, MCP server, Ollama client, hash-chained audit log |
| `swatch.py`, `ranking.py`, `algos.py`, `presets/`, `weights/` | Colors: names, families, contrast, OKLab, ranking |
| `settings.py` | `settings.json`: every setting, its default, its check |

## Rules that hold for every feature

- **Python 3.10+, standard library only.** No packages. Plain functions and dict records, `Result` records
  `{"ok", "error", "value"}`, explicit loops, no argparse (`option_value`). Keep CORE free of tkinter.
- **The window runs slow work as jobs** (`start_job(label, work, done)`): one at a time, queued first come,
  first served. Never block the window's thread on disk, network or decoding.
- **Settings are human-readable JSON** with an `about` text per section. New settings go into `settings.py`
  (`DEFAULTS` and `SPEC`) or their own JSON file (like `links.json`, `planner.json`); a value that is missing or
  wrong falls back to its default with a warning, and a broken file is never overwritten. Shipped example
  files are generated from the defaults (`settings.example_text()`, `shortlinks.links_text()`), and tests check
  they match.
- **Local first.** Anything that touches the network is opt-in, explicit and visible; anything that publishes
  or pushes asks first. Inference stays on loopback (see `ECP.md` §9).
- **ECP stays read-only.** Nothing reachable over MCP writes the registry. New record or plan fields are
  additive; update `mcp_server.TOOLS` output schemas, `planner.json` if planning changes, and `ECP.md`.
- **The registry's marks.** `application_id` 0x51525041 stays in every schema (the user's decision). Data
  Bridge (branch `claude/heuristic-burnell-ac6b9d`, not yet merged) reads versions 1, 2 and 3 and refuses others.
  Its version 3 support was built from a description, before QR Palette's version 3 existed: it reads the same
  columns as version 2, and leaves out codes that hold no http(s) link. Keep those columns, or change both programs
  together, and make the one schema bump for all the features below that need it (8, 9 and possibly 11).
- **Examples are neutral:** `example.com` links, shops, menus, events. No payments, gift cards or anything
  that reads as an attack in examples or tests. Never write invisible or direction characters literally in
  source; build them with `chr()`.

## Definition of done (every feature)

1. Tests in the matching `test_*.py` (or a new one), passing with `python -m unittest discover -p "test_*.py"`
   twice on Python 3.14 and once on 3.11.
2. `python qr_palette.py --selftest` and `--smoke FILE` pass; window changes checked by driving the window and
   looking at a screenshot.
3. `README.md` updated (and `ECP.md` when ECP changes, `PROVENANCE.md` when code or a published design is reused,
   `setup.json` for new shipped files); a dated entry in the portfolio's `LOG.md`.
4. New source files staged with `git add -N`, then `python stamp.py --restamp <paths>` from the repository root,
   and `python stamp.py --check` clean.

## The features

### 6. Batch make

**Goal:** make a whole print run of codes in one go.

- **Sources:** a CSV (`link`, `color`, `label`, optional `file`), or Data Bridge's `bridge.db`
  (`SELECT link, hex, label FROM to_make WHERE kind = 'products'`, read on a read-only connection).
- **Window:** *File → Make from a list…*: pick the source, a folder, PNG or SVG, and whether to use short links
  (and which section). Show the row count first; run as one job; finish with a report of made and skipped rows,
  also written as a CSV beside the pictures.
- **Core:** `make_batch(db_path, rows, folder, kind, scale, short)` calling `make_qr` per row. File names from
  `suggested_name` plus the label; never overwrite (add `-2`, `-3`). A color that is not usable is skipped with
  its reason, or snapped to the nearest usable color by OKLab distance (`swatch.color_distance`) if the user
  ticks that.
- **Tests:** CSV with a byte-order mark, quotes and bad rows; duplicates; short-link reuse; a small STRICT
  `bridge.db` made in the test.
- **Effort:** medium. The `bridge.db` source waits for Data Bridge to be merged; the CSV source does not.

### 7. Print sheets

**Goal:** label sheets and posters, ready to print.

- **Layouts** in a new `sheets.json` (page size in mm, margins, columns, rows, cell size, gutter, whether to print
  the label), for example A4 3×8 and US Letter 3×10 labels, and one poster per page.
- **Output:** SVG, and PDF written by hand (PDF 1.4: modules and caption pixels as filled rectangles in the page
  content, so no fonts or images are needed; a correct `xref` table).
- **Window:** select codes in Find, then *Print sheet…*; choose a layout and a file; open it when done.
- **Tests:** cell placement for each layout; the PDF's structure (`xref` offsets, trailer, `%%EOF`); identical
  output for identical input.
- **Effort:** medium to large.

### 8. Scan analytics loop

**Goal:** see which codes and colors actually get scanned.

- **Import:** a CSV of scans per short-link ID (from an analytics export, using the `utm_content` tag `ID-color`
  that the redirect pages add), or a web server access log (count `GET /ID/` per day). Only counts are kept,
  never addresses or user agents.
- **Data:** a `scans` table (`code`, `day`, `count`, `source`, primary key on the first three, so importing the
  same file twice changes nothing): schema version 3 (see the rules above).
- **Window:** Find shows total and 30-day scans per code; optionally (`colors.scans_vote`, off by default) scans
  feed the color ranking as a new algo and weights file.
- **Tests:** both log formats, the UTM tag, importing twice.
- **Effort:** medium.

### 9. Destination history and scheduling

**Goal:** never lose where a short link used to go, and change it on a date.

- **Data:** `short_link_changes` (code, before, after, when) and `scheduled_changes` (code, target, from_day):
  schema version 3, together with feature 8.
- **Window:** the Find detail shows a short link's history with *Undo last change*; *Schedule a change…* takes a
  date and a destination. Exports use the destination in force on the export date; the window offers to apply
  due changes when it starts.
- **Tests:** history rows, undo, a schedule applied by date (pass "today" in, never read the clock in tests).
- **Effort:** medium.

### 10. Logo in the middle

**Goal:** a small logo in the center of a code that still scans.

- **Behavior:** *Logo…* in the Make tab picks a small PNG; it covers at most about 15% of the modules (well under
  level H's 30% recovery), with a white margin, and forces level H. A code that does not read back is refused.
- **Core:** in `qr_codec.py`, blank the logo's modules in the matrix, decode that (the honest test), and draw the
  logo over the blanked area in PNG and as squares in SVG (after the code's first path, which the SVG reader
  reads).
- **Tests:** read-back with a logo for a sample of usable colors; refusal when the logo is too big.
- **Effort:** medium. Short links make room for it: a short address at level H is still small.

### 11. More code types

**Goal:** codes that are not web links.

- **Kinds:** Wi-Fi join (`WIFI:T:WPA;S:…;P:…;;` with `\`, `;`, `,`, `:` and `"` escaped), contact card (vCard
  3.0), calendar event (iCalendar `VEVENT`), map location (`geo:`), email (`mailto:`), phone (`tel:`), text
  message (`SMSTO:`).
- **Window:** a *Kind* choice in the Make tab with a small form per kind and a payload preview.
- **Privacy:** a Wi-Fi password must not be stored in the registry. Store the payload with the password masked,
  plus a SHA-256 of the real payload so a scanned code still finds its record (a new column, so schema
  version 3).
- **Tests:** escaping, encode and read back for each kind, masking.
- **Effort:** medium.

### 12. Robustness score

**Goal:** know how much wear a code survives before printing it.

- **Core:** from the rendered picture (`qr_codec` Image record): shrink (50%, 33%), blur (3×3, 5×5), noise
  (a fixed seed), a small rotation, lower contrast, and a covered block; decode each with
  `qr_codec.decode_image`. Score = passed / tried, with the failures named.
- **Window:** *Test robustness* in the Make tab, as a job: "8 of 10 passed; failed: shrunk to a third, heavy
  blur".
- **Tests:** deterministic results for a fixed code; a code with more error correction scores at least as well.
- **Effort:** medium. Decoding is pure Python, so test at scale 4.

### 13. One-click publishing

**Goal:** publish the nonlocal redirect pages without copying files by hand.

- **Targets** (in `links.json`, `nonlocal.publish`): a Git repository folder (for example GitHub Pages; write
  `CNAME` with the base's host and `.nojekyll`), or a synced folder (just export there).
- **Behavior:** export, show what changed (pages added, changed, removed), then ask before committing and
  pushing. Never force-push.
- **Tests:** export into a temporary `git init` repository and check the commit; no push in tests.
- **Effort:** medium to large.

### 14. Tamper check for stickers

**Goal:** tell your printed codes from a sticker someone put over them.

- **IDs:** random digits, then a 2-digit tag (HMAC-SHA-256 with a local key, cut to two digits), then the Damm
  check digit. The key lives in its own file in the data folder, never in `settings.json` or the registry; IDs
  made before this have no tag and stay valid.
- **Read tab:** "made with your key", "a short link without a tag", or "not yours"; also warn when a scanned
  address's host looks like one of your bases but is not (one or two letters different).
- **Limits:** two digits make a forged tag right 1 time in 100; this catches casual swaps, it is not a
  cryptographic guarantee. Losing the key makes old tags unverifiable, never invalid.
- **Tests:** tags verify, the check digit still holds, lookalike hosts.
- **Effort:** medium.

### 15. Smarter questions about short links (ECP)

**Goal:** "codes that still point to the old menu", "my local codes", "codes with a short link".

- **Plan:** add `section` (`""`, `"local"`, `"nonlocal"`) and `short` (true for short-linked codes only) to the
  QueryPlan schema; grounding keeps them only when the question says so ("local", "short link", …). Records
  gain `section`.
- **Update:** `ecp.plan_schema`, `ecp.ground`, `planner.json` (rules and examples), `mcp_server.TOOLS`,
  `ECP.md` §7.4, §7.6, §8.2 and §16; still read-only.
- **Tests:** grounding of the new fields, direct plans, a live check with qwen2.5:7b-instruct.
- **Effort:** small to medium.

## Order and what can run side by side

Suggested order: 6, then 7 (together they handle a whole print run); 15; 12; 8 and 9 together (one schema
version 3); 10; 11; 13; 14.

Features that touch mostly separate files can be built side by side, each in its own worktree: 12
(`qr_codec.py`), 15 (`ecp.py`, `mcp_server.py`, `planner.json`), 7 (a new module plus a menu item), 13
(`shortlinks.py` plus a menu item). All of them add a little to `qr_palette.py`'s window code, so merge them
one at a time. Features 8, 9 and 11 change the schema: do them in one pass, and check the result against Data
Bridge, whose version 3 support has not yet met a real version 3 file.
