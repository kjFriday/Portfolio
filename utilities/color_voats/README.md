# Generic Company Color Voats

A desktop program that works like a social feed where every post is a color. Your Good and Bad votes ("voats") teach it what to show you first.

The feed starts with the 216 colors of the 6×6×6 cube, and you can post colors of your own. Each post shows:

- who posted it and when;
- the color, its caption and its hex code;
- **Good** and **Bad** buttons. One vote per post: press yours again to take it back, or press the other one to switch;
- **Save**, which keeps the post in your Saved tab;
- a comment section: write a comment and press Comment or Enter. Delete removes one of your comments.

| Tab | What it holds |
|---|---|
| Feed | All posts, **For you** (ranked by your votes, see below) or **New** (newest first), 20 at a time with Show more. Pick the ranking preset from the list. Votes don't reshuffle what you're reading; Refresh (or F5) re-ranks. |
| Saved | The posts you saved, the most recently saved first. |
| New post | Pick a color (or type `#rrggbb`), add a caption of up to 140 characters (or leave it empty to use the color's name), then Post. Each color can be posted once, and you can delete your own posts. |

Everything stays on this computer, in `%LOCALAPPDATA%\Generic Company Inc\GenericCompany.ColorVoats\social.json`. Delete that file to start over.

Python 3.11+ standard library only (tkinter for the window, `tomllib` for the TOML files).

```bash
python color_voats.py
```

Also `--preset NAME` (default `mixer`), `--data FILE` (keep everything in another file), `--selftest`, `--version` and `--smoke FILE`.

## How it works

1. `color_voats.py` reads the command line. `--version` and `--selftest` (`voats_selftest.py`) answer at once, before the store or tkinter is touched.
2. `voats_core.load_ranker()` asks `factory.ensure()` to make sure `rankers/ranker_<preset>.py` matches its preset and weights, writes it again if not, and loads it.
3. Only then is `voats_gui.py` imported. `run_gui()` opens a `VoatsWindow`, which loads the store with `voats_core.load_store()` and builds the Feed, Saved and New post tabs.
4. The 216 built-in posts are never stored: `all_posts()` makes them from `algos.palette()` each time and adds your own.
5. Each button calls one `voats_core` function (`vote`, `toggle_save`, `add_comment`, `add_post`, a delete), and the window saves the store at once with `save_store()`, through a temporary file.
6. On Refresh (F5), a sort change or a preset change, `feed_order()` turns your votes into the voat log (`voat_log()`, oldest first) and the ranker's `rank(voats, colors)` gives the For you order.

Where state lives:

| What | Where |
|---|---|
| Your posts, votes, comments and saves | `social.json` in `%LOCALAPPDATA%\Generic Company Inc\GenericCompany.ColorVoats\` (`voats_core.data_path()`), or the `--data` file. QR Palette reads it to import your votes. |
| How For you ranks | `presets/*.toml` and `weights/*.toml`, read by `factory.py` |
| The rankers | `rankers/ranker_<preset>.py`, generated beside the program |
| Window settings | none are kept; the preset and sort start fresh each launch |

A `--smoke` run uses an empty store in memory and never reads or writes `social.json`. No database and no registry.

## Code map

In reading order:

| File | What it holds |
|---|---|
| `color_voats.py` | The entry point: `__version__`, the command line and `main()`. |
| `voats_core.py` | The core, no GUI: records, the store file, posts, votes, comments, saves, color names (`HUES`, `color_name`), `feed_order()` and `load_ranker()`. Start at `feed_order()` and `load_store()`. |
| `voats_gui.py` | The window, `VoatsWindow` (tkinter): the tabs, the post cards, the scrolling feeds and the `--smoke` report. Start at `VoatsWindow.__init__`, then `make_card` and `refresh_feed`. |
| `voats_selftest.py` | The quick checks `--selftest` runs (algos, factory, feed, words). |
| `algos.py` | The scorers (net, wilson, similar, explore) and aggregators (blend, mixer). Start at `mixer()` and `order_by()`. |
| `factory.py` | Reads a preset and its weights and writes a standalone ranker. Start at `generate()`. |
| `presets/`, `weights/` | The ranking's TOML files (below). |
| `rankers/` | The generated rankers, one per preset. Don't edit them. |
| `tests/test_algos.py` | The palette, OKLab, each scorer and the aggregators on hand-built voat logs. |
| `tests/test_factory.py` | Each shipped ranker against an independent reference, repeatable output, and the file rules. |
| `tests/test_color_voats.py` | The core: store, posts, votes, comments, saves and the feed's order; imports the window module without opening it. |
| `setup.json` | The installer's description for Wizard Maker. |
| `icon/` | The app icon (see below). |

## Developing

Run everything from this folder (`utilities/color_voats`).

| Task | Command |
|---|---|
| Run | `python color_voats.py` |
| All tests | `python -m unittest discover -s tests` |
| One suite | `python -m unittest discover -s tests -p test_factory.py` |
| Self-test | `python color_voats.py --selftest` |
| Smoke check | `python color_voats.py --smoke report.json` opens the window, votes, saves, comments and posts in memory, writes a JSON report and closes |
| Rankers up to date? | `python factory.py --check` (exit 1 when one is stale) |
| Regenerate rankers | `python factory.py` |
| Package | `wizard-maker.exe build setup.json` with [Wizard Maker](../../company/wizard_maker/README.md); it writes `dist/Generic Company Color Voats-<version>-setup.exe` |

The Dev Console (`tools/dev_console`) runs the same launch and test commands.

Where to add things:

- **A new preset**: add `presets/<name>.toml` naming an existing algo, then `python color_voats.py --preset NAME`. Add it to the presets table below and, if QR Palette should rank with it, a JSON copy in `../qr_palette/presets/`.
- **A new scorer**: write the function in `algos.py` and add its name to `SCORERS`; in `factory.py` add its keys to `WEIGHT_KEYS`, its helpers to `NEEDS` and the functions to `COPY_ORDER`; add `weights/<name>.toml` and tests in `tests/test_algos.py`. Then run `python factory.py`.
- **A new thing to do on a post**: the store change goes in `voats_core.py` (changing the store in place, checked in `load_store()`), the button in `VoatsWindow.make_card` in `voats_gui.py`, and the tests in `tests/test_color_voats.py`.

Twins (QR Palette keeps copies; change both, see `../qr_palette/PROVENANCE.md`):

| Here | There |
|---|---|
| `algos.py` | `../qr_palette/algos.py`, identical apart from the header |
| `HUES`, `normalize_hex`, `color_name` in `voats_core.py` | `../qr_palette/swatch.py` |
| `presets/*.toml`, `weights/*.toml` | `../qr_palette/presets/*.json`, `../qr_palette/weights/*.json`, same values |
| The `social.json` format | `../qr_palette/votes.py` imports it |

QR Palette's `tests/test_swatch.py` checks the names, the presets and weights, and the top tens against this project when it sits beside it.

Traps the code warns about:

- **Version**: `__version__` in `color_voats.py` and `version` in `setup.json` are bumped together by the Dev Console; keep `__version__` the first such line.
- **Rankers are generated**: their first line, `# Generated by factory.py - do not edit.`, is what keeps `tools/stamp.py` from stamping them, and `test_factory.py` checks it.
- **Comments inside `algos.py` functions are copied**: the factory copies each function's text into the rankers, so a docstring or comment edit inside a function makes every ranker stale. Notes go above the `def`, at column 0.
- **Runs write `rankers/`**: a launch, a preset switch, `--selftest` and the tests all rewrite a stale ranker, so run `python factory.py --check` first after changing `algos.py` or `factory.py`.
- **Stamps**: each source file ends with a stamp line. `python tools/stamp.py --check`, from the portfolio root, lists files changed since they were stamped.

## How For you is ranked: the algo aggregation factory

1. **Algos** (`algos.py`) each score the colors from the voat log. An algo's weights live in `weights/<algo>.toml` (or `.json`).
2. **Presets** (`presets/<name>.toml` or `.json`) name the algo that ranks (`algo`) and feed it what it uses (`uses`).
3. **The factory** (`factory.py`) reads a preset and its algos' weights and generates `rankers/ranker_<name>.py`: the weights as constants, plus the functions it needs, copied unchanged from `algos.py`. A ranker runs on its own: `rank(voats, colors)` returns the colors best first.
4. **The window** runs the ranker of the preset you pick, with your votes oldest first as the voat log (Good is an upvoat, Bad a downvoat). When that ranker is missing or no longer matches its files, it is generated again first.

| Algo | Scores a color by | Weights |
|---|---|---|
| net | upvoats × up − downvoats × down | `up`, `down` |
| wilson | the lower bound of its share of upvoats (Wilson score), so 5 of 5 beats 1 of 1 | `z` |
| similar | the pull of voats on nearby colors in OKLab, a space where equal distances look about equally different; 0 beyond `reach` | `reach`, `up`, `down` |
| explore | its distance to the nearest voated color, capped at `far`, so new ground comes first | `far` |
| blend | the weighted sum of the algos in `uses`, each scaled to 0..1 | the preset's `uses` table |
| mixer | the chain of algos in `uses`, handing on whenever one stalls (below) | `tie`, `streak`, `budget` |

The **mixer** ranks by the lead algo of its chain and hands on when that algo stalls:

- **Ties**: colors the lead scores the same (within `tie`) are sorted by the next algo, and so on down the chain.
- **Downvoat streak**: `streak` downvoats in a row pass the lead to the next algo in the chain. The lead is read from your votes, so taking a vote back undoes it too.
- **Work budget**: an algo that would take more than `budget` steps on the color set is skipped. It counts steps, not seconds, so the order never depends on the machine.

Whatever is still tied at the end goes in discovery order: the darkest color first, then always the color farthest from those already placed. So every order is total and the same on every run.

| Preset | Algo | Uses |
|---|---|---|
| `mixer` (default) | mixer | net → wilson → similar → explore |
| `balanced` | blend | similar 0.6, explore 0.3, net 0.1 |
| `popular` | blend | wilson 0.7, net 0.3 |
| `discover` | blend | explore 0.7, similar 0.3 |

To make a preset, add `presets/<name>.toml` and run it:

```bash
python color_voats.py --preset NAME
```

`python factory.py` regenerates every ranker, and `python factory.py --check` exits 1 when one is out of date. The rankers are committed so their code can be read and reviewed; don't edit them by hand (see Developing for what makes them stale).

## Porting to another language

- `algos.py` is plain functions over plain records with explicit loops: port it first. The generated rankers are already standalone.
- `tests/test_algos.py`, `tests/test_factory.py` and `tests/test_color_voats.py` hold the checks to port alongside.
- `voats_core.py` keeps the core (posts, votes, comments, saves, the store and the feed's order) apart from the tkinter window in `voats_gui.py`, which only calls the core.

## Icon

`icon/tiles-16.png` is a 16×16 pixel glyph of nine color tiles drawn for this project; the other sizes are made from it by the portfolio's `tools/pixel_icons.py`, enlarged by whole pixels only. See [icon/README.md](icon/README.md).

## License

AGPL-3.0, see [LICENSE](LICENSE).
