# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: drive_and_network_storage_manager/bench/make_dataset.py
# About: Make a seeded benchmark folder full of files and known duplicates.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

r"""Make a seeded benchmark folder full of files and known duplicates.

  python make_dataset.py OUT_DIR --profile small|local|nas|large [--seed N] [--scale F]

The same profile, seed and scale always give the same files. OUT_DIR\truth.json lists every group of
identical files (relative paths, sorted) so a tool's answer can be checked. truth.json sits outside
the data folder, OUT_DIR\data, which is the folder to scan.

Traps, so a tool that cuts corners gets a wrong answer:
  - "same_size": files with the same size but different content
  - "same_ends": large files with the same size and the same first and last 64 KB, differing
    in one byte in the middle
Standard library only.
"""

import hashlib
import json
import os
import random
import sys

BLOCK = 1024 * 1024
KB = 1024
MB = 1024 * KB
GB = 1024 * MB

# kind -> (share of files, smallest size, largest size)
PROFILES = {
    "small": {"files": 2000, "kinds": [("doc", 1.0, 1 * KB, 200 * KB)]},
    "local": {"files": 40000, "kinds": [("doc", 0.97, 1 * KB, 40 * KB), ("photo", 0.03, 100 * KB, 400 * KB)]},
    "nas": {"files": 200000, "kinds": [("doc", 0.70, 10 * KB, 1 * MB), ("photo", 0.27, 2 * MB, 6 * MB),
                                       ("video", 0.03, 20 * MB, 120 * MB)]},
    "large": {"files": 100, "kinds": [("video", 1.0, 1 * GB, 10 * GB)]},
}
DUPLICATE_SHARE = 0.10   # share of originals that get 1-3 copies
TRAP_SHARE = 0.02        # share of originals that get a trap twin
SAMPLE = 64 * KB         # must match SAMPLE_SIZE in storage_manager.py


def file_rng(seed, number):
    return random.Random(str(seed) + ":" + str(number))


def write_content(path, size, seed, number, flip_middle):
    """Deterministic, incompressible content. A 1 MB base block is reused with a per-block stamp,
    so large files are fast to write but no two blocks are equal."""
    rng = file_rng(seed, number)
    base = bytearray(rng.randbytes(min(size, BLOCK)))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    middle = size // 2
    with open(path, "wb") as handle:
        written = 0
        block_index = 0
        while written < size:
            length = min(BLOCK, size - written)
            stamp = hashlib.sha256((str(seed) + ":" + str(number) + ":" + str(block_index)).encode()).digest()
            chunk = bytearray(base[:length])
            chunk[0:min(32, length)] = stamp[0:min(32, length)]
            if flip_middle and written <= middle < written + length:
                chunk[middle - written] = chunk[middle - written] ^ 0xFF
            handle.write(chunk)
            written = written + length
            block_index = block_index + 1


def plan(profile, seed, scale):
    """-> list of entries {rel, size, number, flip}. Entries with the same (number, flip) are identical."""
    rng = random.Random(seed)
    spec = PROFILES[profile]
    count = max(1, int(spec["files"] * scale))
    entries = []
    folder_count = max(1, count // 40)
    number = 0
    for kind_name, share, low, high in spec["kinds"]:
        kind_count = max(1, int(count * share))
        index = 0
        while index < kind_count:
            size = rng.randint(low, high)
            folder = "f" + str(rng.randrange(folder_count)).zfill(5)
            entries.append({"rel": folder + "/" + kind_name + str(number).zfill(7) + ".bin",
                            "size": size, "number": number, "flip": False})
            number = number + 1
            index = index + 1
    originals = list(entries)
    for original in originals:
        roll = rng.random()
        if roll < DUPLICATE_SHARE:
            copies = rng.randint(1, 3)
            copy = 0
            while copy < copies:
                folder = "f" + str(rng.randrange(folder_count)).zfill(5)
                entries.append({"rel": folder + "/copy" + str(original["number"]).zfill(7) + "_" + str(copy) + ".bin",
                                "size": original["size"], "number": original["number"], "flip": False})
                copy = copy + 1
        elif roll < DUPLICATE_SHARE + TRAP_SHARE:
            folder = "f" + str(rng.randrange(folder_count)).zfill(5)
            if original["size"] > 2 * SAMPLE:
                # same size, same ends, one byte different in the middle
                entries.append({"rel": folder + "/trapends" + str(original["number"]).zfill(7) + ".bin",
                                "size": original["size"], "number": original["number"], "flip": True})
            else:
                # same size, different content
                entries.append({"rel": folder + "/trapsize" + str(original["number"]).zfill(7) + ".bin",
                                "size": original["size"], "number": number, "flip": False})
                number = number + 1
    return entries


def truth_groups(entries):
    by_content = {}
    for entry in entries:
        key = str(entry["number"]) + ":" + str(entry["flip"])
        if key not in by_content:
            by_content[key] = []
        by_content[key].append(entry["rel"])
    groups = []
    for key in by_content:
        if len(by_content[key]) > 1:
            groups.append(sorted(by_content[key]))
    groups.sort()
    return groups


def main(arguments):
    if len(arguments) < 1:
        print(__doc__)
        return 2
    out_dir = arguments[0]
    profile = "small"
    seed = 1
    scale = 1.0
    index = 1
    while index < len(arguments):
        if arguments[index] == "--profile":
            profile = arguments[index + 1]
        elif arguments[index] == "--seed":
            seed = int(arguments[index + 1])
        elif arguments[index] == "--scale":
            scale = float(arguments[index + 1])
        else:
            print("unknown option: " + arguments[index])
            return 2
        index = index + 2
    if profile not in PROFILES:
        print("profile must be one of: " + ", ".join(PROFILES))
        return 2
    data_dir = os.path.join(out_dir, "data")
    if os.path.exists(data_dir) and os.listdir(data_dir):
        print("not empty: " + data_dir)
        return 1
    entries = plan(profile, seed, scale)
    total = 0
    for entry in entries:
        total = total + entry["size"]
    print("writing " + str(len(entries)) + " files, " + str(round(total / GB, 2)) + " GB to " + data_dir)
    done = 0
    for entry in entries:
        write_content(os.path.join(data_dir, entry["rel"]), entry["size"], seed, entry["number"], entry["flip"])
        done = done + 1
        if done % 1000 == 0:
            print("  " + str(done) + " / " + str(len(entries)))
    groups = truth_groups(entries)
    truth = {"profile": profile, "seed": seed, "scale": scale, "files": len(entries), "bytes": total,
             "groups": groups}
    with open(os.path.join(out_dir, "truth.json"), "w", encoding="utf-8") as handle:
        json.dump(truth, handle, indent=1)
    print("done: " + str(len(groups)) + " duplicate groups in truth.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

# ==== stamp v1 | author=kjFriday | hmac-sha256=f956c203a6f4d5ea607905e641637ffb385e204fe941eb1be6797fca88e7c774 ====
