"""CLI interface for exif-stripper."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile

from .core import ExifStripError, inspect, strip


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Exit codes:
        0: Strip succeeded, or --check passed (no metadata found)
        1: --check found metadata blocks
        2: Usage error, I/O error, or ExifStripError
    """
    parser = argparse.ArgumentParser(
        prog="exif-stripper",
        description="Strip EXIF, GPS, XMP, IPTC and comments without pixel re-encoding.",
    )
    parser.add_argument("file", help="Input image path")
    parser.add_argument("-o", "--output", help="Output image path")
    parser.add_argument(
        "--in-place", action="store_true", help="Modify input file directly using an atomic replace"
    )
    parser.add_argument(
        "--check", action="store_true", help="Exit 1 if metadata is present, 0 if clean"
    )
    parser.add_argument(
        "--keep-icc",
        action="store_true",
        default=True,
        help="Preserve ICC color profiles (default)",
    )
    parser.add_argument(
        "--drop-icc", dest="keep_icc", action="store_false", help="Remove ICC color profiles"
    )

    args = parser.parse_args(argv)

    if args.in_place and args.output:
        sys.stderr.write("Error: cannot specify both --in-place and -o/--output\n")
        return 2

    if not os.path.exists(args.file):
        sys.stderr.write(f"Error: file '{args.file}' not found\n")
        return 2

    try:
        with open(args.file, "rb") as f:
            data = f.read()
    except OSError as err:
        sys.stderr.write(f"I/O Error reading file: {err}\n")
        return 2

    try:
        if args.check:
            blocks = inspect(data)
            filtered = blocks if not args.keep_icc else [b for b in blocks if b.kind != "icc"]
            if filtered:
                kinds = ", ".join(b.kind for b in filtered)
                sys.stdout.write(f"Found metadata in {args.file}: {kinds}\n")
                return 1
            return 0

        result = strip(data, keep_icc=args.keep_icc)

        if args.in_place:
            dirname = os.path.dirname(os.path.abspath(args.file))
            with tempfile.NamedTemporaryFile(dir=dirname, delete=False) as tf:
                tf.write(result.data)
                temp_name = tf.name
            os.replace(temp_name, args.file)
            return 0
        elif args.output:
            with open(args.output, "wb") as f:
                f.write(result.data)
            return 0
        else:
            # Without -o or --in-place, print summary to stdout without modifying file
            sys.stdout.write(
                f"{args.file}: format={result.format}, removed={len(result.removed)} blocks, "
                f"orientation={result.orientation}\n"
            )
            return 0
    except ExifStripError as err:
        sys.stderr.write(f"Stripping Error [{err.code}]: {err}\n")
        return 2
    except OSError as err:
        sys.stderr.write(f"I/O Error: {err}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
