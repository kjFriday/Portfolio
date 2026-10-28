# Generic Company QR Studio

A desktop program that reads QR codes from pictures and makes new ones.

Self-contained: one file, `qr_studio.py`, Python 3.10+ standard library only (tkinter for the window). The whole QR codec is written from scratch in that file: Reed-Solomon error correction, the encoder (numeric, alphanumeric and byte modes, versions 1–40, levels L/M/Q/H, mask scoring), and the reader (thresholding, finder-pattern search, alignment-pattern search, perspective sampling, format/version recovery and error correction). No imaging or barcode library is used.

```bash
python qr_studio.py
```

```bash
python -m unittest test_qr_studio
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

## Porting to another language

The file is written to translate line by line:

- **CORE** section: plain functions over plain records (dicts with fixed keys, listed in the file's docstring). Explicit loops, no decorators or generators. Errors are returned as `{"ok", "value", "error"}` records.
- **SELF-TEST** section and `test_qr_studio.py`: the checks to port alongside the core, including the ISO/IEC 18004 annex example.
- **GUI** section: tkinter only, and it only calls core functions. Rewrite it in any toolkit.

The clipboard uses PowerShell (`System.Windows.Forms.Clipboard`), isolated in `clipboard_image_to_png` and `png_to_clipboard`.

## Icon

`icon/qr-16.png` is a 16×16 pixel QR glyph drawn for this project; the other sizes are made from it by the portfolio's `tools/pixel_icons.py`, enlarged by whole pixels only. See [icon/README.md](icon/README.md).

## License

AGPL-3.0, see [LICENSE](LICENSE).
