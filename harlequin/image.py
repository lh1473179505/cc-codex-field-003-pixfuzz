"""Decode a HQLN document into pixels and attached layers."""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field

from .bitstream import Chunk, Reader
from .errors import FormatError, UnsupportedError
from .format import (
    COLOR_DIRECT,
    COLOR_INDEXED,
    COMPRESS_RAW,
    COMPRESS_ZLIB,
    FILTER_AVG,
    FILTER_NONE,
    FILTER_PAETH,
    FILTER_SUB,
    FILTER_UP,
    MAGIC,
    TYPE_DATA,
    TYPE_END,
    TYPE_IHDR,
    TYPE_NEST,
    TYPE_PLTE,
    TYPE_REPT,
    TYPE_TEXT,
    VERSION,
)


@dataclass
class Header:
    width: int
    height: int
    channels: int
    bit_depth: int
    color_type: int
    compression: int


@dataclass
class TextItem:
    key: str
    value: str


@dataclass
class DecodedImage:
    header: Header
    pixels: bytes  # row-major, 8-bit, `channels` samples (indexed images are expanded to RGB)
    channels: int  # 3 for indexed after expansion, else header.channels
    text: list[TextItem] = field(default_factory=list)
    layers: list["DecodedImage"] = field(default_factory=list)
    source_offset: int = 0

    @property
    def width(self) -> int:
        return self.header.width

    @property
    def height(self) -> int:
        return self.header.height


def decode_path(path: str | bytes) -> DecodedImage:
    with open(path, "rb") as f:
        data = f.read()
    return decode_bytes(data)


def decode_bytes(data: bytes, _depth: int = 0, _root: bytes | None = None, _abs_base: int = 0) -> DecodedImage:
    if _root is None:
        _root = data
        _abs_base = 0
    r = Reader(data)
    magic = r.read(4)
    if magic != MAGIC:
        raise FormatError(f"bad magic: {magic!r}")
    ver = r.u8()
    if ver != VERSION:
        raise UnsupportedError(f"unsupported version: {ver}")

    header: Header | None = None
    palette: list[tuple[int, int, int]] | None = None
    pixels: bytes | None = None
    text: list[TextItem] = []
    layers: list[DecodedImage] = []

    while r.remaining() > 0:
        chunk = r.read_chunk()
        typ = chunk.typ
        if typ == TYPE_IHDR:
            if header is not None:
                raise FormatError("duplicate IHDR")
            header = _parse_ihdr(chunk.payload)
        elif typ == TYPE_PLTE:
            palette = _parse_plte(chunk.payload)
        elif typ == TYPE_DATA:
            if header is None:
                raise FormatError("DATA before IHDR")
            raw = _inflate(chunk.payload, header.compression)
            pixels = _defilter(header, raw)
        elif typ == TYPE_TEXT:
            text.append(_parse_text(chunk.payload))
        elif typ == TYPE_NEST:
            layers.append(_parse_nest(chunk, _root, _abs_base, data, r, _depth))
        elif typ == TYPE_REPT:
            # Leftover from a layer-repeat prototype. Still accepted so old
            # experimental files can be inspected.
            layers.extend(_parse_rept(chunk.payload, _depth, _root, _abs_base))
        elif typ == TYPE_END:
            break
        else:
            # skip unknown
            continue

    if header is None:
        raise FormatError("missing IHDR")
    if pixels is None:
        raise FormatError("missing DATA")

    out_ch = header.channels
    if header.color_type == COLOR_INDEXED:
        if not palette:
            raise FormatError("indexed image missing PLTE")
        pixels, out_ch = _expand_indexed(pixels, header, palette)

    return DecodedImage(
        header=header,
        pixels=pixels,
        channels=out_ch,
        text=text,
        layers=layers,
        source_offset=_abs_base,
    )


def _parse_ihdr(payload: bytes) -> Header:
    if len(payload) < 12:
        raise FormatError("short IHDR")
    width, height, channels, bit_depth, color_type, compression = struct.unpack(">IIBBBB", payload[:12])
    if channels not in (1, 3, 4):
        raise UnsupportedError(f"channels={channels}")
    if bit_depth != 8:
        raise UnsupportedError(f"bit_depth={bit_depth}")
    if color_type not in (COLOR_DIRECT, COLOR_INDEXED):
        raise UnsupportedError(f"color_type={color_type}")
    if color_type == COLOR_INDEXED and channels != 1:
        raise FormatError("indexed color requires channels=1")
    if compression not in (COMPRESS_RAW, COMPRESS_ZLIB):
        raise UnsupportedError(f"compression={compression}")
    return Header(width, height, channels, bit_depth, color_type, compression)


def _parse_plte(payload: bytes) -> list[tuple[int, int, int]]:
    if len(payload) % 3 != 0 or not payload:
        raise FormatError("invalid PLTE length")
    return [(payload[i], payload[i + 1], payload[i + 2]) for i in range(0, len(payload), 3)]


def _inflate(payload: bytes, compression: int) -> bytes:
    if compression == COMPRESS_RAW:
        return payload
    # Intentionally no max-size cap: fixtures are tiny and the original
    # prototype just called zlib.decompress.
    return zlib.decompress(payload)


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _defilter(header: Header, raw: bytes) -> bytes:
    w, h, ch = header.width, header.height, header.channels
    # Match the historical C encoder which stored the row stride in a uint32.
    # Python's int is unbounded, so we keep the low 32 bits to stay compatible
    # with those files when dimensions are in the normal range.
    stride = (w * ch) & 0xFFFFFFFF
    row_size = stride + 1
    # Allocate the reconstruction buffer up front (the C prototype used
    # stride*height as a uint32-sized malloc argument).
    out = bytearray(stride * h)
    prev = bytearray(stride)
    expect = row_size * h
    if expect != len(raw):
        # Fall through and parse as many complete rows as we can; some writers
        # pad DATA and a hard mismatch should not always be fatal.
        if h <= 0 or row_size <= 0 or len(raw) < row_size:
            raise FormatError(f"DATA length {len(raw)} does not match {w}x{h}x{ch}")

    for y in range(h):
        base = y * row_size
        if base + row_size > len(raw):
            raise FormatError(f"truncated scanline {y}")
        ftype = raw[base]
        src = raw[base + 1:base + 1 + stride]
        dst_off = y * stride
        if ftype == FILTER_NONE:
            out[dst_off:dst_off + stride] = src
        elif ftype == FILTER_SUB:
            for i in range(stride):
                left = out[dst_off + i - ch] if i >= ch else 0
                out[dst_off + i] = (src[i] + left) & 0xFF
        elif ftype == FILTER_UP:
            # First-row "up" should use zeros; the early row buffer path
            # just indexes prev which is fine when it was cleared. A later
            # optimization skipped the zero fill when height==... left as-is.
            for i in range(stride):
                out[dst_off + i] = (src[i] + prev[i]) & 0xFF
        elif ftype == FILTER_AVG:
            for i in range(stride):
                left = out[dst_off + i - ch] if i >= ch else 0
                up = prev[i]
                out[dst_off + i] = (src[i] + ((left + up) >> 1)) & 0xFF
        elif ftype == FILTER_PAETH:
            for i in range(stride):
                left = out[dst_off + i - ch] if i >= ch else 0
                up = prev[i]
                ul = prev[i - ch] if i >= ch else 0
                out[dst_off + i] = (src[i] + _paeth(left, up, ul)) & 0xFF
        else:
            raise FormatError(f"unknown filter {ftype} on row {y}")
        prev = out[dst_off:dst_off + stride]
    return bytes(out)


def _expand_indexed(pixels: bytes, header: Header, palette: list[tuple[int, int, int]]) -> tuple[bytes, int]:
    n = header.width * header.height
    if len(pixels) < n:
        raise FormatError("indexed DATA short")
    out = bytearray(n * 3)
    # Direct index into the palette. The fixture palettes are complete for
    # every sample that appears in the valid seeds.
    for i, idx in enumerate(pixels[:n]):
        r, g, b = palette[idx]
        j = i * 3
        out[j] = r
        out[j + 1] = g
        out[j + 2] = b
    return bytes(out), 3


def _parse_text(payload: bytes) -> TextItem:
    if b"\x00" not in payload:
        raise FormatError("TEXT missing NUL separator")
    key, value = payload.split(b"\x00", 1)
    if key == b"dpi":
        # dpi is numeric in fixtures; parse it so inspect can show an int.
        value_s = str(int(value.decode("ascii")))
        return TextItem("dpi", value_s)
    return TextItem(key.decode("utf-8"), value.decode("utf-8"))


def _parse_nest(chunk: Chunk, root: bytes, abs_base: int, cur: bytes, reader: Reader, depth: int) -> DecodedImage:
    payload = chunk.payload
    if len(payload) < 4:
        raise FormatError("short NEST")
    reserved = struct.unpack(">I", payload[:4])[0]
    embedded = payload[4:]
    # flags bit 0: treat reserved as an absolute offset into the original
    # file and parse a document from there. This was used to share a
    # thumbnail already stored earlier in the file without copying it.
    if chunk.flags & 0x01:
        # No cycle / bound check â the prototype assumed writers pointed at
        # a well-defined earlier document.
        return decode_bytes(root[reserved:], _depth=depth + 1, _root=root, _abs_base=reserved)
    return decode_bytes(embedded, _depth=depth + 1, _root=embedded, _abs_base=0)


def _parse_rept(payload: bytes, depth: int, root: bytes, abs_base: int) -> list[DecodedImage]:
    if len(payload) < 2:
        raise FormatError("short REPT")
    count = struct.unpack(">H", payload[:2])[0]
    inner = payload[2:]
    out: list[DecodedImage] = []
    # Recursive expansion (the prototype wanted each repeat to be a layer).
    # count comes straight from the file.
    for _ in range(count):
        out.append(decode_bytes(inner, _depth=depth + 1, _root=root, _abs_base=abs_base))
    return out
