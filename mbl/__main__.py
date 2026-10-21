"""Command line entry point: python -m mbl build ..."""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from mbl.build import build
from mbl.cdn import DEFAULT_SNAPSHOT, fetch_live, write_snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mbl")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("build", help="fetch sources and write the blocklist files")
    p.add_argument("--sources", type=Path, default=Path("sources.toml"))
    p.add_argument("--allowlist", type=Path, default=Path("allowlist.txt"))
    p.add_argument("--out", type=Path, default=Path("dist"))
    p.add_argument("--version-file", type=Path, default=Path("VERSION"))
    p.add_argument("--previous-stats", default=None, metavar="URL")
    p.add_argument("--allow-growth", action="store_true",
                   help="skip only the check that refuses a total more than 2x the previous one")
    p.add_argument("--cdn-snapshot", type=Path, default=DEFAULT_SNAPSHOT,
                   help="CDN provider lists used when a live download is rejected")
    s = sub.add_parser("cdn-snapshot", help="download the CDN lists into a snapshot file")
    s.add_argument("--out", type=Path, default=DEFAULT_SNAPSHOT)
    args = parser.parse_args(argv)
    if args.command == "cdn-snapshot":
        try:
            blocks = fetch_live()
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        write_snapshot(args.out, blocks, datetime.now(timezone.utc).date())
        print(f"wrote {args.out}: " + ", ".join(f"{k} {len(v)}" for k, v in blocks.items()))
        return 0
    return build(args.sources, args.allowlist, args.out, args.previous_stats,
                 allow_growth=args.allow_growth, version_path=args.version_file,
                 cdn_snapshot=args.cdn_snapshot)


if __name__ == "__main__":
    sys.exit(main())
