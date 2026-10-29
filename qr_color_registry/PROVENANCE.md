# Provenance

Code in this project that came from elsewhere in the portfolio (all AGPL-3.0, same author). Sources are the
committed files named here; the SHA-256 is of each source file at that commit.

## Copied from QR Studio (`qr_code_studio`, commit 0f031f7)

| File | From | sha256 of the source | What | Changes |
|---|---|---|---|---|
| `qr_codec.py` | `qr_studio.py` | `58DF5DB001128C95BBA8AB4FCE8D034F87C982E20734F040EB820EA9823DF38B` | The CORE section, lines 55-1674 (tables, Result records, GF(256), Reed-Solomon, encoder, decoder, images, binarizing, finder search, sampling, the test-only picture changes), and `is_link`, `save_matrix`, `describe` | `LEVELS` is now `EC_LEVELS` and the decoder's `distance` is `point_distance` (both names mean something else in the color code). Added: `matrix_to_color_png` (a two-entry palette PNG), a `color` for `matrix_to_svg` and `save_matrix`, `read_svg_matrix` and `svg_color` (this codec's own drawings read back), `dark_color`, `read_qr_file`, `file_kind`, `picture_bytes`, PNG transparency (`tRNS`) and an `rgb` plane in the Image record. Limits: files over 20 MB, pictures over 4096 px a side (checked before any pixel memory is taken) and image data that unpacks past its picture are refused; unknown PNG filter types and damaged PNG/PGM/PPM files are failed Results, never exceptions. `save_matrix` writes beside the target, then moves it into place. |
| `test_qr_codec.py` | `test_qr_studio.py` | `606414AE0EF12EC945AF94D9435FF6B496EB8985DBC547BE4E6758D11BC4EAC6` | The Reed-Solomon, table, matrix and picture tests | Names follow the renames above. The history tests stay in QR Studio. New: color round trips for all 118 usable colors, files, SVG reading, transparency, and the size and damage limits. |
| `qr_palette.py` (`windows_identity`, `set_icon`, `picture_through_tk`, `option_value`, `check`, the paste script in `clipboard_picture`, the job polling and the smoke report in `run_gui`) | `qr_studio.py` | as above | The same calls and patterns | The window itself is new. |

## Copied from Color Voats (`color_tile_recommender`)

| File | From | Commit | sha256 of the source | What | Changes |
|---|---|---|---|---|---|
| `algos.py` | `algos.py` | 7ebbbe9 | `6102BCF000C1D4B8DFC5E3330724FB2D9FCDFDA7C68D5F509DC1A87D74A14D8A` | The whole file: the scorers and aggregators | None. `swatch.py` reaches the cube and OKLab through it (`palette`, `linear`, `oklab`, `color_distance`). |
| `ranking.py` (`WEIGHT_KEYS`, `POSITIVE`, `NAME_RE`, `is_number`, `load`, `read_weights`, `read_preset`, `preset_names`) | `factory.py` | 7ebbbe9 | `C168F61C32E1D1A2FFB2BC277F750C733A4713512A36F95C1DB5A6704F684149` | The preset and weights rules | `load` reads JSON only (the `.toml` branch is gone, so no `tomllib` and Python 3.10 works), allows a byte-order mark, and keeps an `about` text apart from the values. `read_preset` returns that `about` too. Nothing is generated: rankings are worked out from the files each time, so an edit applies at once. |
| `ranking.py` (`rank`) | `test_factory.py` (`reference_rank`) | 7ebbbe9 | `4586FF33A085387DB6E517FC94F400A9202CFD6934511DD251E5B441275F0098` | How a preset ranks with `algos.py` | Renamed `rank`. The tests check it gives Color Voats' own top tens. |
| `presets/*.json`, `weights/*.json` | `presets/*.toml`, `weights/*.toml` | 7ebbbe9 | e.g. `154C676080BB370D76C9CDBFF3F90C2127CF520F7EF80ACF51FD8DFDB170DB9B` (`presets/mixer.toml`), `DB4C77EE7E23E50720D845B888F74CBA440A53DBFE2591B15BE759A5D4318AFD` (`weights/net.toml`) | Every preset and weight | Written as JSON with the same values. Each file's comments became its `about` text. `test_swatch.py` checks the values still match Color Voats' TOML when it is next to this project. |
| `swatch.py` (`HUES`, `normalize_hex`, `color_name`) | `color_voats.py` 0.2.0 | 3b2a93d | `1F3EC2022007961B66669AFB8F6964310102246B97E9AC9FFCDCD80136D33A32` | `HUES`, `normalize_hex`, `color_name` | None. New beside them: `family`, `family_of_word`, contrast, cube index, ranking by preset. |

## Copied from the CRUD hub (`create_read_update_delete_simple_io_data_base`, commit 97e4d6a)

| File | From | sha256 of the source | Changes |
|---|---|---|---|
| `textsafe.py`, `test_textsafe.py` | `textsafe.py`, `test_textsafe.py` | `5C62D9ED0AF5D3473AB0B2104917E9E6F20DD441BC56EEA29638B2D1EC6E7143`, `9A99A86288223BA1F1DCC257F808DCDDCBD3AFB2C002BB6D56AF437C39695EE2` | Unchanged. Cleans questions and typed links, and is the first step when ECP cleans registry text before returning it. QR payloads read from pictures are stored as they are, so exact lookups still match. |

## Copied from Storage Manager (`drive_and_network_storage_manager`, commit 11adc9d)

| File | From | sha256 of the source | Changes |
|---|---|---|---|
| `qr_palette.py` (`reveal_command_line`) | `storage_manager.py` (`reveal_command`, `command_line`) | `59B7E4E4044C638728F81BD0F6B0725140F8BE108A752E6A0753269D2FCE9FC1` | Reduced to the one Explorer case used here: the path is quoted, because Explorer splits its own arguments at "," and "=". |

`registry.py`, `local_inference.py`, `ecp.py`, `mcp_server.py`, `audit.py`, `settings.py`, the GUI and the other tests
are new, and so are `ECP.md`, `planner.json` and `settings.example.json`.

## Designs followed (no code copied)

| What | From | Where |
|---|---|---|
| ECP as three MCP tools, the dual-era rules, the `isError` kinds, the local-inference refusals, the read-only rail's settings, the output caps and labels, and the audit log's fields | *ECP dual rail runtime spec*, v1.0 draft, 2026-10-29 (`research/ecp_dual_rail_runtime_spec.md`) | `mcp_server.py`, `ecp.py`, `local_inference.py`, `registry.py`, `audit.py`; [ECP.md](ECP.md) §16 lists the differences |
