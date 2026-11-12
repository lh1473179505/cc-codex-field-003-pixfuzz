# pixfuzz / harlequin

Harlequin (`HQLN`) is a small experimental layered image container used here as a local test codec. The decoder in the `harlequin` package already understands the documented chunk layout and can inspect or decode the checked-in fixtures. The `pixfuzz` package implements a coverage-guided mutation fuzzer for the decoder (stdlib only).

## Requirements

- Python 3.11+ (stdlib only)
- No containers. Do not add Docker files.

## Usage

```bash
python -m harlequin inspect fixtures/valid/tiny_rgb.hqln
python -m harlequin decode fixtures/valid/tiny_rgb.hqln --out /tmp/tiny.ppm
```

Run the fuzzer:

```bash
python -m pixfuzz run --seed-dir fixtures/valid --out-dir /tmp/pixfuzz-out --max-time 20 --timeout 0.2 --rss-mb 256 --dict fixtures/hqln.dict
```

The fuzzer decodes mutated seeds in-process under a per-input wall-clock
timeout (`--timeout`) and address-space cap (`--rss-mb`), traces real line
coverage of the `harlequin` package to grow `<out-dir>/corpus`, and saves
deduplicated crashing inputs (traceback fingerprint) under
`<out-dir>/crashes`. A JSON summary lands in `<out-dir>/report.json`
(override with `--report`); each crash entry includes a replay command.
`--jobs N` runs N parallel workers sharing the corpus directory.

See `docs/format.md` for the container layout. `scripts/make_fixtures.py` regenerates the valid fixtures.

## Layout

- `harlequin/` — container parser, inspect, and PPM decode
- `pixfuzz/` — coverage-guided fuzzer (CLI, tracer, mutator, crash dedup)
- `fixtures/valid/` — well-formed seeds
- `fixtures/hqln.dict` — token dictionary useful for mutation
- `docs/format.md` — format notes
