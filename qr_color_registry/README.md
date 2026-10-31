# Generic Company QR Palette

QR codes in recommended colors, and a registry that finds any of them again. QR Palette combines
[QR Studio](../qr_code_studio/README.md)'s QR codec with [Color Voats](../color_tile_recommender/README.md)'
color ranking:

- **Make:** draw a link as a QR code in one of the colors ranked for you.
- **Remember:** record each code's link, color and the path of its picture file in a relational SQLite registry.
- **Find:** look a code up by its QR code (the link, its file, or a picture of it) or by its color. Every answer gives
  the color, the link and the path of the picture.

Other programs can query the registry through the **Environment Context Protocol (ECP)**, an MCP server with three
tools, specified in [ECP.md](ECP.md). A client picks a **local model** first; inference never leaves this
computer, and every call is written to a hash-chained audit log.

Python 3.10+, standard library only.

```bash
python qr_palette.py
```

```bash
python -m unittest discover -p "test_*.py"
```

`--selftest` runs a quick built-in check, `--version` prints the version, and `--smoke FILE` opens the window on a
scratch registry, makes and finds a code, writes a JSON report and closes. `--export-redirects DIR` writes the
redirect pages of the short-link section in use (or `--section local|nonlocal`) into `DIR` and exits.

## What it does

| Tab | What |
|---|---|
| Make | Choose a **Kind** (a web link, or see "More kinds of code" below). Type a link (or build it with *From template…*), then pick a color from the board. The board shows the 118 cube colors dark enough to scan, best first for the chosen preset and your votes. **Good** / **Bad** vote on the picked color (one vote per color; press it again to take it back). Tick **Short link** to print a short address instead of the link (see below). *Save PNG…* or *Save SVG…* writes the code, reads the file back to prove it scans, and registers it. *Print size…* says how wide to print it for a scanning distance, *Test robustness* how much wear it survives, and *Logo…* puts a small picture in its middle (see below). |
| Read | Open or paste a picture of a QR code. It shows the text, the color it detects, and the codes in the registry that hold the same text. *Register this picture…* adds a PNG or SVG made elsewhere, in the color you confirm. |
| Find | Find by **QR code** (a link, words in it, a short-link ID, a file path, or a picture) or by **Color** (`#rrggbb`, "near", or a family such as blue). Each result shows the color, the link, the path and whether the file is still there. From there: open the picture, show it in its folder, copy the path or link, or open the link. Pick several results (Ctrl+click or Shift+click) and *Change destination…* sends their short links somewhere else, *Redraw…* draws them again in another color or size over their own files (each read back first), *Forget record* removes them from the registry (the files stay), and *Print sheet…* lays them out on labels or posters (see below). *History…* shows where a short link has gone, and schedules where it goes next. The **Scans** column shows a short link's scans, in all and in the last 30 days. The **Ask** row asks in plain English through a local model you pick. |

*File → Import votes from Color Voats…* brings in Color Voats' votes, with the newer vote winning for each color, so
importing again changes nothing. The rest of the File menu: *Make from a list…* and *Import scans…* (below), exporting,
publishing and serving the redirect pages (below), *Back up the registry…*, *Export the registry (CSV or JSON)…*, *Audit log…*
and *Open settings.json*.

The window runs one slow task at a time and queues the rest, so Save or Find asked for while a model loads simply
waits its turn.

### Print size

*Print size…* in the Make tab takes the printed width of the picture and the scanning distance, and for each
error-correction level gives the code's version, the module size, whether it is big enough, the smallest width
that is, and how tall the printed address's letters come out. The rules of thumb: a module of at least 0.4 mm to
print well, and the code at least a tenth as wide as the distance (a module at least 1/250 of it); address letters
under 1.5 mm are flagged as hard to read. They are guidance, not guarantees: try a print before printing a batch.

### Test robustness

*Test robustness* in the Make tab wears the code in the preview ten ways and decodes each result, as a job since the
decoder is plain Python: shrunk to half and to a third, a light and a heavy blur, light and heavy noise, tilted 5
degrees, low and very low contrast, and a covered corner. It answers like "8 of 10 passed; failed: shrunk to a
third, heavy blur". The tests are fixed (the noise is seeded), so the same code always scores the same and two
choices can be compared. Darker colors and more error correction usually score better. It is a comparison, not a
promise about a particular phone.

### A logo in the middle

*Logo…* in the Make tab picks a small picture (up to 1024 pixels a side) to draw in the middle of the code, in a
square with a white margin. The code becomes level H, the most error correction (and the level box locks there until
*No logo*).
- **How big:** the square is the largest of 15%, 12% or 9% of the modules whose code still reads with those modules
  blank, at the smallest version that fits or one larger. It never covers the finder patterns, the timing patterns,
  or the format and version information. If no square reads, the logo is refused.
- **Proof:** as with every code, the saved file is read back before it is registered; a logo that spoils it is
  refused, and the file removed.
- **Files:** a PNG with a logo is truecolor. In an SVG the code stays the first path, and the logo follows as small
  squares, with colors cut to 4 bits a channel.
- **Short links help:** a short address at level H is still small.
- **The registry does not keep the logo.** So *Redraw…* refuses such a code rather than lose the logo from its file, and
  *Print sheet…* and Find's preview draw the code without it, and say so. *Print size…* gives only level H.

### Print sheets

Select codes in Find, then *Print sheet…*: choose a layout and a file, and it opens when done.
- **Layouts** are in `sheets.json` beside the program, read each time: A4 labels 3 × 8 (70 × 37 mm), US Letter labels
  3 × 10 (2 5/8 × 1 inch, the common 5160 layout), and one poster per A4 or US Letter page. Each gives the page
  size, margins, columns, rows, cell size, gutter, and whether to print the label. Add your own.
- **What is printed:** each code is drawn again from what it holds, as large as its cell allows with its quiet zone,
  with its short address under it when it has one. If a code's modules come out under 0.4 mm on that layout, the window
  says so: pick a larger layout or a shorter link.
- **Files:** a PDF (PDF 1.4 written by this program: only filled rectangles, so no fonts or images, and the same
  codes always give the same bytes) or SVG drawings sized in millimetres, one per page (`name.svg`, `name-2.svg`, …).

### A whole print run from a list

*File → Make from a list…* makes one code for every row of a CSV whose first row names its columns: `link` and
`color`, and optionally `label` and `file`, in any order. Spreadsheets' own CSVs work: UTF-8 with or without a
byte-order mark, or Windows-1252, separated by commas, semicolons or tabs.

```text
link,color,label,file
https://shop.example.com/p/blue-mug,#3366cc,Blue mug,
https://shop.example.com/p/green-mug,#006633,Green mug,green.svg
```

- **First the count:** choosing the file says how many rows are ready and which have a problem. Then pick a folder,
  PNG or SVG, and whether to print short links (and which section). The error-correction level is the Make tab's.
- **Names:** a row's `file` column (a plain file name; a path is refused, so a list can never write outside the
  folder), else its label and the suggested name. **Nothing is overwritten:** a name already there gets `-2`, `-3`.
- **Skipped, with the reason:** a row with no link or no color, a row the same as an earlier one, and a color too light
  to scan. Tick the box to use the nearest color that scans instead (by OKLab distance), which the report notes.
- **Short links** follow the usual rule: the same destination in the same color shares its ID.
- **Report:** `made-DATE-TIME.csv` beside the pictures says what happened to every row. *Stop* in the dialog stops after
  the current code, and the report says which rows were not made.

### More kinds of code

The **Kind** box in the Make tab swaps the Link box for a small form. The preview and the note below it show what
the code will hold. Short links and templates are for web links only.

| Kind | The code holds | Opens |
|---|---|---|
| Wi-Fi join | `WIFI:T:WPA;S:name;P:password;;` (with `\ ; , : "` escaped) | joins the network |
| Contact card | a vCard 3.0 | adds a contact |
| Calendar event | an iCalendar `VEVENT`, with its times as typed, on the phone's own clock | adds an event |
| Map location | `geo:52.37,4.89` | opens a map |
| Email | `mailto:…?subject=…&body=…` | starts an email |
| Phone call | `tel:+15550100` | starts a call |
| Text message | `SMSTO:+15550100:message` | starts a text message |

**A Wi-Fi password is never stored in the registry.** It goes into the code and its picture file, so **anyone who can
see the code or the file can join the network**: print it only where that is what you want. This applies to
however a Wi-Fi code arrives: made in the form, typed in the Link box, in a list of codes, or registered from a picture.
- **What is kept:** the text with the password masked (always the same length, so it says nothing about the password),
  and a keyed hash of the real text, so scanning or opening the code in the Read tab still finds its record. The hash
  uses a key in `qr_palette.key` beside the registry, not a plain SHA-256, because Wi-Fi passwords are often weak
  enough to guess: without the key, the registry file or a backup cannot be used to try passwords.
- **What follows:** exports, reports, file names, ECP's answers and the Print size dialog only ever see the masked text. Find
  has no preview of such a code, and *Redraw…* refuses it, since the registry cannot draw it again; make it again in
  the Make tab. *Print sheet…* reads the real text from the picture file, and leaves the code out if the file is gone.
- **The key:** made the first time it is needed. Back it up with the registry if you move to another computer. Without
  it nothing breaks, but these codes are no longer found by scanning them.

### Scans

*File → Import scans…* reads how often your short links were opened, and Find shows it per code: in all, and in the
last 30 days. Only a short link's ID, a day and a count are kept: never an address, a user agent or anything else.
- **An analytics report:** a CSV with a date column (`YYYY-MM-DD` or `YYYYMMDD`), a column with the `utm_content` tag
  the redirect pages add (`ID-color`, such as `73491205-3366cc`) and a count column (`count`, `sessions`, `views`,
  `clicks`, …). A newer report corrects the days it covers.
- **A web server's access log:** Common or Combined Log Format, or gzipped. `GET /ID/` or `/ID` with a 2xx or 3xx status
  counts, per day as the log dates it. A log that grew or was rotated imports over itself; a new log file adds to it.
- **Importing the same file twice changes nothing,** and IDs that are not short links here are named and left out.
- **Scans can feed the ranking.** Turn on `colors.scans_vote` and choose the `scans` preset (colors like your Good votes,
  then colors whose codes get scanned): a color scores its scans per short link, pulled down a little for colors with
  few links (`weights/scans.json`). It is off by default, and presets that do not name the `scans` algo never change.

Scans measure what each file counts: a page view is not always a person, and a scanner that blocks tracking tags is
not in an analytics report.

### Keeping your data

- **Backups.** *File → Back up the registry…* copies `palette.db` with SQLite's own backup, consistent even while
  the window writes, into a new file (by default `backups\palette-DATE-TIME.db` in the data folder), and checks the
  copy before saying it is done. To restore one, close the window and copy it over `palette.db`. `qr_palette.key`
  (see "More kinds of code") is not in a backup, on purpose: keep a copy of it somewhere else.
- **Exports.** *File → Export the registry (CSV or JSON)…* writes a CSV with one row per code (color, link,
  destination, short-link ID and section, path, format, level, version, when, scans, whether a password is masked,
  whether it has a logo) for spreadsheets, with a byte-order mark so they read it as UTF-8, or a JSON file with
  everything: codes, short links with their history, schedules and scans, and votes. A CSV cell that
  starts with `=`, `+`, `-` or `@` gets a leading apostrophe, so a spreadsheet never runs a link as a formula.

## Short links: print once, change where it goes later

With **Short link** ticked, the code holds a short address such as `HTTPS://GO.EXAMPLE.COM/73491205` instead of
the link itself, and that address is printed under the code for anyone whose camera cannot scan it.
- **Smaller codes.** The address is all capitals and digits, which QR codes store in their compact
  alphanumeric mode: `https://shop.example.com/hours` needs a 29×29 code at level M, the short address 25×25.
- **IDs you can type.** Seven random digits and a check digit (the Damm algorithm), so a mistyped ID is caught.
  Digits have no upper or lower case, which web hosts would treat as different pages.
- **One ID per link and color.** A PNG and an SVG of the same code share their ID; the same link in another
  color gets its own, so scans can be told apart by color.
- **Change destinations without reprinting.** *Change destination…* in Find sends a short link somewhere else.
  The pictures stay as they are, and forgetting a picture keeps its short link, since printed copies still use it.
- **Never lose where it used to go.** *History…* in Find lists every change. *Undo last change* sends it back, which
  is written in the history too.
- **Change it on a date.** *Schedule a change…* in *History…* takes a day and a destination. Exports use the destination
  in force on the day they run, even before the change is applied. When the window starts, it offers to apply
  changes that are due. Either way, export again on that day to publish it: nothing runs while the window is closed.
- **Publish with any static web host.** *File → Export local redirect pages…* and *Export nonlocal redirect
  pages…* (or `--export-redirects DIR --section local|nonlocal`) write one small page per ID that forwards to its
  destination, plus `index.html`, `404.html` and a `robots.txt` that keeps the pages out of search engines. Export
  again after a change.
- **Or publish them in one step.** *File → Publish nonlocal pages…* (below) writes them where `links.json` says, shows what
  would change first, and asks.
- **Tags in the page, not in the code.** The tracking tags in `links.json` (by default
  `utm_source=qr&utm_medium=print&utm_content=ID-color`) are added to each destination when the pages are written,
  so the code stays small. A link's own tags are never replaced.
- **Templates.** *From template…* builds a link from a pattern in `links.json`, such as
  `https://shop.example.com/p/{item}`, with each field filled in and encoded.

### Local and nonlocal

`links.json` has two sections of short links, each with its own base address and export folder. The two buttons
beside **Short link** switch between them (choosing one ticks Short link), and `settings.json` remembers the choice
as `links.use`. The Find tab marks each short link local or nonlocal.

| Section | For | Default base |
|---|---|---|
| `local` | trying codes before you have a domain: they work on this computer, or on your own network | `HTTP://LOCALHOST:8000/` |
| `nonlocal` | codes you print for everyone: an internet address on a domain of your own | `HTTPS://GO.EXAMPLE.COM/` (a placeholder) |

- **A code keeps its address.** Switching changes which address new codes print, and which pages each Export
  writes; a code already made stays local or nonlocal. The same link in the same color gets one ID in each section.
- **Trying local codes.** *File → Serve local pages* exports the local pages (into `links.json`'s local export
  folder, or `local pages` in the data folder) and serves them from this computer at the local base, until you
  choose *Stop serving local pages* or close the window. While they are served, they are written again after every
  local short link you save or send somewhere else. The server only answers GET and HEAD for files in that
  folder, never lists files, and logs nothing.

  `LOCALHOST` only works in this computer's own browser, and then the server listens to this computer alone. For
  phones on the same Wi-Fi, set the local base to this computer's network address (`ipconfig` shows it), such as
  `HTTP://192.168.1.20:8000/`; the window then asks before letting your network in, and Windows may ask to let
  Python through its firewall. To serve an exported folder without the window:

  ```bash
  python -m http.server 8000 --bind 127.0.0.1 --directory "C:\path\to\local pages"
  ```
- **Nonlocal must be an internet address.** A local name or address there (`LOCALHOST`, `192.168.…`,
  `….LOCAL`) is refused with a warning, so printed codes never point at your own network by mistake. Use a domain
  or subdomain you control and will keep: every printed code depends on it, and whoever owned a lapsed domain could
  send your codes anywhere. `GO.EXAMPLE.COM` is only a placeholder, and the window says so.

### Publishing the nonlocal pages

*File → Publish nonlocal pages…* publishes without copying files by hand. Say where in `links.json`, under `nonlocal`:

```json
"publish": {"kind": "git", "folder": "C:\\path\\to\\the\\repository"}
```

- **`git`:** a folder in a Git repository, such as one GitHub Pages serves. `CNAME` (the base's host) and `.nojekyll` are
  written too, and the pages are committed and pushed.
- **`folder`:** a folder something else syncs. The pages are written there, and that is all.
- **You see it first.** It lists the pages it would add, change and remove, with nothing touched, and asks. If nothing
  changed, it says so.
- **It touches only its own pages.** A page is removed only when its short link is gone, and only an ID-named folder's
  `index.html`. A commit holds only those pages: whatever else is staged or lying in that repository stays as it is.
- **A push is never forced.** If it fails (the remote has moved on, or Git has no credentials here), the commit stays and
  the window repeats what Git said, so you can push it with your own Git client. Git is never left waiting for a password.
- **Uses the day in force:** a change scheduled for today or earlier goes out even if it has not been applied yet.

## Colors

- **Which colors:** the 216 colors of the 6×6×6 cube, named the way Color Voats names them ("Dark teal",
  "Light grey").
- **Which ones scan:** a code is drawn in its color on white. Only colors with a WCAG contrast of at least 3:1
  against white are offered: 118 of the 216. The comparison is exact, so `#0099ff` at 2.9998 is out.
- **Proof:** every one of the 118 is read back by the decoder in the tests, and every saved file is read back
  before it is registered.
- **Ranking:** Color Voats' algos rank the board, driven by plain JSON files.
  - The presets in `presets/` are mixer (the default), balanced, popular and discover. Add your own by copying
    one.
  - The weights in `weights/` tune each algo.
  - Each file starts with an `about` text that explains it. An edit applies the next time the board is ranked.

## The registry

`%LOCALAPPDATA%\Generic Company Inc\GenericCompany.QRPalette\palette.db` (or `--db FILE`). It belongs to this program
alone, not to the Generic Company hub, and every open checks its SQLite application id and schema version.

| Table | Holds |
|---|---|
| `colors` | every color used: hex, RGB, cube index (none for off-cube colors), name and family; the 216 cube colors are there from the start |
| `links` | the text each QR code holds |
| `qr_codes` | one row per picture file: its path, its link, its color, PNG or SVG, error-correction level, QR version, made here or registered, and when |
| `short_links` | one row per short link: its ID, the link row of the address it prints, the color it was made in, where it sends people, and when it was made and last changed |
| `short_link_changes` | a short link's history: where it went, where it goes after, and when |
| `scheduled_changes` | changes to come: which short link, where to, from which day, and when it was applied |
| `scans` | a short link's scans per day and source: only counts |
| `votes` | one Good or Bad vote per color |

`qr_codes` also keeps `payload_hash` for a code whose text is masked (see "More kinds of code"), and `has_logo` for one
drawn with a logo.

The schema is version 3 (version 2 added `short_links`, version 3 added the rest above). The window moves an older
registry to version 3 the first time it opens it, after keeping a checked copy beside it (`palette-v2.db`), since older
versions of this program cannot open version 3. Read-only readers, such as ECP, read any of them. Version 3 only adds:
other programs that read the older tables and columns, such as Data Bridge, read them as before.

The registry holds data only; every setting is in `settings.json` (below).
- **Pictures:** saved where you choose, by default in your Pictures folder under `QR Palette`. If Windows keeps
  Pictures in OneDrive, OneDrive syncs them.
- **Uninstalling:** removes the registry, `settings.json` and the audit log, but never the pictures.
- **ECP:** opens the registry read-only, behind an allow-list of tables, columns and functions, with SQLite's
  hardening settings and a time limit ([ECP.md](ECP.md) §10). Only the window writes.

## Settings: all plain JSON

Everything you may change is a human-readable JSON file: indented, one setting per line, with an `about` text in each
section. *File → Open settings.json* opens yours.

| File | What it sets |
|---|---|
| `settings.json` | Where things are and how the program behaves. It lives next to the registry in `%LOCALAPPDATA%\Generic Company Inc\GenericCompany.QRPalette\` (or `--settings FILE`). The window writes it with every setting and its default the first time it runs. `settings.example.json` shows the same defaults. |
| `presets/*.json` | Which algos rank the colors, and how they are mixed. |
| `weights/*.json` | The numbers each algo uses. |
| `qr_palette.key` | Not a setting: a secret beside the registry, made on first need (see "More kinds of code"). It is never in `settings.json` or the registry. |
| `sheets.json` | The layouts of *Print sheet…*: page, margins, columns, rows, cell, gutter and label, in millimetres. Read each time you print. |
| `planner.json` | How a question in plain English becomes a query plan: what the local model is told, the worked examples it is shown, the words for color families ("navy" is blue), the words that name a section of short links or ask for short links, and the filler words taken off the ends of links and paths. `settings.json` can point to your own copy. A copy written before `section` and `short` existed still works. |
| `links.json` | Short links: two sections, `local` and `nonlocal`, each with a base address (in capitals, ending in `/`) and the folder its exports start in; and, for both, the number of random digits per ID (4-12, default 7), whether **Short link** starts ticked, the tags added to destinations (`{id}` and `{hex}` are filled in) and the link templates (`{name}` is a field). `settings.json` can point to your own copy. |

`settings.json`, section by section:

| Setting | Default | What it does |
|---|---|---|
| `registry` | `""` | the registry file; empty means `palette.db` in the data folder |
| `pictures.folder` | `""` | where new codes are saved; empty means Pictures\QR Palette |
| `pictures.pixels_per_module` | `8` | PNG scale, 1-40 |
| `pictures.error_correction` | `"M"` | L, M, Q or H for new codes |
| `colors.preset` | `"mixer"` | the preset that ranks the board, recommendations and ranks in answers |
| `colors.minimum_contrast` | `3.0` | contrast against white a color needs to be offered (4.5 keeps 77 colors) |
| `colors.near_distance` | `0.08` | how close in OKLab counts as "near" a color |
| `colors.rankings_folder` | `""` | the folder holding `presets/` and `weights/`; empty means beside the program |
| `inference.url` | `"http://127.0.0.1:11434"` | the local model server; loopback only |
| `inference.model` | `""` | the default model for queries that name none, and the one the window selects at start |
| `inference.require_cloud_disabled` | `true` | refuse to plan unless Ollama reports its cloud features off (`OLLAMA_NO_CLOUD=1`) |
| `inference.timeout_seconds` | `45` | how long a model may plan for `--mcp` |
| `inference.window_timeout_seconds` | `300` | the same for the window's Ask |
| `inference.list_timeout_seconds` | `3` | how long listing models may take |
| `inference.max_answer_tokens` / `retry_answer_tokens` | `256` / `512` | the most a model may write for one plan, and for the one retry when it is cut off |
| `inference.context_tokens` | `4096` | the model's context size for planning |
| `inference.keep_alive` | `"10m"` | how long the server keeps the model loaded |
| `planner.file` | `""` | your own planner file; empty means `planner.json` beside the program |
| `links.file` | `""` | your own short-link file; empty means `links.json` beside the program |
| `links.use` | `"local"` | which section new short links use, `local` or `nonlocal`; the Make tab switches it |
| `queries.default_limit` / `max_limit` | `20` / `100` | results per answer, and the most a plan may ask for |
| `queries.question_characters` | `2000` | the longest question |
| `queries.statement_seconds` | `2` | how long one read of the registry may take before it is stopped |
| `protocol.max_message_bytes` | `1048576` | the longest MCP message line |
| `protocol.rate_per_second` / `rate_burst` | `1` / `5` | tool calls allowed per second, and in a burst |
| `protocol.max_field_characters` / `max_result_characters` | `256` / `40000` | the most of a link or path in an answer, and of a whole answer |
| `audit.file` | `""` | the audit log; empty means `audit.jsonl` in the data folder |

How settings are read:
- **Bad values.** A setting that is left out, or has the wrong kind of value, uses its default. The window
  lists what it could not use when it starts; `--mcp` prints it on standard error.
- **Broken files.** A file that is not valid JSON is never overwritten.
- **What the window writes.** It changes only the preset, the model and the picture folder, and keeps
  everything else in the file as you wrote it.
- **Overrides.** Command-line options (`--db`, `--inference`, `--inference-timeout`, `--model`) override
  `settings.json` for one run.

## ECP: the MCP server

```bash
python qr_palette.py --mcp
```

`--mcp` (or `--ecp`, the same) serves ECP on stdin/stdout to MCP clients of both eras: `initialize`
(2025-11-25) and `server/discover` (2026-07-28). It has three tools:

| Tool | What it does |
|---|---|
| `ecp_list_models` | lists the models local to this computer that can plan, each with its `model_id` (`name@digest`) |
| `ecp_select_model` | checks a model is local, pins its digest into a `model_id`, and loads it |
| `ecp_query` | answers a question (`prompt`) with the matching codes: color, link (`payload_url`), a short link's destination (`target_url`) and section (`section`), and picture path (`file_path`); pass the `model_id` |

- **How a question is answered:** the chosen model only turns the question into a query plan. The plan is checked
  against the question's own words before it runs, then runs on a read-only connection. The model never writes
  SQL, never sees the stored data, and never makes a file be opened. A color code, a whole link or a file path
  needs no model at all.
- **Questions about short links:** "my local codes", "codes with a short link that still point to the menu" and
  "blue codes on the nonlocal short links" are planned with `section` (local or nonlocal) and `short`. Each is kept
  only when the question says so in words (`section_words` and `short_words` in `planner.json`; "non-local" means
  nonlocal).
- **Choosing a model:** nothing is remembered between calls. Pass the `model_id` on every query, or set a default
  with `inference.model` (or `--model NAME`). If the model's digest changes, queries say so instead of using it.
- **Failures** come back as tool results marked `isError`, with a `kind` such as `model_not_local` or
  `cloud_not_disabled` and a `detail` ([ECP.md](ECP.md) §11).
- **Answers are data:** every answer is labelled `untrusted-db-content`. Links and paths are cleaned of hidden
  characters and capped. Do not pass them on to another tool as instructions.
- **Audit log:** every call adds a line to `audit.jsonl`, chained by SHA-256, with hashes of the prompt and the
  planner and the plan as it ran, never the prompt itself. An anchor beside it (`audit.jsonl.anchor`) records the
  last line, so lines cut off the end show too. *File → Audit log…* lists the lines newest first, checks the chain,
  and copies the last line's fingerprint for you to keep somewhere else; *Check a kept fingerprint…* compares the
  log with it later, which still works if someone rewrote the anchor as well.

To add it to Claude Code, use `python.exe` (not `pythonw`) and your own path to the file:

```bash
claude mcp add qr-palette -- python "C:\path\to\qr_color_registry\qr_palette.py" --mcp
```

Local inference means Ollama on this computer:
- **Address:** `inference.url` in `settings.json` (or `--inference URL`); the default is
  `http://127.0.0.1:11434`. It must be `127.0.0.x`, `::1` or `localhost`. Names are never looked up, proxies are
  never used and redirects are refused.
- **Cloud features off:** a signed-in Ollama can run some models on another computer, from the same local port.
  Cloud and remote models are never listed or used, and a question that needs the model is refused
  (`cloud_not_disabled`) until Ollama reports its cloud features off. To turn them off, set the environment
  variable `OLLAMA_NO_CLOUD=1` for the Ollama server and restart it. If you accept the risk, set
  `inference.require_cloud_disabled` to `false` instead.
- **Timeouts:** `inference.timeout_seconds` and `window_timeout_seconds` (or `--inference-timeout S`) set how long
  a model may take to plan: 45 s for `--mcp`, 300 s in the window. Once loaded, qwen2.5:7b-instruct and
  deepseek-r1:7b each plan a question in about a second here.

Answers do leave this program: whatever an MCP client receives (links, paths, colors) goes to the model that client
runs, which may be remote. ECP keeps its own inference local; it cannot decide where its answers go next.

## Porting to another language

Same layout as QR Studio and Color Voats:
- **Plain code:** plain functions and records, explicit loops, and failures as Result records.
- **Separate parts:** each module is its own part: codec, colors, registry, short links, local inference, ECP,
  MCP server, audit log.
- **The window:** it only calls those.
- **Order:** port `qr_codec.py` first, then `swatch.py` and `registry.py`, each with its tests.

## Icon

`icon/qr-palette-16.png`, drawn for this project: QR Studio's glyph with its data modules in Color Voats' tile colors,
enlarged by whole pixels with `tools/pixel_icons.py`. See [icon/README.md](icon/README.md).

## License

AGPL-3.0 (see [LICENSE](LICENSE)). Reused code is listed in [PROVENANCE.md](PROVENANCE.md).
