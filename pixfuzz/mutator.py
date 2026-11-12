"""Binary-oriented mutations for HQLN containers, plus dictionary tokens."""

from __future__ import annotations

import ast
import random
import re

INTERESTING_8 = (0x00, 0x01, 0x02, 0x7F, 0x80, 0xFE, 0xFF)
INTERESTING_16 = (0x0000, 0x0001, 0x0100, 0x7FFF, 0x8000, 0xFFFF)
INTERESTING_32 = (0x00000000, 0x00000001, 0x00000100, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF)

_TOKEN_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')


def load_dictionary(path: str) -> list[bytes]:
    """Parse an AFL-style token dictionary ("tok" or name="tok" lines)."""
    tokens: list[bytes] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            matches = _TOKEN_RE.findall(line)
            if not matches:
                continue
            try:
                token = ast.literal_eval('b"' + matches[-1] + '"')
            except (SyntaxError, ValueError):
                continue
            if token:
                tokens.append(token)
    return tokens


class Mutator:
    def __init__(self, rng: random.Random, tokens: list[bytes] | None = None) -> None:
        self.rng = rng
        self.tokens = tokens or []

    def mutate(self, data: bytes, corpus: list[bytes] | None = None) -> bytes:
        buf = bytearray(data)
        for _ in range(self.rng.randint(1, 6)):
            if not buf:
                buf = bytearray(self.rng.randbytes(self.rng.randint(1, 16)))
            buf = self._one(buf)
        if corpus and len(corpus) > 1 and self.rng.random() < 0.10:
            buf = self._splice(buf, self.rng.choice(corpus))
        return bytes(buf)

    def _one(self, buf: bytearray) -> bytearray:
        ops = [
            self._flip_bit,
            self._set_byte_random,
            self._set_byte_interesting,
            self._overwrite_int,
            self._insert_block,
            self._delete_block,
            self._copy_block,
        ]
        if self.tokens:
            ops += [self._insert_token, self._overwrite_token]
        return self.rng.choice(ops)(buf)

    def _flip_bit(self, buf: bytearray) -> bytearray:
        pos = self.rng.randrange(len(buf))
        buf[pos] ^= 1 << self.rng.randrange(8)
        return buf

    def _set_byte_random(self, buf: bytearray) -> bytearray:
        pos = self.rng.randrange(len(buf))
        buf[pos] = self.rng.randrange(256)
        return buf

    def _set_byte_interesting(self, buf: bytearray) -> bytearray:
        pos = self.rng.randrange(len(buf))
        buf[pos] = self.rng.choice(INTERESTING_8)
        return buf

    def _overwrite_int(self, buf: bytearray) -> bytearray:
        width = self.rng.choice((2, 4))
        if len(buf) < width:
            return buf
        pos = self.rng.randrange(len(buf) - width + 1)
        pool = INTERESTING_16 if width == 2 else INTERESTING_32
        value = self.rng.choice(pool)
        byteorder = self.rng.choice(("big", "little"))
        buf[pos:pos + width] = value.to_bytes(width, byteorder)
        return buf

    def _insert_block(self, buf: bytearray) -> bytearray:
        pos = self.rng.randrange(len(buf) + 1)
        block = self.rng.randbytes(self.rng.randint(1, 16))
        return buf[:pos] + block + buf[pos:]

    def _delete_block(self, buf: bytearray) -> bytearray:
        if len(buf) < 2:
            return buf
        pos = self.rng.randrange(len(buf))
        length = self.rng.randint(1, min(32, len(buf) - pos))
        del buf[pos:pos + length]
        return buf

    def _copy_block(self, buf: bytearray) -> bytearray:
        if len(buf) < 2:
            return buf
        src = self.rng.randrange(len(buf))
        length = self.rng.randint(1, min(32, len(buf) - src))
        dst = self.rng.randrange(len(buf) + 1)
        block = bytes(buf[src:src + length])
        return buf[:dst] + block + buf[dst:]

    def _insert_token(self, buf: bytearray) -> bytearray:
        pos = self.rng.randrange(len(buf) + 1)
        token = self.rng.choice(self.tokens)
        return buf[:pos] + token + buf[pos:]

    def _overwrite_token(self, buf: bytearray) -> bytearray:
        token = self.rng.choice(self.tokens)
        if len(buf) < len(token):
            return bytearray(token)
        pos = self.rng.randrange(len(buf) - len(token) + 1)
        buf[pos:pos + len(token)] = token
        return buf

    def _splice(self, buf: bytearray, other: bytes) -> bytearray:
        if not other:
            return buf
        cut_a = self.rng.randrange(len(buf) + 1)
        cut_b = self.rng.randrange(len(other) + 1)
        return buf[:cut_a] + other[cut_b:]
