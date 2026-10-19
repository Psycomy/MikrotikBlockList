"""Command line entry point: python -m mbl build ..."""
import argparse
import sys
from pathlib import Path

from mbl.build import build


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mbl")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("build", help="fetch sources and write the blocklist files")
    p.add_argument("--sources", type=Path, default=Path("sources.toml"))
    p.add_argument("--allowlist", type=Path, default=Path("allowlist.txt"))
    p.add_argument("--out", type=Path, default=Path("dist"))
    p.add_argument("--previous-stats", default=None, metavar="URL")
    args = parser.parse_args(argv)
    return build(args.sources, args.allowlist, args.out, args.previous_stats)


if __name__ == "__main__":
    sys.exit(main())
