# Generic Company Storage Manager

A desktop program that organizes and cleans folders on local drives and handles network shares (NAS / SMB).

Self-contained: one file, `storage_manager.py`, Python 3.10+ standard library only (tkinter for the window). No installs.

```bash
python storage_manager.py
```

```bash
python storage_manager.py --selftest
```

## What it does

| Tab | Actions |
|---|---|
| Scan | File count and total size, largest files, files not changed for N days, empty folders, unreadable paths. Remove empty folders. |
| Duplicates | Groups identical files (same size, then same SHA-256). Keeps the first of each group and moves the rest to the trash folder. |
| Organize | Sorts the files directly in a folder into subfolders by type (Images, Documents, Video, …) or by year-month. Preview first, then Apply. |
| Network | Saved list of shares (`\\host\share`, optional drive letter). Check reachability and free space, map / disconnect (Windows `net use`), use a share as the working folder, and back up a folder to a share (copies only new or changed files). |
| Log | Everything the program did this session. |

Safety:

- Every change is previewed and confirmed first.
- Nothing is deleted. "Removed" duplicates go to `_storage_manager_trash` inside the scanned folder, keeping their relative paths.
- Each applied change is recorded in `_storage_manager_undo.json` in that folder; **Undo last change** reverses it.
- Passwords are never stored. Windows asks for them when mapping a share if needed.

Settings (saved shares, last folder) are kept in `%LOCALAPPDATA%\Generic Company Inc\GenericCompany.Storage\settings.json`.

## Porting to another language

The file is written to translate line by line:

- **CORE** section: plain functions over plain records (dicts with fixed keys, listed in the file's docstring). Explicit loops, no decorators, generators or comprehensions. Errors are returned as `{"ok", "value", "error"}` records.
- **SELF-TEST** section: the checks to port alongside the core.
- **GUI** section: tkinter only, and it only calls core functions. Rewrite it in any toolkit.

OS-specific pieces are isolated in `map_command`, `unmap_command` and `ping_command`.

## Icon

`icon/` is made by the portfolio's `tools/pixel_icons.py` from Silk's `drive_network.png` (Mark James, CC BY 2.5), enlarged by whole pixels only; see [icon/README.md](icon/README.md). The credit is also in the window's About box. Without `icon/` the program still runs with the default icon.

## License

AGPL-3.0, see [LICENSE](LICENSE).
