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
python storage_manager.py --folder D:\ --view map
```

## How it works

Pick a folder or drive (the list offers recent folders, drives and saved shares) and press **Analyze** (or Enter, or F5). One pass reads every folder, then same-size files are compared for duplicates. The sidebar fills in with what was found:

| Sidebar | What it shows | Action |
|---|---|---|
| Overview | Files, space on disk and folders, and what that leaves out (see below); free space on the drive and what the trash folder holds; what is worth a look; space by type (Images, Video, …). | Open the trash folder. |
| Space map | A sunburst of the folder: rings are folder levels, each slice's angle is its space on disk, and every folder and file big enough to see gets its own slice (the rest of a folder becomes one "N smaller items" slice). The trash folder is one grey slice. Point at a slice for its path and size; click a folder to zoom in, the centre or Backspace to go back up; double-click a file to show it in its folder. **Colour by Duplicate copies** turns slices red where extra copies take space that removing them would free. A "Biggest here" list beside it does the same from the keyboard (Enter zooms into a folder or shows a file). | Open the folder; right-click a slice to open its folder or show it. Files are only ever shown, never opened. |
| Largest files | The 100 files that take the most space on disk, with their file size beside it. | Move to trash, show in folder. |
| Old files | Files not changed for N days (365 by default; change it in place, no new scan). | Move to trash, show in folder. |
| Duplicates | Files stored more than once, grouped, biggest savings first. Green is kept, red goes to the trash. Two names of one file (hard links) are never offered as copies. | Move extra copies to trash; **Keep selected copy** changes which one stays. |
| Empty folders | Folders with nothing in them, including nested ones. | Remove. |
| Unreadable | Paths that could not be read, and why. | — |
| Organize | Sorts the files directly in the folder into subfolders by type or by year-month. | Preview, then Apply. |
| Network shares | Saved shares (`\\host\share`, optional drive letter): online, free and total space. | Add, check, analyze, map / disconnect (Windows `net use`), back up a folder to the share (only new or changed files), remove. |
| Activity | Everything done this session. | Clear. |

Actions apply to the selected rows, or to every row when nothing is selected. Lists show the first 2,000 rows; columns sort when their heading is clicked; double-click a file to show it in its folder; Delete runs the view's main action and Ctrl+Z undoes. After moving or removing, the lists update without a new scan.

Sizes are **space on disk**, not file sizes, and the window says so: "on disk" in the Overview, the map and the lists, which show the file size beside it. The two differ exactly where it matters for cleaning:

- A cloud-only file (OneDrive Files On-Demand and similar placeholders, or an offline file) takes nothing here. It is not compared for duplicates either: reading it would download it, and moving it frees nothing on this disk.
- A compressed or sparse file counts what it takes (NTFS compression and sparse files; on macOS and Linux what the file system reports, such as APFS or btrfs compression).
- A file with several names (hard links) counts once, under its first name, and its names are marked "(hard link)". Two names of one file are never offered as duplicate copies, and a copy that has other names is kept by default: moving it would free nothing.
- Files in the trash folder still take space. The Overview says how much the trash folder holds and the map shows it as a grey slice; the space is freed when you delete the folder.

The Overview adds up what on disk leaves out: what compression saves, files with no data on this disk, and second names of hard-linked files. Limits, to keep the scan fast:

- On Windows a folder listing does not say which names are one file. Hard links are found while duplicates are compared (only files whose contents matched are looked up), and the totals and the map are corrected then.
- On a network share (Windows), compressed and sparse files count at their size: asking the server about each one would cost a round trip per file.
- Files compressed with `compact /exe` or CompactOS look like ordinary files in a folder listing and count at their size.
- The unused end of each file's last cluster is not counted, so a total can be a little below Explorer's "Size on disk".

Safety:

- Every change is confirmed first, with the count and size.
- Nothing is deleted. "Removed" duplicates go to `_storage_manager_trash` inside the scanned folder, keeping their relative paths. They take the same space until you delete that folder; the Overview and the space map show how much it holds.
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

0.4.0 counts space on disk (see above) at nearly the same speed. On `bench/make_dataset.py --profile local` (48,995 files, 1.4 GB, 1,000 folders; 12,265 of the files are duplicates or their originals), fastest of interleaved runs against 0.3.1 on one PC, on its SSD and through an SMB share of the same folder on the same PC:

| Step | 0.3.1 | 0.4.0 |
|---|---|---|
| Scan, local | 0.71 s | 0.75 s |
| Scan, SMB share | 3.68 s | 3.91 s |
| Plan a backup that is already up to date, local | 1.28 s | 1.39 s |
| Find duplicates, local | 4.21 s | 4.76 s |
| Find duplicates, SMB share | 12.1 s | 13.1 s |

Over repeated rounds the scan was 2 to 7% slower, inside this PC's run-to-run noise. Finding duplicates was 8 to 19% slower on this duplicate-heavy set, nearly all of it the hard-link lookup described below.

- Folders are read once with `os.scandir`, which returns sizes, dates and (on Windows) file attributes with the listing, without opening each file. Empty folders are found in the same pass, and duplicates reuse the same list.
- Space on disk mostly comes with the listing: on Windows the attributes say which files are cloud-only, compressed or sparse; on macOS and Linux the listing's stat has the allocated blocks and the link count. Only compressed and sparse files on a local Windows drive cost a call each (`GetCompressedFileSizeW`, 8 at a time): 4,894 NTFS-compressed files scan in 0.26 s instead of 0.08 s. On a network share they are not asked about, as each call would be a round trip to the server.
- Duplicates are narrowed step by step: same size, then the same first and last 64 KB for large files, then the same SHA-256. Files are read on 8 threads, which hides disk, antivirus and network latency.
- Which names are one file (hard links) is read from the handle already open for a large file's two ends, and looked up with one `os.stat` only for files whose whole contents matched another's: 12,265 files here, about 0.4 s locally. Looking up every file that shares its size with another (34,982 here) before hashing would take about 1.1 s locally and 3.8 s over SMB.
- A backup lists the source and the share once each and compares them in memory instead of asking the share about every file.
- The window reads progress from the worker every 100 ms and caps each list at 2,000 rows, so it stays responsive on big drives.

## Porting to another language

The file is written to translate line by line:

- **CORE** section: plain functions over plain records (dicts with fixed keys, listed in the file's docstring). Explicit loops, no decorators, generators or comprehensions. Errors are returned as `{"ok", "value", "error"}` records. Progress is a plain callback, `progress(text, done, total, unit)`.
- **SELF-TEST** section: the checks to port alongside the core.
- **GUI** section: tkinter only, and it only calls core functions. Rewrite it in any toolkit.

A few pieces map to a library call in the target language: `hash_many` and `run_on_workers` (any thread pool or parallel-for) and `largest_files` (a top-N / priority queue). OS-specific pieces are isolated in `map_command`, `unmap_command`, `ping_command`, `reveal_command`, `open_folder_command`, `list_drives`, and the two Windows calls behind `windows_api`: `allocated_size` (GetCompressedFileSizeW) and `is_network_path` (GetDriveTypeW).

## Icon

`icon/` is made by the portfolio's `tools/pixel_icons.py` from Silk's `drive_network.png` (Mark James, CC BY 2.5), enlarged by whole pixels only; see [icon/README.md](icon/README.md). The credit is also in the window's About box. Without `icon/` the program still runs with the default icon.

## License

AGPL-3.0, see [LICENSE](LICENSE).
