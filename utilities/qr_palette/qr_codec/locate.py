# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: qr_codec/locate.py
# About: Finding a code in a picture: finder patterns, a homography, sampling and decode_image.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Finding a code in a picture: finder patterns, a homography, sampling and decode_image.

decode_image is the reader's entry point: Image -> Result Reading. A big picture is tried shrunk
first, then at full size; each with the global and the local threshold, each raw and through the
majority filter. Every triple of the eight strongest finder candidates that forms an L is sampled at
a few grid sizes, and each grid is decoded as it is and transposed (a mirrored picture).

The picture side of reading follows the reference decode algorithm in ISO/IEC 18004: scan rows for
the finder pattern's 1:1:3:1:1 run ratio, confirm each hit with a vertical and a horizontal pass,
pick three finders that form an L, estimate the version from their spacing, and map the module grid
onto the picture with a perspective transform fitted to the three finder centres and the bottom-right
alignment pattern (or where it would be). decode.py then reads the sampled grid.

Callers: the package's decode_image (re-exported from __init__.py), and through it the app's reading
paths and the tests. distort.py borrows perspective and apply_perspective to warp test pictures.
Points are (x, y) in pixels with y going down; bits is one int per pixel, 1 for dark, row by row.

Start reading at decode_image, then decode_bits.
"""

from .records import fail
from .tables import blank_grid
from .decode import decode_matrix, transpose
from .images import shrink_image
from .binarize import binarize_global, binarize_local, majority_filter


def ratio_ok(runs):
    """Five runs dark, light, dark, light, dark in the finder ratio 1:1:3:1:1.

    runs are pixel counts. The finder is 7 modules across, so one module is total / 7; each run may be
    off from its expected width by less than 70% of a module (three times that for the 3-module
    centre), which allows for blur and an uneven threshold. Runs of 0 pixels, or fewer than 7 pixels in
    all, never match.
    """
    total = 0
    for run in runs:
        if run == 0:
            return False
        total = total + run
    if total < 7:
        return False
    module = total / 7.0
    allowed = module * 0.7
    return (abs(runs[0] - module) < allowed and abs(runs[1] - module) < allowed and
            abs(runs[2] - 3 * module) < 3 * allowed and abs(runs[3] - module) < allowed and
            abs(runs[4] - module) < allowed)


def is_dark(bits, width, height, x, y):
    """True when pixel (x, y) is inside the picture and dark; points outside count as light."""
    return 0 <= x < width and 0 <= y < height and bits[y * width + x] == 1


def cross_check(bits, width, height, x, y, dx, dy, limit):
    """Runs through dark pixel (x, y) along (dx, dy) -> (centre along the line, total) or None.

    Confirms a finder seen along one line by measuring across it along another (dx, dy is (0, 1) for a
    vertical pass, (1, 0) for a horizontal one). The centre is an offset in pixels from (x, y) along the
    direction; total is the five runs' summed length. None when (x, y) is light, a side reaches the
    picture's edge or `limit` steps before its outer dark ring, or the runs miss the 1:1:3:1:1 ratio.

    Steps:
    1. Walk backward from (x, y), then forward from the next pixel, counting three runs each way: the
       dark centre, the light ring, the dark ring. state 0 and 2 expect dark, state 1 light; a pixel of
       the other color moves to the next state, and a fourth run ends the walk.
    2. Join them into the five runs, outer-back to outer-forward, the two centre parts added together.
    3. Check the ratio; the centre's offset from (x, y) is half the difference of the two centre parts
       (plus 1 for the pixel-edge convention the caller undoes with - 0.5).
    """
    if not is_dark(bits, width, height, x, y):
        return None
    sides = []
    for direction in (-1, 1):
        counts = [0, 0, 0]
        state = 0
        px = x
        py = y
        if direction == 1:
            px = x + dx
            py = y + dy
        steps = 0
        while 0 <= px < width and 0 <= py < height and steps < limit:
            dark = bits[py * width + px] == 1
            expected = state != 1
            if dark != expected:
                state = state + 1
                if state == 3:
                    break
            counts[state] = counts[state] + 1
            px = px + dx * direction
            py = py + dy * direction
            steps = steps + 1
        if counts[2] == 0:
            return None
        sides.append(counts)
    back = sides[0]
    forward = sides[1]
    runs = [back[2], back[1], back[0] + forward[0], forward[1], forward[2]]
    if not ratio_ok(runs):
        return None
    total = runs[0] + runs[1] + runs[2] + runs[3] + runs[4]
    centre = 1 + (forward[0] - back[0]) / 2.0
    return (centre, total)


def add_candidate(candidates, x, y, module):
    """Count a finder sighting at (x, y) with module size `module` (pixels) into candidates, in place.

    A finder is crossed by many scanned rows, so a sighting within two modules of a known candidate
    joins it: position and module size become running averages and its hit count goes up by one.
    Otherwise it starts a new candidate [x, y, module, 1].
    """
    for candidate in candidates:
        if abs(candidate[0] - x) <= module * 2 and abs(candidate[1] - y) <= module * 2:
            count = candidate[3]
            candidate[0] = (candidate[0] * count + x) / (count + 1)
            candidate[1] = (candidate[1] * count + y) / (count + 1)
            candidate[2] = (candidate[2] * count + module) / (count + 1)
            candidate[3] = count + 1
            return
    candidates.append([x, y, module, 1])


def find_finders(bits, width, height):
    """Finder-pattern centres -> list of [x, y, module size, hits], most hits first.

    Steps:
    1. Scan rows (every row of a picture under 800 rows, else every height // 400-th) and cut each into runs
       of one color, remembering where each run starts and its color.
    2. At every dark run, test it and the next four runs for the 1:1:3:1:1 ratio.
    3. From the middle run's centre, cross-check vertically to find the centre's y, then horizontally
       from there to refine its x; either failing drops the hit.
    4. The module size is the vertical and horizontal totals over 14 (7 modules each way).
    5. Merge the hit into the candidates (add_candidate) and finally sort them by hit count, so real
       finders, crossed by many rows, come before chance matches.
    The + 0.5 and - 0.5 shifts move between pixel indexes and pixel centres.
    """
    candidates = []
    row_step = max(1, height // 400)
    for y in range(0, height, row_step):
        runs = []
        starts = []
        current = bits[y * width]
        length = 0
        start = 0
        for x in range(width + 1):
            if x < width and bits[y * width + x] == current:
                length = length + 1
                continue
            runs.append(length)
            starts.append((start, current))
            if x < width:
                current = bits[y * width + x]
                start = x
                length = 1
        for i in range(len(runs) - 4):
            if starts[i][1] != 1:
                continue
            five = runs[i:i + 5]
            if not ratio_ok(five):
                continue
            total = five[0] + five[1] + five[2] + five[3] + five[4]
            centre_x = starts[i + 2][0] + five[2] / 2.0
            vertical = cross_check(bits, width, height, int(centre_x), y, 0, 1, total * 2)
            if vertical is None:
                continue
            centre_y = y + vertical[0] - 0.5
            horizontal = cross_check(bits, width, height, int(centre_x), int(centre_y), 1, 0, total * 2)
            if horizontal is None:
                continue
            centre_x = int(centre_x) + horizontal[0] - 0.5
            module = (vertical[1] + horizontal[1]) / 14.0
            add_candidate(candidates, centre_x + 0.5, centre_y + 0.5, module)
    ordered = []
    for candidate in candidates:
        ordered.append(candidate)
    ordered.sort(key=candidate_hits, reverse=True)
    return ordered


def candidate_hits(candidate):
    """A finder candidate's hit count (its fourth item), the sort key for find_finders."""
    return candidate[3]


def point_distance(a, b):
    """Straight-line (Euclidean) distance between two points; only their first two items, x and y, count."""
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def order_finders(a, b, c):
    """Three centres -> (top-left, top-right, bottom-left), or None when they don't form an L.

    Steps:
    1. The corner (top-left) finder is the one opposite the longest side, the L's hypotenuse.
    2. Refuse the triple when a leg is zero, one leg is over 1.6 times the other (a QR code is square;
       the slack allows for perspective), or the angle at the corner is outside 60..120 degrees (the
       cosine is over 0.5 in size).
    3. The sign of the cross product of the two legs says which way the L turns. With y going down,
       turning from the top-right leg to the bottom-left leg must be clockwise on screen (a positive
       cross product); swap the two if not. A
       mirrored picture therefore comes out transposed, which decode_bits also tries.
    """
    ab = point_distance(a, b)
    bc = point_distance(b, c)
    ac = point_distance(a, c)
    if bc >= ab and bc >= ac:
        corner, one, two = a, b, c
    elif ac >= ab:
        corner, one, two = b, a, c
    else:
        corner, one, two = c, a, b
    leg_one = point_distance(corner, one)
    leg_two = point_distance(corner, two)
    if leg_one == 0 or leg_two == 0:
        return None
    if max(leg_one, leg_two) > 1.6 * min(leg_one, leg_two):
        return None
    cross = (one[0] - corner[0]) * (two[1] - corner[1]) - (one[1] - corner[1]) * (two[0] - corner[0])
    cosine = ((one[0] - corner[0]) * (two[0] - corner[0]) + (one[1] - corner[1]) * (two[1] - corner[1]))
    if abs(cosine) / (leg_one * leg_two) > 0.5:
        return None
    if cross < 0:
        one, two = two, one
    return (corner, one, two)


def solve_linear(matrix, values):
    """Gaussian elimination with partial pivoting -> solution list or None.

    Solves matrix * solution = values for a square matrix (a list of n rows) and n values. None when
    the matrix is singular (a pivot below 1e-12), as it is for points that lie on one line.

    Steps:
    1. Append each value to its row (the augmented matrix).
    2. For each column, swap up the row with the largest entry in it (partial pivoting keeps rounding
       errors small), then subtract multiples of that row from every other row to clear the column
       (the Gauss-Jordan form, so no back-substitution is needed).
    3. Each unknown is its row's last entry over its diagonal entry.
    """
    n = len(values)
    rows = []
    for i in range(n):
        rows.append(list(matrix[i]) + [values[i]])
    for column in range(n):
        pivot = column
        for row in range(column + 1, n):
            if abs(rows[row][column]) > abs(rows[pivot][column]):
                pivot = row
        if abs(rows[pivot][column]) < 1e-12:
            return None
        rows[column], rows[pivot] = rows[pivot], rows[column]
        for row in range(n):
            if row != column:
                factor = rows[row][column] / rows[column][column]
                for k in range(column, n + 1):
                    rows[row][k] = rows[row][k] - factor * rows[column][k]
    result = []
    for i in range(n):
        result.append(rows[i][n] / rows[i][i])
    return result


def perspective(sources, targets):
    """Homography taking four source points to four target points -> 8 coefficients or None.

    A camera looking at a flat code at an angle turns its square into a general quadrilateral. The
    mapping that does this is a perspective transform (homography):

        x = (h0 u + h1 v + h2) / (h6 u + h7 v + 1)
        y = (h3 u + h4 v + h5) / (h6 u + h7 v + 1)

    Eight unknowns, and each point pair gives two equations once the divisor is multiplied out:
    h0 u + h1 v + h2 - h6 u x - h7 v x = x, and the same with h3..h5 and y. Four pairs, no three on one
    line, fix all eight; solve_linear finds them. None when the points are degenerate.
    """
    matrix = []
    values = []
    for i in range(4):
        u, v = sources[i]
        x, y = targets[i]
        matrix.append([u, v, 1, 0, 0, 0, -u * x, -v * x])
        values.append(x)
        matrix.append([0, 0, 0, u, v, 1, -u * y, -v * y])
        values.append(y)
    return solve_linear(matrix, values)


def apply_perspective(h, u, v):
    """Map point (u, v) through homography h (from perspective) -> (x, y).

    A divisor of (nearly) zero means the point maps to infinity, the horizon of the tilted plane; it
    returns (-1.0, -1.0), a point outside any picture, so callers read it as light or skip it.
    """
    divisor = h[6] * u + h[7] * v + 1.0
    if abs(divisor) < 1e-12:
        return (-1.0, -1.0)
    return ((h[0] * u + h[1] * v + h[2]) / divisor, (h[3] * u + h[4] * v + h[5]) / divisor)


def find_alignment(bits, width, height, guess, across, down, module):
    """Best match for the 5x5 alignment pattern near `guess` -> (x, y) or None.
    Every position with the top score is averaged, so the result sits on the pattern's centre.

    across and down are one module's step in pixels along the code's rows and columns, so the template
    follows the code's tilt. Candidate centres cover 5 modules each way around the guess, a third of a
    module apart. Each scores one point per template module whose pixel has the expected color (dark
    except the ring at distance 1); fewer than 23 of the 25 is no match.
    """
    best_score = 0
    sum_x = 0.0
    sum_y = 0.0
    hits = 0
    reach = int(module * 5)
    step = max(1, int(module / 3))
    for oy in range(-reach, reach + 1, step):
        for ox in range(-reach, reach + 1, step):
            cx = guess[0] + ox
            cy = guess[1] + oy
            score = 0
            for j in range(-2, 3):
                for i in range(-2, 3):
                    x = int(cx + i * across[0] + j * down[0])
                    y = int(cy + i * across[1] + j * down[1])
                    if is_dark(bits, width, height, x, y) == (max(abs(i), abs(j)) != 1):
                        score = score + 1
            if score > best_score:
                best_score = score
                sum_x = 0.0
                sum_y = 0.0
                hits = 0
            if score == best_score:
                sum_x = sum_x + cx
                sum_y = sum_y + cy
                hits = hits + 1
    if best_score < 23 or hits == 0:
        return None
    return (sum_x / hits, sum_y / hits)


def sample_grid(bits, width, height, finders, size):
    """Read a size x size grid of modules from the picture -> grid of bools, or None.

    finders are the ordered (top-left, top-right, bottom-left) centres in pixels; grid coordinates count
    modules from the symbol's top-left corner, so a finder centre is at 3.5 (the middle of module 3).

    Steps:
    1. From the finders, work out one module's step along a row (across) and down a column (down):
       the finder centres are size - 7 modules apart.
    2. A homography needs a fourth point. Guess it by completing the parallelogram: for versions 2 and
       up, the bottom-right alignment pattern's centre (size - 6.5); for version 1, which has none, the
       spot where a fourth finder would sit (size - 3.5).
    3. On versions 2 and up, search for the real alignment pattern near the guess (find_alignment); it
       corrects for perspective, which a parallelogram cannot show. Keep the guess if none is found.
    4. Fit the homography from the four grid points to the four picture points (perspective), and
       read the pixel under each module's centre (column + 0.5, row + 0.5).
    None when the four points give no homography.
    """
    top_left, top_right, bottom_left = finders
    span = size - 7.0
    across = ((top_right[0] - top_left[0]) / span, (top_right[1] - top_left[1]) / span)
    down = ((bottom_left[0] - top_left[0]) / span, (bottom_left[1] - top_left[1]) / span)
    sources = [(3.5, 3.5), (size - 3.5, 3.5), (3.5, size - 3.5)]
    targets = [(top_left[0], top_left[1]), (top_right[0], top_right[1]), (bottom_left[0], bottom_left[1])]
    corner = size - 6.5
    if size == 21:
        corner = size - 3.5
    guess = (top_left[0] + (corner - 3.5) * (across[0] + down[0]),
             top_left[1] + (corner - 3.5) * (across[1] + down[1]))
    fourth = guess
    if size > 21:
        module = (abs(across[0]) + abs(across[1]) + abs(down[0]) + abs(down[1])) / 2.0
        found = find_alignment(bits, width, height, guess, across, down, module)
        if found is not None:
            fourth = found
    sources.append((corner, corner))
    targets.append(fourth)
    h = perspective(sources, targets)
    if h is None:
        return None
    grid = blank_grid(size, False)
    for row in range(size):
        for column in range(size):
            x, y = apply_perspective(h, column + 0.5, row + 0.5)
            grid[row][column] = is_dark(bits, width, height, int(x), int(y))
    return grid


def candidate_sizes(finders):
    """Symbol sizes (modules a side) worth sampling for three ordered finders, best guess first.

    Finder centres sit 3.5 modules in from the edges, so their distance over the module size is
    size - 7. Valid sizes are 17 + 4 * version, all one more than a multiple of 4, so the estimate is
    snapped to the nearest such size (an estimate of 4k + 3, halfway between two sizes, goes down). The neighbouring versions
    (sizes 4 and 8 either way) follow, since the module size measured from finders is rough; anything
    outside 21..177 is dropped.
    """
    top_left, top_right, bottom_left = finders
    module = (top_left[2] + top_right[2] + bottom_left[2]) / 3.0
    across = point_distance(top_left, top_right) / module
    down = point_distance(top_left, bottom_left) / module
    estimate = int(round((across + down) / 2.0)) + 7
    remainder = estimate % 4
    if remainder == 0:
        estimate = estimate + 1
    elif remainder == 2:
        estimate = estimate - 1
    elif remainder == 3:
        estimate = estimate - 2
    sizes = []
    for offset in (0, 4, -4, 8, -8):
        size = estimate + offset
        if 21 <= size <= 177:
            sizes.append(size)
    return sizes


def decode_bits(bits, width, height):
    """Find and read a code in one binarized picture -> Result Reading, with "corners" added.

    "corners" holds the [x, y] pixel centres of the top-left, top-right and bottom-left finders.

    Steps:
    1. Find finder candidates and keep the eight with the most hits.
    2. Try every triple that forms an L (order_finders), at each candidate size.
    3. Sample the grid and decode it, then its transpose (a mirrored picture swaps rows and columns);
       the first that decodes wins.
    Fails with "no QR code found" when fewer than three finders were seen, else "found a QR code but
    could not read it".
    """
    finders = find_finders(bits, width, height)
    top = finders[:8]
    for a in range(len(top)):
        for b in range(a + 1, len(top)):
            for c in range(b + 1, len(top)):
                ordered = order_finders(top[a], top[b], top[c])
                if ordered is None:
                    continue
                for size in candidate_sizes(ordered):
                    grid = sample_grid(bits, width, height, ordered, size)
                    if grid is None:
                        continue
                    for attempt in (grid, transpose(grid)):
                        decoded = decode_matrix(attempt)
                        if decoded["ok"]:
                            corners = []
                            for point in ordered:
                                corners.append([point[0], point[1]])
                            decoded["value"]["corners"] = corners
                            return decoded
    if len(finders) < 3:
        return fail("no QR code found")
    return fail("found a QR code but could not read it")


def decode_image(image):
    """Image -> Result Reading. Big pictures are tried shrunk first, then at full size.

    Steps:
    1. A picture 1600 pixels or more on its longer side is first tried shrunk by largest // 800, which
       is faster and smooths camera noise; the full size comes second.
    2. Each size is binarized two ways: one global threshold and a local one for uneven light
       (binarize.py). The global threshold is Otsu's: the gray level that splits the histogram into a
       dark and a light class as far apart as possible (the largest between-class variance). Each
       result is tried as is and after a 3 x 3 majority filter that removes stray specks.
    3. The first reading that works wins; its finder corners are scaled back to full-size pixels.
    The failure returned is the first that got past "no QR code found", so "found a QR code but could
    not read it" is not hidden by a later attempt that saw nothing.
    """
    attempts = []
    largest = max(image["width"], image["height"])
    factor = largest // 800
    if factor >= 2:
        attempts.append((shrink_image(image, factor), factor))
    attempts.append((image, 1))
    last = fail("no QR code found")
    for picture, scale in attempts:
        for binarize in (binarize_global, binarize_local):
            bits = binarize(picture)
            for attempt in (bits, majority_filter(bits, picture["width"], picture["height"])):
                result = decode_bits(attempt, picture["width"], picture["height"])
                if result["ok"]:
                    for corner in result["value"]["corners"]:
                        corner[0] = corner[0] * scale
                        corner[1] = corner[1] * scale
                    return result
                if last["error"] == "no QR code found":
                    last = result
    return last

# ==== stamp v1 | author=kjFriday | hmac-sha256=1f77630aaade7da5b3fa795468a1df59c1e16e8d750126d3360ae70f6135a321 ====
