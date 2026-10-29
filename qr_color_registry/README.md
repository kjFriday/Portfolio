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
| Make | Type a link (or build it with *From template…*), then pick a color from the board. The board shows the 118 cube colors dark enough to scan, best first for the chosen preset and your votes. **Good** / **Bad** vote on the picked color (one vote per color; press it again to take it back). Tick **Short link** to print a short address instead of the link (see below). *Save PNG…* or *Save SVG…* writes the code, reads the file back to prove it scans, and registers it. |
| Read | Open or paste a picture of a QR code. It shows the text, the color it detects, and the codes in the registry that hold the same text. *Register this picture…* adds a PNG or SVG made elsewhere, in the color you confirm. |
| Find | Find by **QR code** (a link, words in it, a short-link ID, a file path, or a picture) or by **Color** (`#rrggbb`, "near", or a family such as blue). Each result shows the color, the link, the path and whether the file is still there. From there: open the picture, show it in its folder, copy the path or link, open the link, send a short link somewhere else (*Change destination…*), or forget the record (the file stays). The **Ask** row asks in plain English through a local model you pick. |

*File → Import votes from Color Voats…* brings in Color Voats' votes, with the newer vote winning for each color, so
importing again changes nothing.

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
- **Publish with any static web host.** *File → Export local redirect pages…* and *Export nonlocal redirect
  pages…* (or `--export-redirects DIR --section local|nonlocal`) write one small page per ID that forwards to its
  destination, plus `index.html`, `404.html` and a `robots.txt` that keeps the pages out of search engines. Export
  again after a change.
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
- **Trying local codes.** Export the local pages, then serve that folder from this computer:

  ```bash
  python -m http.server 8000 --bind 127.0.0.1 --directory "C:\path\to\local pages"
  ```

  `LOCALHOST` only works in this computer's own browser. For phones on the same Wi-Fi, set the local base to this
  computer's network address (`ipconfig` shows it), such as `HTTP://192.168.1.20:8000/`, and leave out
  `--bind 127.0.0.1`; Windows may ask to let Python through its firewall. Stop the server with Ctrl+C when done.
- **Nonlocal must be an internet address.** A local name or address there (`LOCALHOST`, `192.168.…`,
  `….LOCAL`) is refused with a warning, so printed codes never point at your own network by mistake. Use a domain
  or subdomain you control and will keep: every printed code depends on it, and whoever owned a lapsed domain could
  send your codes anywhere. `GO.EXAMPLE.COM` is only a placeholder, and the window says so.

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
| `votes` | one Good or Bad vote per color |

The schema is version 2 (version 1 had no `short_links`). The window moves a version 1 registry to version 2 the
first time it opens it; read-only readers, such as ECP, read either.

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
| `planner.json` | How a question in plain English becomes a query plan: what the local model is told, the worked examples it is shown, the words for color families ("navy" is blue) and the filler words taken off the ends of links and paths. `settings.json` can point to your own copy. |
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
| `ecp_query` | answers a question (`prompt`) with the matching codes: color, link (`payload_url`) and picture path (`file_path`); pass the `model_id` |

- **How a question is answered:** the chosen model only turns the question into a query plan. The plan is checked
  against the question's own words before it runs, then runs on a read-only connection. The model never writes
  SQL, never sees the stored data, and never makes a file be opened. A color code, a whole link or a file path
  needs no model at all.
- **Choosing a model:** nothing is remembered between calls. Pass the `model_id` on every query, or set a default
  with `inference.model` (or `--model NAME`). If the model's digest changes, queries say so instead of using it.
- **Failures** come back as tool results marked `isError`, with a `kind` such as `model_not_local` or
  `cloud_not_disabled` and a `detail` ([ECP.md](ECP.md) §11).
- **Answers are data:** every answer is labelled `untrusted-db-content`. Links and paths are cleaned of hidden
  characters and capped. Do not pass them on to another tool as instructions.
- **Audit log:** every call adds a line to `audit.jsonl`, chained by SHA-256, with hashes of the prompt and the
  planner and the plan as it ran, never the prompt itself.

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
