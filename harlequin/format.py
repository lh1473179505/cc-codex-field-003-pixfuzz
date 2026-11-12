"""HQLN constants and CRC helper."""

MAGIC = b"HQLN"
VERSION = 1
HEADER_SIZE = 5  # magic + version

TYPE_IHDR = b"IHDR"
TYPE_PLTE = b"PLTE"
TYPE_DATA = b"DATA"
TYPE_NEST = b"NEST"
TYPE_TEXT = b"TEXT"
TYPE_REPT = b"REPT"
TYPE_END = b"IEND"

COLOR_DIRECT = 0
COLOR_INDEXED = 1
COMPRESS_RAW = 0
COMPRESS_ZLIB = 1

FILTER_NONE = 0
FILTER_SUB = 1
FILTER_UP = 2
FILTER_AVG = 3
FILTER_PAETH = 4

# Soft cap used by the encoder / fixture script. The decoder itself does not
# currently reject larger dimensions up front (it tries to follow the header).
MAX_FIXTURE_PIXELS = 1_000_000


def crc32(data: bytes) -> int:
    import zlib
    return zlib.crc32(data) & 0xFFFFFFFF
