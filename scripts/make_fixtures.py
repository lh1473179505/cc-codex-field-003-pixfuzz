#!/usr/bin/env python3
"""Regenerate fixtures/valid. Run from the repository root."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from hqln_write import (  # type: ignore
    COLOR_INDEXED,
    COMPRESS_ZLIB,
    data_raw,
    document,
    end,
    ihdr,
    nest,
    plte,
    text,
)
from harlequin.format import FILTER_SUB, FILTER_UP, FILTER_NONE


def solid_row(w, ch, rgb):
    if ch == 1:
        return bytes([rgb[0]] * w)
    pix = []
    for _ in range(w):
        pix.extend(rgb[:ch])
    return bytes(pix)


def write(name: str, data: bytes) -> None:
    path = ROOT / "fixtures" / "valid" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    print(f"wrote {path} ({len(data)} bytes)")


def main() -> None:
    # 1. tiny RGB, filter none
    rows = [solid_row(4, 3, (255, 0, 0)),
            solid_row(4, 3, (0, 255, 0)),
            solid_row(4, 3, (0, 0, 255))]
    tiny = document(
        ihdr(4, 3, 3),
        text("title", "tiny-rgb"),
        text("dpi", "72"),
        data_raw(rows, filters=[FILTER_NONE] * 3),
        end(),
    )
    write("tiny_rgb.hqln", tiny)

    # 2. RGB with sub/up filters (first row none, then sub, then up)
    w, h = 8, 5
    rows2 = []
    for y in range(h):
        row = bytearray()
        for x in range(w):
            row.extend(((x * 20 + y * 7) & 255, (y * 40) & 255, (255 - x * 10) & 255))
        rows2.append(bytes(row))
    # store filtered bytes: we'll put unfiltered samples with filter tags that
    # the writer writes as "already raw samples + filter byte". The decoder
    # *applies* the predictor, so for valid files we must either use filter 0
    # or pre-encode predictors. Use filter 0 here and a second file with
    # correctly encoded SUB.
    grad = document(
        ihdr(w, h, 3),
        text("title", "gradient"),
        data_raw(rows2, filters=[FILTER_NONE] * h),
        end(),
    )
    write("gradient_rgb.hqln", grad)

    # correctly encoded SUB filter file
    def encode_sub(row, ch=3):
        out = bytearray(len(row))
        for i, b in enumerate(row):
            left = row[i - ch] if i >= ch else 0
            out[i] = (b - left) & 0xFF
        return bytes(out)

    def encode_up(row, prev):
        return bytes((b - p) & 0xFF for b, p in zip(row, prev))

    enc_rows = [rows2[0], encode_sub(rows2[1]), encode_up(rows2[2], rows2[1]),
                encode_sub(rows2[3]), encode_up(rows2[4], rows2[3])]
    filters = [FILTER_NONE, FILTER_SUB, FILTER_UP, FILTER_SUB, FILTER_UP]
    filt = document(
        ihdr(w, h, 3),
        text("title", "filtered"),
        data_raw(enc_rows, filters=filters),
        end(),
    )
    write("filtered_rgb.hqln", filt)

    # 3. indexed, palette of 4 colors, all samples in range
    pal = [(0, 0, 0), (255, 80, 0), (0, 180, 80), (40, 40, 255)]
    idx_rows = [
        bytes([0, 1, 2, 3, 0, 1]),
        bytes([1, 1, 2, 2, 3, 3]),
        bytes([3, 2, 1, 0, 3, 2]),
        bytes([0, 0, 0, 1, 1, 1]),
    ]
    indexed = document(
        ihdr(6, 4, 1, color_type=COLOR_INDEXED),
        plte(pal),
        text("title", "indexed-4"),
        data_raw(idx_rows, filters=[FILTER_NONE] * 4),
        end(),
    )
    write("indexed_4.hqln", indexed)

    # 4. zlib-compressed gray
    gray_rows = [bytes((x + y * 3) & 255 for x in range(16)) for y in range(8)]
    zgray = document(
        ihdr(16, 8, 1, compression=COMPRESS_ZLIB),
        text("title", "zlib-gray"),
        data_raw(gray_rows, filters=[FILTER_NONE] * 8, compression=COMPRESS_ZLIB),
        end(),
    )
    write("zlib_gray.hqln", zgray)

    # 5. nested thumbnail (one level), reserved=0, flags=0
    thumb_rows = [solid_row(2, 3, (200, 200, 50)), solid_row(2, 3, (50, 50, 200))]
    thumb = document(
        ihdr(2, 2, 3),
        text("title", "thumb"),
        data_raw(thumb_rows, filters=[FILTER_NONE, FILTER_NONE]),
        end(),
    )
    parent_rows = [solid_row(4, 3, (10, 20, 30))] * 3
    nested = document(
        ihdr(4, 3, 3),
        text("title", "with-thumb"),
        nest(thumb, reserved=0, flags=0),
        data_raw(parent_rows, filters=[FILTER_NONE] * 3),
        end(),
    )
    write("nested_thumb.hqln", nested)

    # 6. offset-reserved seed: NEST flags=0, reserved points at the NEST chunk
    # itself. Harmless until flags bit 0 is set. We build the file, then patch
    # the reserved field once offsets are known.
    # Layout: magic+ver (5) + IHDR chunk + TEXT + NEST + DATA + END
    prefix = ihdr(4, 2, 3) + text("title", "offset-reserved")
    # reserved is the start of the file (0). Harmless while flags bit 0 is clear;
    # the field is just a leftover placeholder in this seed.
    nest_chunk = nest(thumb, reserved=0, flags=0)
    body_rows = [solid_row(4, 3, (9, 8, 7)), solid_row(4, 3, (7, 8, 9))]
    offset_doc = document(prefix, nest_chunk, data_raw(body_rows, filters=[FILTER_NONE, FILTER_NONE]), end())
    write("nested_offset_reserved.hqln", offset_doc)

    # 7. two-level nest (still shallow, flags 0)
    mid = document(
        ihdr(2, 1, 3),
        text("title", "mid"),
        nest(thumb, reserved=0, flags=0),
        data_raw([solid_row(2, 3, (1, 2, 3))], filters=[FILTER_NONE]),
        end(),
    )
    two = document(
        ihdr(3, 1, 3),
        text("title", "two-level"),
        nest(mid, reserved=0, flags=0),
        data_raw([solid_row(3, 3, (4, 5, 6))], filters=[FILTER_NONE]),
        end(),
    )
    write("nested_two_level.hqln", two)

    # 8. REPT with count=1 wrapping the tiny RGB document as a single layer
    from hqln_write import chunk  # type: ignore
    from harlequin.format import TYPE_REPT
    rept_chunk = chunk(TYPE_REPT, (1).to_bytes(2, "big") + tiny, flags=0)
    rept_rows = [solid_row(3, 3, (11, 22, 33))]
    rept_doc = document(
        ihdr(3, 1, 3),
        text("title", "repeat-once"),
        rept_chunk,
        data_raw(rept_rows, filters=[FILTER_NONE]),
        end(),
    )
    write("repeat_once.hqln", rept_doc)


if __name__ == "__main__":
    main()
