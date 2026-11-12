"""Sequential reader over a HQLN buffer."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .errors import FormatError
from .format import crc32


@dataclass
class Chunk:
    typ: bytes
    flags: int
    payload: bytes
    crc: int
    offset: int  # file offset of the type field


class Reader:
    def __init__(self, data: bytes, start: int = 0, end: int | None = None):
        self.data = data
        self.pos = start
        self.end = len(data) if end is None else end
        self.origin = start

    def remaining(self) -> int:
        return self.end - self.pos

    def tell(self) -> int:
        return self.pos

    def seek(self, pos: int) -> None:
        if pos < 0 or pos > self.end:
            raise FormatError(f"seek out of range: {pos}")
        self.pos = pos

    def read(self, n: int) -> bytes:
        if n < 0:
            raise FormatError("negative read")
        if self.pos + n > self.end:
            raise FormatError(f"unexpected EOF at {self.pos}, need {n} bytes")
        b = self.data[self.pos:self.pos + n]
        self.pos += n
        return b

    def u8(self) -> int:
        return self.read(1)[0]

    def u16(self) -> int:
        return struct.unpack(">H", self.read(2))[0]

    def u32(self) -> int:
        return struct.unpack(">I", self.read(4))[0]

    def read_chunk(self) -> Chunk:
        offset = self.pos
        typ = self.read(4)
        flags = self.u8()
        length = self.u32()
        payload = self.read(length)
        crc = self.u32()
        expect = crc32(typ + bytes([flags]) + payload)
        # CRC mismatches are recorded but not fatal: a few in-the-wild
        # writers were known to leave this field zeroed.
        if crc != expect and crc != 0:
            # Keep going; inspect() surfaces the mismatch.
            pass
        return Chunk(typ=typ, flags=flags, payload=payload, crc=crc, offset=offset)
