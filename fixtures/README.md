# Fixtures

`valid/` holds well-formed HQLN seeds used as a starting corpus. They decode with `python -m harlequin decode` and are safe, small images (thumbnails, a short gradient, an indexed graphic, a zlib-wrapped gray image, and a couple of nested layers).

Regenerate with `python scripts/make_fixtures.py` from the repository root.

There is no crashing corpus in this directory. The decoder is intended to be exercised on untrusted input by the fuzzer that this snapshot does not yet include.
