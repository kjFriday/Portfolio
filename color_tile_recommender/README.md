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

```bash
python -m unittest discover -p "test_*.py"
```

Also `--preset NAME` (default `mixer`), `--data FILE` (keep everything in another file), `--selftest`, `--version` and `--smoke FILE`.

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

`python factory.py` regenerates every ranker, and `python factory.py --check` exits 1 when one is out of date. The rankers are committed so their code can be read and reviewed; don't edit them by hand.

## Porting to another language

The layout is QR Studio's:

- `algos.py` is plain functions over plain records with explicit loops: port it first. The generated rankers are already standalone.
- `test_algos.py`, `test_factory.py` and `test_color_voats.py` hold the checks to port alongside.
- `color_voats.py` keeps its CORE (posts, votes, comments, saves, the store and the feed's order) apart from the tkinter GUI, which only calls the core.

## Icon

`icon/tiles-16.png` is a 16×16 pixel glyph of nine color tiles drawn for this project; the other sizes are made from it by the portfolio's `tools/pixel_icons.py`, enlarged by whole pixels only. See [icon/README.md](icon/README.md).

## License

AGPL-3.0, see [LICENSE](LICENSE).
