"""Build pipeline: fetch, normalize, check and write the blocklist."""
import json
import os
import sys
import tomllib
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from mbl.checks import safety_errors
from mbl.fetch import USER_AGENT, SourceResult, fetch_all
from mbl.normalize import normalize
from mbl.render import write_outputs
from mbl.sources import load_allowlist, load_sources

PREVIOUS_TIMEOUT = 15


def _previous_total(url: str | None) -> int | None:
    if not url:
        return None
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=PREVIOUS_TIMEOUT) as resp:
            total = json.load(resp)["total"]
        if not isinstance(total, int) or isinstance(total, bool):
            raise ValueError("total is not an integer")
        return total
    except Exception as exc:  # network error, 404, malformed JSON...
        print(f"warning: previous stats unavailable ({type(exc).__name__}: {exc}); "
              "skipping drop check", file=sys.stderr)
        return None


def _summary(results: list[SourceResult], total: int) -> tuple[str, str]:
    rows = [(r.source.name, r.source.category, str(len(r.networks)), str(r.invalid),
             "yes" if r.source.required else "no", r.error or "ok") for r in results]
    head = ("source", "category", "entries", "invalid", "required", "status")
    widths = [max(len(h), *(len(row[i]) for row in rows)) if rows else len(h)
              for i, h in enumerate(head)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    text = "\n".join([fmt.format(*head), *(fmt.format(*row) for row in rows),
                      f"total after normalization: {total}"]) + "\n"
    md = "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head),
                    *("| " + " | ".join(row) + " |" for row in rows),
                    "", f"Total after normalization: **{total}**"]) + "\n"
    return text, md


def build(sources_path: Path, allowlist_path: Path, out_dir: Path,
          previous_stats_url: str | None, now: datetime | None = None,
          fetcher=fetch_all, allow_growth: bool = False) -> int:
    """Return 0 on success, 1 if safety checks fail, 2 on configuration errors."""
    try:
        sources = load_sources(Path(sources_path))
        allowlist = load_allowlist(Path(allowlist_path))
    except (ValueError, TypeError, tomllib.TOMLDecodeError, OSError) as exc:
        print(f"configuration error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    now = now or datetime.now(timezone.utc)
    results = fetcher(sources)
    networks = normalize([n for r in results for n in r.networks], allowlist)
    total = len(networks)

    text, md = _summary(results, total)
    print(text, end="")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(md)

    failed = [r.source.name for r in results if r.source.required and r.error]
    errors = safety_errors(total, _previous_total(previous_stats_url), failed,
                           allow_growth=allow_growth)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    write_outputs(Path(out_dir), networks, results, now)
    return 0
