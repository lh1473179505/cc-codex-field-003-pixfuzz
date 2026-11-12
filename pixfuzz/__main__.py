"""CLI for pixfuzz: coverage-guided fuzzing of the harlequin decoder."""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pixfuzz")
    sub = p.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="coverage-guided fuzz of harlequin.decode_path")
    run.add_argument("--seed-dir", required=True, help="directory of seed inputs")
    run.add_argument("--out-dir", required=True, help="corpus, crashes, and report directory")
    run.add_argument("--max-time", type=float, default=20.0, help="stop after this many seconds")
    run.add_argument("--timeout", type=float, default=0.2, help="per-input wall timeout in seconds")
    run.add_argument("--rss-mb", type=int, default=256, help="per-input RSS limit in mebibytes")
    run.add_argument("--dict", dest="dict_path", default=None, help="optional token dictionary")
    run.add_argument("--jobs", type=int, default=1, help="worker processes (1 is acceptable)")
    run.add_argument("--report", default=None, help="path for the JSON report (default: <out-dir>/report.json)")
    return p


def main(argv: list[str] | None = None) -> int:
    p = build_parser()
    args = p.parse_args(argv)
    if args.cmd == "run":
        from .fuzzer import run_fuzz

        return run_fuzz(args)
    p.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
