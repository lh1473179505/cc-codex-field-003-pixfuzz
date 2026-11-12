"""CLI: inspect / decode. The fuzz subcommand lives in the pixfuzz package."""

from __future__ import annotations

import argparse
import json
import sys

from .errors import HarlequinError
from .image import decode_path
from .inspect import inspect_path
from .ppm import write_ppm


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="harlequin")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_ins = sub.add_parser("inspect", help="print chunk structure")
    p_ins.add_argument("input")

    p_dec = sub.add_parser("decode", help="decode to PPM")
    p_dec.add_argument("input")
    p_dec.add_argument("--out", required=True, help="output .ppm path")
    p_dec.add_argument("--json", dest="meta_json", help="optional metadata JSON")

    args = p.parse_args(argv)
    try:
        if args.cmd == "inspect":
            print(inspect_path(args.input))
            return 0
        img = decode_path(args.input)
        write_ppm(img, args.out)
        if args.meta_json:
            meta = {
                "width": img.width,
                "height": img.height,
                "channels": img.channels,
                "text": [{"key": t.key, "value": t.value} for t in img.text],
                "layers": len(img.layers),
            }
            with open(args.meta_json, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
                f.write("\n")
        return 0
    except FileNotFoundError as e:
        print(f"error: file not found: {e.filename or e}", file=sys.stderr)
        return 2
    except HarlequinError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
