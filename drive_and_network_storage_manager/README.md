# Generic Company Storage Manager

A desktop program that organizes and cleans folders on local drives and handles network shares (NAS / SMB).

Self-contained: one file, `storage_manager.py`, Python 3.10+ standard library only (tkinter for the window). No installs.

```bash
python storage_manager.py
```

```bash
python storage_manager.py --selftest
```

```bash
python storage_manager.py --folder D:\ --view duplicates
```

## How it works

Pick a folder or drive (the list offers recent folders, drives and saved shares) and press **Analyze** (or Enter, or F5). One pass reads every folder, then same-size files are compared for duplicates. The sidebar fills in with what was found:

| Sidebar | What it shows | Action |
|---|---|---|
| Overview | Files, size and folders; free space on the drive; what is worth a look; space by type (Images, Video, …). | Open the trash folder. |
| Largest files | The 100 biggest files. | Move to trash, show in folder. |
| Old files | Files not changed for N days (365 by default; change it in place, no new scan). | Move to trash, show in folder. |
| Duplicates | Files stored more than once, grouped, biggest savings first. Green is kept, red goes to the trash. | Move extra copies to trash; **Keep selected copy** changes which one stays. |
| Empty folders | Folders with nothing in them, including nested ones. | Remove. |
| Unreadable | Paths that could not be read, and why. | — |
| Organize | Sorts the files directly in the folder into subfolders by type or by year-month. | Preview, then Apply. |
| Network shares | Saved shares (`\\host\share`, optional drive letter): online, free and total space. | Add, check, analyze, map / disconnect (Windows `net use`), back up a folder to the share (only new or changed files), remove. |
| Activity | Everything done this session. | Clear. |

Actions apply to the selected rows, or to every row when nothing is selected. Lists show the first 2,000 rows; columns sort when their heading is clicked; double-click a file to show it in its folder; Delete runs the view's main action and Ctrl+Z undoes. After moving or removing, the lists update without a new scan.

Safety:

- Every change is confirmed first, with the count and size.
- Nothing is deleted. "Removed" duplicates go to `_storage_manager_trash` inside the scanned folder, keeping their relative paths.
- Each applied change is recorded in `_storage_manager_undo.json` in that folder; **Undo last change** reverses it.
- Passwords are never stored. Windows asks for them when mapping a share if needed.

Settings (saved shares, recent folders, the old-files age, window size) are kept in `%LOCALAPPDATA%\Generic Company Inc\GenericCompany.Storage\settings.json`.

## Speed

On 40,000 files (600 MB, 1,100 folders, local SSD) compared with 0.1.0:

| Step | 0.1.0 | 0.2.0 |
|---|---|---|
| Scan (sizes, dates, empty folders) | 9.6 s | 0.3 s |
| Find duplicates | 38.0 s | 4.2 s |
| Plan a backup that is already up to date | 13.5 s | 0.6 s |

- Folders are read once with `os.scandir`, which returns sizes and dates with the listing (on Windows without opening each file). Empty folders are found in the same pass, and duplicates reuse the same list.
- Duplicates are narrowed step by step: same size, then the same first and last 64 KB for large files, then the same SHA-256. Files are read on 8 threads, which hides disk, antivirus and network latency.
- A backup lists the source and the share once each and compares them in memory instead of asking the share about every file.
- The window reads progress from the worker every 100 ms and caps each list at 2,000 rows, so it stays responsive on big drives.

## Porting to another language

The file is written to translate line by line:

- **CORE** section: plain functions over plain records (dicts with fixed keys, listed in the file's docstring). Explicit loops, no decorators, generators or comprehensions. Errors are returned as `{"ok", "value", "error"}` records. Progress is a plain callback, `progress(text, done, total, unit)`.
- **SELF-TEST** section: the checks to port alongside the core.
- **GUI** section: tkinter only, and it only calls core functions. Rewrite it in any toolkit.

Two pieces map to a library call in the target language: `hash_many` (any thread pool or parallel-for) and `largest_files` (a top-N / priority queue). OS-specific pieces are isolated in `map_command`, `unmap_command`, `ping_command`, `reveal_command`, `open_folder_command` and `list_drives`.

## Icon

`icon/` is made by the portfolio's `tools/pixel_icons.py` from Silk's `drive_network.png` (Mark James, CC BY 2.5), enlarged by whole pixels only; see [icon/README.md](icon/README.md). The credit is also in the window's About box. Without `icon/` the program still runs with the default icon.

## License

AGPL-3.0, see [LICENSE](LICENSE).
