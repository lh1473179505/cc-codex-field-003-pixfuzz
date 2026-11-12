"""Helpers to write well-formed HQLN files. Used by the fixture generator."""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

# allow running as a script from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harlequin.format import (
    COLOR_DIRECT,
    COLOR_INDEXED,
    COMPRESS_RAW,
    COMPRESS_ZLIB,
    FILTER_NONE,
    MAGIC,
    TYPE_DATA,
    TYPE_END,
    TYPE_IHDR,
    TYPE_NEST,
    TYPE_PLTE,
    TYPE_TEXT,
    VERSION,
    crc32,
)


def chunk(typ: bytes, payload: bytes, flags: int = 0, crc_zero: bool = False) -> bytes:
    body = typ + bytes([flags]) + struct.pack(">I", len(payload)) + payload
    c = 0 if crc_zero else crc32(typ + bytes([flags]) + payload)
    return body + struct.pack(">I", c)


def ihdr(w, h, channels=3, bit_depth=8, color_type=COLOR_DIRECT, compression=COMPRESS_RAW, flags=0):
    payload = struct.pack(">IIBBBB", w, h, channels, bit_depth, color_type, compression)
    return chunk(TYPE_IHDR, payload, flags=flags)


def plte(entries: list[tuple[int, int, int]], flags=0):
    payload = b"".join(bytes(e) for e in entries)
    return chunk(TYPE_PLTE, payload, flags=flags)


def data_raw(rows: list[bytes], filters: list[int] | None = None, compression=COMPRESS_RAW, flags=0):
    h = len(rows)
    raw = bytearray()
    for y, row in enumerate(rows):
        f = 0 if not filters else filters[y]
        raw.append(f)
        raw.extend(row)
    payload = bytes(raw)
    if compression == COMPRESS_ZLIB:
        payload = zlib.compress(payload, level=9)
    return chunk(TYPE_DATA, payload, flags=flags)


def text(key: str, value: str, flags=0):
    payload = key.encode("utf-8") + b"\x00" + value.encode("utf-8")
    return chunk(TYPE_TEXT, payload, flags=flags)


def nest(inner: bytes, reserved: int = 0, flags: int = 0):
    payload = struct.pack(">I", reserved) + inner
    return chunk(TYPE_NEST, payload, flags=flags)


def end(flags=0):
    return chunk(TYPE_END, b"", flags=flags)


def document(*parts: bytes) -> bytes:
    return MAGIC + bytes([VERSION]) + b"".join(parts)
