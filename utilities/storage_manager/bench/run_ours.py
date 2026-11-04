# ==== Generic Company Inc. portfolio ====================================
# Project: storage_manager | File: bench/run_ours.py
# About: Time Storage Manager's duplicate finder on a dataset from make_dataset.py and check its...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

# The docstring below is the usage text main prints, so it is code: notes for readers go here.
#
# What it is for: the second half of the benchmark kit (BENCHMARK_PLAN.md). It runs
# duplicates.find_duplicates headless (no window, no tkinter) on a dataset from
# make_dataset.py, and checks the groups against truth.json; with --check-fclones it scores the
# fclones tool's JSON answer the same way instead, so both tools face the same traps.
#
# Main flow (main):
#   1. Read the options and truth.json.
#   2. Either score an fclones report and stop, or:
#   3. run_once the finder --runs times, timing each run and reading the network counters around it;
#   4. score the last run's groups, read the peak memory once, and print (and save) the JSON report.
# Paths are compared relative to DATASET_DIR\data with forward slashes, as truth.json writes them.

r"""Time Storage Manager's duplicate finder on a dataset from make_dataset.py and check its answer.

  python run_ours.py DATASET_DIR [--runs N] [--out FILE]
  python run_ours.py DATASET_DIR --check-fclones FCLONES.json

DATASET_DIR holds data\ (scanned) and truth.json. DATASET_DIR can be a share path such as
\\NAS\bench\nas. Prints one JSON report (and writes it to --out): wall time per run, median, peak
memory, bytes all network adapters received during each run (Windows; includes background traffic) and whether the duplicate groups
match truth.json exactly.

--check-fclones scores a rival's answer instead: run
  fclones group DATASET_DIR\data --format json -o FCLONES.json
and pass that file. Clear caches (remount the share or reboot) before each timed run.
Standard library only.
"""

import ctypes
import json
import os
import statistics
import subprocess
import sys
import time

# the project folder (bench's parent) goes first on the import path, so the imports below find the
# Storage Manager modules from any working folder; bench must stay a direct child of the project
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import duplicates  # noqa: E402
import storage_manager  # noqa: E402


def load_truth(dataset):
    """Read DATASET_DIR\\truth.json -> dict (profile, seed, scale, files, bytes, groups).

    A missing or broken file raises (OSError, ValueError): the run cannot be scored without it.
    """
    with open(os.path.join(dataset, "truth.json"), encoding="utf-8") as handle:
        return json.load(handle)


def relative_groups(groups, data_dir):
    """Absolute paths -> sorted lists of forward-slash paths relative to data_dir.

    groups: lists of paths, from either tool. The result has the same shape as truth.json's groups
    (each group sorted, then the groups sorted), so the two can be compared directly.
    """
    result = []
    for group in groups:
        names = []
        for path in group:
            names.append(os.path.relpath(path, data_dir).replace("\\", "/"))
        result.append(sorted(names))
    result.sort()
    return result


def score(found, truth_groups):
    """Compare found groups with the true ones -> {"exact", "groups_expected", "groups_found",
    "missed", "wrong"}.

    Both are lists of sorted path lists. A group matches only when it has exactly the same paths, so
    a group found partly (or with an extra file) counts once as missed and once as wrong. exact is
    True when the two sets of groups are equal.
    """
    truth_set = set()
    for group in truth_groups:
        truth_set.add(tuple(group))
    found_set = set()
    for group in found:
        found_set.add(tuple(group))
    return {"exact": found_set == truth_set, "groups_expected": len(truth_set), "groups_found": len(found_set),
            "missed": len(truth_set - found_set), "wrong": len(found_set - truth_set)}


def peak_memory_mb():
    """Peak working set of this process (Windows), or None elsewhere.

    -> megabytes (1024 * 1024 bytes), one decimal. The working set is the physical memory the process
    holds; its peak covers the whole process life, so read after all runs it is the largest of any
    run, plus the interpreter and imports. None when the call fails.

    Steps:
      1. Declare PROCESS_MEMORY_COUNTERS (psapi.h) as a ctypes structure and set cb to its size, as
         the API requires.
      2. Call K32GetProcessMemoryInfo, the kernel32 export of GetProcessMemoryInfo (Windows 7 and
         later), so psapi.dll need not be loaded, on GetCurrentProcess's pseudo-handle.
    """
    if os.name != "nt":
        return None

    class Counters(ctypes.Structure):
        """PROCESS_MEMORY_COUNTERS from psapi.h: field order and types must match the C struct.

        DWORD fields are c_ulong (32 bits on Windows); SIZE_T fields are c_size_t (pointer sized).
        """
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

    counters = Counters()
    counters.cb = ctypes.sizeof(Counters)
    kernel32 = ctypes.windll.kernel32
    # the pseudo-handle is (HANDLE)-1; with ctypes' default int types it would be cut to 32 bits on
    # 64-bit Python, so both the result and the argument are declared pointer sized
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.K32GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
    if not kernel32.K32GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        return None
    return round(counters.PeakWorkingSetSize / (1024 * 1024), 1)


def received_bytes():
    """Total bytes received by all network adapters (Windows), or None.

    Runs PowerShell's Get-NetAdapterStatistics and sums ReceivedBytes over every adapter, so other
    traffic on the machine is counted too. None elsewhere, when PowerShell cannot start, takes over
    30 s, or prints something that is not a number. run_once reads it outside the timed part, so
    PowerShell's start-up does not count toward the run's time.
    """
    if os.name != "nt":
        return None
    command = ["powershell", "-NoProfile", "-Command",
               "(Get-NetAdapterStatistics | Measure-Object -Property ReceivedBytes -Sum).Sum"]
    try:
        output = subprocess.run(command, capture_output=True, text=True, timeout=30).stdout.strip()
        return int(output)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def run_once(data_dir):
    """Find the duplicates in data_dir once -> ({"seconds", "network_bytes"}, groups of absolute paths).

    Only find_duplicates is timed (perf_counter, wall time). It runs with a cancel flag that is never
    set and no progress callback. network_bytes is None when either counter read fails. A failed
    Result ends the program through SystemExit with its error.
    """
    before = received_bytes()
    start = time.perf_counter()
    result = duplicates.find_duplicates(data_dir, [False], None)
    seconds = time.perf_counter() - start
    after = received_bytes()
    if not result["ok"]:
        raise SystemExit("find_duplicates failed: " + str(result["error"]))
    paths = []
    for group in result["value"]["groups"]:
        names = []
        for info in group:
            names.append(info["path"])
        paths.append(names)
    network = None
    if before is not None and after is not None:
        network = after - before
    return {"seconds": round(seconds, 3), "network_bytes": network}, paths


def main(arguments):
    """Run the benchmark for the command line arguments (without the program name) -> exit status.

    0 when done, 2 for a usage error (the usage text is printed when no DATASET_DIR is given). Each
    run's time goes to stderr; the JSON report goes to stdout, and to --out when given. Only the last
    run's check is reported; each run's exact flag is on its stderr line. --runs defaults to 3.
    Known limitation: options are read in pairs, so an option given last without a value raises
    IndexError, and a bad --runs number raises ValueError, instead of printing the usage. --runs 0
    raises StatisticsError (the median of no runs).
    """
    if len(arguments) < 1:
        print(__doc__)
        return 2
    dataset = arguments[0]
    runs = 3
    out_path = ""
    fclones_path = ""
    index = 1
    while index < len(arguments):
        if arguments[index] == "--runs":
            runs = int(arguments[index + 1])
        elif arguments[index] == "--out":
            out_path = arguments[index + 1]
        elif arguments[index] == "--check-fclones":
            fclones_path = arguments[index + 1]
        else:
            print("unknown option: " + arguments[index])
            return 2
        index = index + 2
    truth = load_truth(dataset)
    data_dir = os.path.join(dataset, "data")

    if fclones_path:
        with open(fclones_path, encoding="utf-8") as handle:
            report = json.load(handle)
        # fclones' JSON report: {"groups": [{"files": [path, ...], ...}, ...]}
        groups = []
        for group in report["groups"]:
            groups.append(group["files"])
        print(json.dumps({"tool": "fclones", "dataset": dataset,
                          "check": score(relative_groups(groups, data_dir), truth["groups"])}, indent=1))
        return 0

    timings = []
    check = None
    number = 0
    while number < runs:
        timing, groups = run_once(data_dir)
        timings.append(timing)
        check = score(relative_groups(groups, data_dir), truth["groups"])
        print("run " + str(number + 1) + ": " + str(timing["seconds"]) + " s, exact=" + str(check["exact"]),
              file=sys.stderr)
        number = number + 1
    # the median rather than the mean, so one run slowed by a cold cache or background work does not
    # move the headline number
    seconds = []
    for timing in timings:
        seconds.append(timing["seconds"])
    report = {"tool": "storage_manager " + storage_manager.__version__, "dataset": dataset,
              "profile": truth["profile"], "files": truth["files"], "bytes": truth["bytes"],
              "runs": timings, "median_seconds": statistics.median(seconds),
              "peak_memory_mb": peak_memory_mb(), "check": check}
    text = json.dumps(report, indent=1)
    print(text)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as handle:
            handle.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

# ==== stamp v1 | author=kjFriday | hmac-sha256=fe2f4310342d60f0cd4f6e53f5a8e3d2fc885c7821973180899ed37c297651bf ====
