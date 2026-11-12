"""Execution coverage for the harlequin package, collected with sys.settrace.

The tracer records (file, line) hits and line-to-line edges for code that
lives in the harlequin package only, so the numbers reflect real decoder
coverage rather than "how many files were touched".
"""

from __future__ import annotations

import os
import sys
import types
from typing import Callable, TypeVar

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HARLEQUIN_DIR = os.path.join(REPO_ROOT, "harlequin")

T = TypeVar("T")


def harlequin_source_files() -> list[str]:
    return sorted(
        os.path.join(HARLEQUIN_DIR, name)
        for name in os.listdir(HARLEQUIN_DIR)
        if name.endswith(".py")
    )


def _collect_code_lines(code: types.CodeType, out: set[tuple[str, int]]) -> None:
    for _, _, lineno in code.co_lines():
        if lineno is not None:
            out.add((code.co_filename, lineno))
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            _collect_code_lines(const, out)


def total_executable_lines() -> set[tuple[str, int]]:
    """All lines in the harlequin package that compile to real bytecode."""
    lines: set[tuple[str, int]] = set()
    for path in harlequin_source_files():
        with open(path, "rb") as f:
            src = f.read()
        _collect_code_lines(compile(src, path, "exec"), lines)
    return lines


class CoverageTracer:
    """Collect line hits and edges while running a callable."""

    def __init__(self) -> None:
        self.lines: set[tuple[str, int]] = set()
        self.edges: set[tuple[tuple[str, int], tuple[str, int]]] = set()
        self._last: tuple[str, int] | None = None

    def _trace(self, frame, event, arg):  # settrace callback signature
        code = frame.f_code
        filename = code.co_filename
        if not filename.startswith(HARLEQUIN_DIR + os.sep):
            return None
        if event == "call":
            cur = (filename, code.co_firstlineno)
        elif event == "line":
            cur = (filename, frame.f_lineno)
        else:
            return self._trace
        self.lines.add(cur)
        if self._last is not None and self._last != cur:
            self.edges.add((self._last, cur))
        self._last = cur
        return self._trace

    def run(self, fn: Callable[[], T]) -> T:
        self._last = None
        sys.settrace(self._trace)
        try:
            return fn()
        finally:
            sys.settrace(None)
