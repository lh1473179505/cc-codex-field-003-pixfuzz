"""Pretty-print the chunk tree of a HQLN file."""

from __future__ import annotations

import struct

from .bitstream import Reader
from .format import (
    MAGIC,
    TYPE_DATA,
    TYPE_END,
    TYPE_IHDR,
    TYPE_NEST,
    TYPE_PLTE,
    TYPE_REPT,
    TYPE_TEXT,
    VERSION,
    crc32,
)


def inspect_bytes(data: bytes, indent: int = 0) -> list[str]:
    lines: list[str] = []
    pad = "  " * indent
    r = Reader(data)
    magic = r.read(4)
    ver = r.u8()
    lines.append(f"{pad}magic={magic!r} version={ver}")
    if magic != MAGIC or ver != VERSION:
        lines.append(f"{pad}!! unexpected header")
        return lines
    while r.remaining() > 0:
        chunk = r.read_chunk()
        expect = crc32(chunk.typ + bytes([chunk.flags]) + chunk.payload)
        crc_note = "ok" if chunk.crc == expect or chunk.crc == 0 else f"mismatch got=0x{chunk.crc:08x} expect=0x{expect:08x}"
        typ = chunk.typ
        extra = ""
        if typ == TYPE_IHDR and len(chunk.payload) >= 14:
            w, h, ch, bd, ct, comp = struct.unpack(">IIBBBB", chunk.payload[:14])
            extra = f" {w}x{h} channels={ch} bit={bd} color={ct} comp={comp}"
        elif typ == TYPE_PLTE:
            extra = f" entries={len(chunk.payload)//3}"
        elif typ == TYPE_TEXT and b"\x00" in chunk.payload:
            key, _, val = chunk.payload.partition(b"\x00")
            extra = f" {key!r}={val[:60]!r}"
        elif typ == TYPE_REPT and len(chunk.payload) >= 2:
            extra = f" count={struct.unpack('>H', chunk.payload[:2])[0]}"
        elif typ == TYPE_NEST and len(chunk.payload) >= 4:
            reserved = struct.unpack(">I", chunk.payload[:4])[0]
            extra = f" reserved={reserved} inner={len(chunk.payload)-4}B"
        lines.append(f"{pad}{typ.decode('latin1', 'replace')} flags=0x{chunk.flags:02x} len={len(chunk.payload)} crc={crc_note} @{chunk.offset}{extra}")
        if typ == TYPE_NEST and len(chunk.payload) >= 4 and not (chunk.flags & 0x01):
            lines.extend(inspect_bytes(chunk.payload[4:], indent + 1))
        if typ == TYPE_END:
            break
    return lines


def inspect_path(path: str) -> str:
    with open(path, "rb") as f:
        data = f.read()
    return "\n".join(inspect_bytes(data))
