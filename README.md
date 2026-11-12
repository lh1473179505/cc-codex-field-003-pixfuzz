# pixfuzz / harlequin

Harlequin (`HQLN`) is a small experimental layered image container used here as a local test codec. The decoder in the `harlequin` package already understands the documented chunk layout and can inspect or decode the checked-in fixtures.

This snapshot does **not** implement the coverage-guided fuzzer. The `pixfuzz` CLI entry point is stubbed so work can start from a real package and a real parser, not an empty folder.

## Requirements

- Python 3.11+ (stdlib only)
- No containers. Do not add Docker files.

## Usage

```bash
python -m harlequin inspect fixtures/valid/tiny_rgb.hqln
python -m harlequin decode fixtures/valid/tiny_rgb.hqln --out /tmp/tiny.ppm
```

The intended next piece is:

```bash
python -m pixfuzz run --seed-dir fixtures/valid --out-dir /tmp/pixfuzz-out --max-time 20
```

See `docs/format.md` for the container layout. `scripts/make_fixtures.py` regenerates the valid fixtures.

## Layout

- `harlequin/` — container parser, inspect, and PPM decode
- `pixfuzz/` — fuzzer CLI stub (not implemented yet)
- `fixtures/valid/` — well-formed seeds
- `fixtures/hqln.dict` — token dictionary useful for mutation
- `docs/format.md` — format notes
