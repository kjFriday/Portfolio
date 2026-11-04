# ==== Generic Company Inc. portfolio ====================================
# Project: storage_manager | File: bench/make_dataset.py
# About: Make a seeded benchmark folder full of files and known duplicates.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

# The docstring below is the usage text main prints, so it is code: notes for readers go here.
#
# What it is for: the benchmark kit (BENCHMARK_PLAN.md) needs folders whose duplicates are known in
# advance, of a size that matches a real use (a small test, a local disk, a NAS, a few huge videos).
# run_ours.py then times the duplicate finder on OUT_DIR\data and scores it against truth.json. It
# imports nothing from Storage Manager; only SAMPLE must match duplicates.SAMPLE_SIZE by hand.
#
# Main flow (main):
#   1. Read OUT_DIR and the options; refuse a data folder that is not empty.
#   2. plan draws every file's path, size and content number from one seeded random generator.
#   3. write_content writes each file; files that share (number, flip) get identical bytes.
#   4. truth_groups groups the plan by (number, flip) and truth.json is written beside data.
#
# Determinism: random.Random seeded with an int or a str gives the same stream on every run (str
# seeds are hashed with SHA-512, not with Python's per-run string hash), so a profile, seed and scale
# always give the same bytes. The order of calls on plan's generator defines the dataset: adding or
# moving one call changes every file after it.

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

# BLOCK: bytes written at a time, and the size of each file's reusable random block.
# KB, MB, GB: 1024-based size units for the profiles and the summary line.
BLOCK = 1024 * 1024
KB = 1024
MB = 1024 * KB
GB = 1024 * MB

# profile -> {"files": originals at scale 1, "kinds": [(kind, share of files, smallest size,
# largest size)]}. Sizes are in bytes and drawn uniformly between the two bounds. The kind names the
# files (doc0000001.bin); copies and trap twins come on top of the originals
PROFILES = {
    "small": {"files": 2000, "kinds": [("doc", 1.0, 1 * KB, 200 * KB)]},
    "local": {"files": 40000, "kinds": [("doc", 0.97, 1 * KB, 40 * KB), ("photo", 0.03, 100 * KB, 400 * KB)]},
    "nas": {"files": 200000, "kinds": [("doc", 0.70, 10 * KB, 1 * MB), ("photo", 0.27, 2 * MB, 6 * MB),
                                       ("video", 0.03, 20 * MB, 120 * MB)]},
    "large": {"files": 100, "kinds": [("video", 1.0, 1 * GB, 10 * GB)]},
}
# shares are of the originals; plan draws one roll per original, so the two never overlap
DUPLICATE_SHARE = 0.10   # share of originals that get 1-3 copies
TRAP_SHARE = 0.02        # share of originals that get a trap twin
SAMPLE = 64 * KB         # must match SAMPLE_SIZE in duplicates.py


def file_rng(seed, number):
    """A random generator for one file's content, seeded with "seed:number".

    Each content number gets its own generator, so a file's bytes do not depend on how many files
    were written before it, and two entries with one number get the same bytes.
    """
    return random.Random(str(seed) + ":" + str(number))


def write_content(path, size, seed, number, flip_middle):
    """Deterministic, incompressible content. A 1 MB base block is reused with a per-block stamp,
    so large files are fast to write but no two blocks are equal.

    path: the file to write (its folder is created); size: bytes; seed, number: pick the content (see
    file_rng); flip_middle: invert the byte at size // 2, for a "same_ends" trap. For any file larger
    than 2 * SAMPLE that byte lies outside both 64 KB end samples, so only a whole-file comparison
    sees the difference.

    Steps:
      1. Draw one random base block (at most BLOCK bytes) from the file's own generator.
      2. For each block: copy the base and overwrite its first 32 bytes with the SHA-256 of
         "seed:number:block", so no two blocks of the file are equal.
      3. In the block holding the middle byte, XOR it with 0xFF when flip_middle is set. This comes
         after the stamp, so the flip lands even when the middle falls in a stamp.
    Random bytes do not compress, so file-system compression cannot shrink the dataset.
    """
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
    """-> list of entries {rel, size, number, flip}. Entries with the same (number, flip) are identical.

    profile: a PROFILES key; seed: the generator seed; scale: multiplies the profile's file count (at
    least one file). rel is a forward-slash path under the data folder; number picks the content.
    Nothing is written.

    Steps:
      1. Originals: for each kind, its share of the files, each with a random size in its range, in
         one of count // 40 folders (about 40 originals a folder) named f00000, f00001, ...
      2. For each original, one roll: under DUPLICATE_SHARE it gets 1 to 3 copies (same number);
         in the next TRAP_SHARE a trap twin; otherwise nothing.
      3. A trap twin of a file larger than 2 * SAMPLE is a "same_ends" trap (same number, flip set);
         a smaller one is a "same_size" trap with a fresh number, so different content.
    """
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
    """The groups of identical files in entries -> sorted list of sorted lists of rel paths.

    Files are identical when they share "number:flip". Only groups of two or more are kept; trap
    twins never join their original's group. Sorting both levels makes the answer comparable with
    any tool's, whatever order it reports in.
    """
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
    """Write the dataset for the command line arguments (without the program name) -> exit status.

    0 when done, 1 when OUT_DIR\\data already holds files, 2 for a usage error (the usage text is
    printed when no OUT_DIR is given). Writes OUT_DIR\\data and OUT_DIR\\truth.json, overwriting an
    old truth.json. Prints a summary line, a count every 1000 files and the number of groups.
    Known limitation: options are read in pairs, so an option given last without a value raises
    IndexError, and a bad number raises ValueError, instead of printing the usage.
    """
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
    # truth.json goes beside data, not in it, so a tool scanning data never sees it
    groups = truth_groups(entries)
    truth = {"profile": profile, "seed": seed, "scale": scale, "files": len(entries), "bytes": total,
             "groups": groups}
    with open(os.path.join(out_dir, "truth.json"), "w", encoding="utf-8") as handle:
        json.dump(truth, handle, indent=1)
    print("done: " + str(len(groups)) + " duplicate groups in truth.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

# ==== stamp v1 | author=kjFriday | hmac-sha256=8315928622fcd93dfd9e737730c88164a10cca2f5a871df5ecffe243169b4c1e ====
