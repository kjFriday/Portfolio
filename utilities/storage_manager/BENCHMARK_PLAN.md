# Benchmark plan: duplicate finding vs rivals

Goal: a number you can put on a sales page, e.g. "finds duplicates on a 1 TB NAS share in X min, Y× faster than Z".

## Rivals
| Tool | Why | Command / mode |
|---|---|---|
| Storage Manager (current version) | ours | headless: `bench/run_ours.py` calls `duplicates.find_duplicates(root, cancel_flag, progress)`, no window |
| fclones (free, Rust) | fastest free tool | `fclones group \\NAS\share --cache off` |
| DupScout Pro (paid, trial) | paid rival with network-share support | GUI scan, timed by its own report |
| dupeGuru (free) | the best-known free option | GUI, standard mode (contents) |

## Datasets
1. **Local SSD, 40k files / 600 MB.** Repeats the README run; checks the method.
2. **NAS share over SMB, ~200k files / ~500 GB, mixed photos/video/docs, ~10% duplicates.** The headline test.
3. **Large-file share (~100 files of 1–10 GB, some identical).** Checks the first/last 64 KB shortcut.

Build datasets 2–3 with a seeded generator script so they're the same every run. Duplicates should include same-size-different-content files, to trap tools that only check size.

## Method
- Same PC, wired gigabit, NAS idle; record CPU, NAS model, link speed.
- Clear caches between runs: reboot the PC, or remount the share; on the NAS, drop page cache or run with a cold set.
- 3 cold runs per tool per dataset; report the median.
- Measure: wall time, bytes read over the network (Task Manager / `Get-NetAdapterStatistics` before and after), peak RAM, and correctness (duplicate groups found vs known truth from the generator).

## Deliverables
- `bench/make_dataset.py` (done: seeded generator, profiles `small`, `local`, `nas`, `large`; writes `truth.json`)
- `bench/run_ours.py` (done: times `duplicates.find_duplicates`, prints JSON; `--check-fclones` scores fclones' answer the same way)
- `bench/results.md` (to do: table + setup notes); headline numbers copied into README `## Speed`

Run from `utilities/storage_manager`:

```bash
python bench/make_dataset.py OUT_DIR --profile local
python bench/run_ours.py OUT_DIR --runs 3
```

`SAMPLE` in `make_dataset.py` must match `SAMPLE_SIZE` in `duplicates.py`.

## Needs from you
- A NAS or a second PC with an SMB share and ~600 GB free.
- Install fclones, dupeGuru and the DupScout trial (your downloads).
