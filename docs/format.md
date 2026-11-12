# HQLN container (v1)

A Harlequin file is a short header followed by a sequence of chunks.

```
magic        : 4 bytes  "HQLN"
version      : u8       must be 1
chunks       : repeated until IEND
```

Each chunk:

```
type         : 4 bytes  ASCII tag
flags        : u8       writers should leave this 0; reserved for decoder experiments
length       : u32be    payload size in bytes
payload      : `length` bytes
crc32        : u32be    CRC-32 of `type || flags || payload` (zlib CRC)
```

## Chunk types

### IHDR (required, first)

```
width        : u32be
height       : u32be
channels     : u8       1 = gray or indexed, 3 = RGB, 4 = RGBA
bit_depth    : u8       only 8 is defined
color_type   : u8       0 = direct, 1 = indexed (requires PLTE, channels must be 1)
compression  : u8       0 = raw scanlines, 1 = zlib-wrapped scanlines
```

Image size in the checked-in fixtures is small (well under a megapixel).

### PLTE

Packed RGB triples, 3 bytes each. Required when `color_type == 1`.

### DATA

Scanline payload. For each of `height` rows:

```
filter       : u8       0 none, 1 sub, 2 up, 3 average, 4 paeth
samples      : width * channels bytes (8-bit)
```

Filter 1–4 follow the usual PNG-style predictors over the current and previous reconstructed scanlines. Filter 2–4 on the first row should treat the previous row as all zeros.

If `compression == 1`, the DATA payload is a zlib stream that inflates to the scanline bytes above.

### NEST

An embedded HQLN document, used for a thumbnail or layer.

```
reserved     : u32be    writers must set this to 0
document     : the remaining bytes, themselves a complete HQLN file
```

The decoder may attach the nested document as a layer. Nesting in the fixtures is shallow.

### TEXT

`key` and `value` separated by a single NUL byte. Keys used in fixtures: `title`, `dpi`, `comment`.

### REPT

Reserved experimental tag. Fixtures do not use it. A decoder may ignore unknown tags; current code still recognizes this name because it grew out of an earlier looping-layer prototype.

### IEND

Empty payload. Must be last. Anything after IEND is ignored.

Unknown chunk types should be skipped if their length and CRC are consistent.
