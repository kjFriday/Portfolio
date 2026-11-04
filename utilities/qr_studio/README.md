# Generic Company QR Studio

A desktop program that reads QR codes from pictures and makes new ones.

Self-contained: Python 3.10+ standard library only (tkinter for the window). The whole QR codec is written from scratch in the `qr_codec` package beside `qr_studio.py`: Reed-Solomon error correction, the encoder (numeric, alphanumeric and byte modes, versions 1–40, levels L/M/Q/H, mask scoring), and the reader (thresholding, finder-pattern search, alignment-pattern search, perspective sampling, format/version recovery and error correction). No imaging or barcode library is used.

```bash
python qr_studio.py
```

Tests, run in this folder:

```bash
python -m unittest discover -s tests
```

Command line, without the window:

```bash
python qr_studio.py --make "https://example.com" code.png
```

```bash
python qr_studio.py --read code.png
```

Also `--selftest` (quick checks), `--version` and `--smoke FILE`.

## What it does

| Tab | Actions |
|---|---|
| Read | Open a picture (PNG, GIF, PPM) or paste one from the clipboard (for screenshots). Finds the code even when turned, mirrored, tilted, noisy or unevenly lit, circles the three corner marks and shows the text, version, level and how many codewords were corrected. Copy the text; links (http/https only) open after you confirm. |
| Make | Type text or a link and see the code as you type. Choose the error-correction level and the pixels per module, then save as PNG or SVG, or copy the picture. |
| History | The last 50 codes read or made, newest first. Make again, copy, or clear. |

History is kept on this computer only, in `%LOCALAPPDATA%\Generic Company Inc\GenericCompany.QRStudio\history.json`. JPEG pictures can't be opened without an imaging library; paste them through the clipboard instead, or save them as PNG.

## How it works

1. `qr_studio.py` starts in `main`. It turns off `__pycache__` folders, then reads the command line with `option_value` (`studio_options.py`). The first of `--version`, `--selftest`, `--make` and `--read` wins; anything else opens the window.
2. `--make TEXT OUT` calls `encode_text` (`qr_codec/encode.py`: smallest version, level M, best mask) and writes the Matrix with `save_matrix` (`studio_history.py`) as PNG or SVG, 8 pixels per module.
3. `--read IMAGE` loads the file with `load_image_file` (`qr_codec/images.py`, PNG, PGM or PPM) and finds the code with `decode_image` (`qr_codec/locate.py`: `binarize`, finder and alignment search, sampling, then `decode_matrix` in `decode.py`). It prints the text.
4. Otherwise `run_gui` imports `studio_gui.py` (only now is tkinter loaded) and runs `StudioWindow`. It loads the history, then builds the menu, the Read, Make and History tabs and the status line.
5. Read: Open or Paste picture (`studio_clipboard.py` saves the clipboard picture to a temp PNG through PowerShell) -> `read_path` -> `decode_image` on a worker thread -> `poll_job` -> `finish_read` shows the text and circles the corners.
6. Make: each keystroke schedules `refresh_preview`, which calls `encode_text`; Save writes through `save_matrix`, Copy picture through `png_to_clipboard`.
7. Every code read, saved or copied goes through `remember` -> `add_history` -> `save_history`.

Where state lives:

| What | Where |
|---|---|
| History (at most 50 entries) | `history.json` in `%LOCALAPPDATA%\Generic Company Inc\GenericCompany.QRStudio`, read and written only by `studio_history.py` |
| Version | `__version__` in `qr_studio.py` and `"version"` in `setup.json` |
| Pasted and copied pictures | temp PNG files, handed to and from PowerShell |

There is no database, registry key or settings file. The window remembers nothing else between runs.

## Code map

In reading order, entry point first.

| File | What it holds |
|---|---|
| `qr_studio.py` | The entry point: the version, `main` and the command line (`--make`, `--read`) |
| `studio_options.py` | `option_value`, which reads the command line (the self-test checks it too) |
| `qr_codec/__init__.py` | The codec's map: its chapters, its records (Result, Image, Matrix, Reading) and the names it exports |
| `qr_codec/records.py` | Result records: `ok_result` and `fail` |
| `qr_codec/gf.py` | GF(256) arithmetic |
| `qr_codec/reed_solomon.py` | Reed-Solomon codewords (`rs_remainder`) and repairs (`rs_correct`) |
| `qr_codec/tables.py` | Levels, version tables, function patterns, data order, masks |
| `qr_codec/blocks.py` | Data split into blocks and interleaved, and back |
| `qr_codec/encode.py` | Text -> Matrix: `encode_text` |
| `qr_codec/decode.py` | Matrix -> text: `decode_matrix` |
| `qr_codec/images.py` | The Image record; PNG and PGM/PPM reading, PNG and SVG writing |
| `qr_codec/binarize.py` | Gray -> dark and light |
| `qr_codec/locate.py` | Finding a code in a picture: `decode_image` |
| `qr_codec/distort.py` | Picture changes (noise, turn, scale, warp) for the tests and the self-test |
| `studio_history.py` | The history of codes read and made; links, saving a code, describing a reading |
| `studio_clipboard.py` | Pictures to and from the Windows clipboard, through PowerShell |
| `studio_selftest.py` | The checks `--selftest` runs |
| `studio_gui.py` | The tkinter window, `StudioWindow`; loaded only when a window opens |
| `tests/test_qr_codec.py` | The codec, inside out: Reed-Solomon, tables, matrix round trips, pictures through the whole reader |
| `tests/test_qr_studio.py` | The history file and which texts count as links |
| `setup.json` | The install wizard's description: files, icon, shortcut, the data folder to purge |
| `icon/` | The icon and its sizes (see [icon/README.md](icon/README.md)) |

## Developing

Run these in this folder (`utilities/qr_studio`).

| Step | Command |
|---|---|
| Run | `python qr_studio.py` |
| Test | `python -m unittest discover -s tests` (24 tests; the picture tests take most of a minute) |
| Quick check | `python qr_studio.py --selftest` (no tkinter needed) |
| Smoke check | `python qr_studio.py --smoke report.json` opens the window, writes a JSON report (version, title, tabs, `codec_ok`) and closes |
| Round trip | `python qr_studio.py --make "https://example.com" code.png`, then `python qr_studio.py --read code.png` |
| Build the setup | `..\..\company\wizard_maker\wizard-maker.exe build setup.json` writes `dist\Generic Company QR Studio-<version>-setup.exe` |

There is nothing to compile; the program runs from source.

Where to add a typical feature:

- **A new command-line flag** (say `--svg-scale N`): read it with `option_value` in `main` in `qr_studio.py`, add it to the Usage block in the docstring, and add a check to `studio_selftest.py`.
- **A new button in the Make tab** (say Copy as SVG): build it in `StudioWindow.build_make_tab` and add its handler beside `save_as` and `copy_picture` in `studio_gui.py`. Keep the work in a core module (`studio_history.py` or `qr_codec/`) so the window only calls functions, and test it in `tests/`.
- **A new module**: add it to the `files` list in `setup.json`, or the installed program will not find it.

Twins: the `qr_codec` package is shared with QR Palette (`utilities/qr_palette/qr_codec`, an extended copy; see `utilities/qr_palette/PROVENANCE.md`). Every codec module except `images.py` and `distort.py` is byte-identical in both programs, so a fix to one belongs in both.

Traps the code warns about:

- **Version lines**: the version is `__version__` in `qr_studio.py` and `"version"` in `setup.json`. Change both together (the portfolio's Dev Console does it with Apply version).
- **Stamps**: each source file ends with a stamp line. After editing one, run `python tools/stamp.py --restamp <path>` from the portfolio root; `tools/stamp.py --check` verifies them.
- **App id**: `APP_ID` in `studio_history.py` names the data folder and the taskbar identity, and must match `id`, `appUserModelId` and `purge` in `setup.json`.
- **Widget order**: `studio_gui.py` makes its widgets in a fixed order so Tk gives them the same names and packs them the same way; reordering them changes both.
- **Thread rule**: the reading thread only sets `self.pending`; only the Tk thread (`poll_job`, `finish_read`) touches widgets.
- **Import order**: `studio_options.py` sits below both `qr_studio.py` and `studio_selftest.py` so the self-test does not import the entry point. Each codec module imports only modules above it in the `qr_codec/__init__.py` list.
- **Generated files**: `icon/app-*.png`, `app.ico` and `app.res` are made from `qr-16.png` by `tools/pixel_icons.py`; do not edit them by hand.

## Porting to another language

The code is written to translate line by line:

- **Core**: `qr_codec/` and the `studio_history`, `studio_clipboard` and `studio_options` modules are plain functions over plain records (dicts with fixed keys, listed in the module docstrings). Explicit loops, no decorators or generators. Errors are returned as `{"ok", "value", "error"}` records. Port the codec first.
- **Self-test**: `studio_selftest.py` and `tests/` hold the checks to port alongside the core, including the ISO/IEC 18004 annex example.
- **Window**: `studio_gui.py` is tkinter only, and it only calls core functions. Rewrite it in any toolkit.

The clipboard uses PowerShell (`System.Windows.Forms.Clipboard`), isolated in `clipboard_image_to_png` and `png_to_clipboard` in `studio_clipboard.py`.

## Icon

`icon/qr-16.png` is a 16×16 pixel QR glyph drawn for this project; the other sizes are made from it by the portfolio's `tools/pixel_icons.py`, enlarged by whole pixels only. See [icon/README.md](icon/README.md).

## License

AGPL-3.0, see [LICENSE](LICENSE).
