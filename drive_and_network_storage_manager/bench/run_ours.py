# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: drive_and_network_storage_manager/bench/run_ours.py
# About: Time Storage Manager's duplicate finder on a dataset from make_dataset.py and check its...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

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

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import storage_manager  # noqa: E402


def load_truth(dataset):
    with open(os.path.join(dataset, "truth.json"), encoding="utf-8") as handle:
        return json.load(handle)


def relative_groups(groups, data_dir):
    """Absolute paths -> sorted lists of forward-slash paths relative to data_dir."""
    result = []
    for group in groups:
        names = []
        for path in group:
            names.append(os.path.relpath(path, data_dir).replace("\\", "/"))
        result.append(sorted(names))
    result.sort()
    return result


def score(found, truth_groups):
    truth_set = set()
    for group in truth_groups:
        truth_set.add(tuple(group))
    found_set = set()
    for group in found:
        found_set.add(tuple(group))
    return {"exact": found_set == truth_set, "groups_expected": len(truth_set), "groups_found": len(found_set),
            "missed": len(truth_set - found_set), "wrong": len(found_set - truth_set)}


def peak_memory_mb():
    """Peak working set of this process (Windows), or None elsewhere."""
    if os.name != "nt":
        return None

    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

    counters = Counters()
    counters.cb = ctypes.sizeof(Counters)
    kernel32 = ctypes.windll.kernel32
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.K32GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
    if not kernel32.K32GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        return None
    return round(counters.PeakWorkingSetSize / (1024 * 1024), 1)


def received_bytes():
    """Total bytes received by all network adapters (Windows), or None."""
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
    before = received_bytes()
    start = time.perf_counter()
    result = storage_manager.find_duplicates(data_dir, [False], None)
    seconds = time.perf_counter() - start
    after = received_bytes()
    if not result["ok"]:
        raise SystemExit("find_duplicates failed: " + str(result["error"]))
    paths = []
    for group in result["value"]:
        names = []
        for info in group:
            names.append(info["path"])
        paths.append(names)
    network = None
    if before is not None and after is not None:
        network = after - before
    return {"seconds": round(seconds, 3), "network_bytes": network}, paths


def main(arguments):
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

# ==== stamp v1 | author=kjFriday | hmac-sha256=5d30b76ffd3cbd3d0cc32548805a03bc40ac44d96b6c69948de879b47ba01064 ====
