"""Build pipeline: fetch, normalize, check and write the blocklist."""
import json
import os
import re
import sys
import tomllib
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from mbl.checks import LIMITS, safety_errors
from mbl.fetch import USER_AGENT, SourceResult, fetch_all
from mbl.normalize import normalize
from mbl.render import write_outputs
from mbl.sources import VARIANTS, load_allowlist, load_sources

PREVIOUS_TIMEOUT = 15


def _previous_totals(url: str | None) -> dict[str, int]:
    """Previous total per variant; empty when unavailable (checks are skipped)."""
    if not url:
        return {}
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=PREVIOUS_TIMEOUT) as resp:
            data = json.load(resp)
        totals: dict[str, int] = {}
        variants = data.get("variants")
        for name in VARIANTS:
            entry = variants.get(name) if isinstance(variants, dict) else None
            total = entry.get("total") if isinstance(entry, dict) else None
            if total is None and name == "full":
                total = data["total"]  # stats.json from before the variants
            if total is None:
                continue
            if not isinstance(total, int) or isinstance(total, bool):
                raise ValueError(f"{name} total is not an integer")
            totals[name] = total
        return totals
    except Exception as exc:  # network error, 404, malformed JSON...
        print(f"warning: previous stats unavailable ({type(exc).__name__}: {exc}); "
              "skipping drop check", file=sys.stderr)
        return {}


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
          fetcher=fetch_all, allow_growth: bool = False,
          version_path: Path = Path("VERSION")) -> int:
    """Return 0 on success, 1 if safety checks fail, 2 on configuration errors."""
    try:
        sources = load_sources(Path(sources_path))
        allowlist = load_allowlist(Path(allowlist_path))
        script_version = Path(version_path).read_text(encoding="utf-8").strip()
        if not script_version:
            raise ValueError(f"{version_path} is empty")
        if not re.fullmatch(r"\d+\.\d+\.\d+", script_version, re.ASCII):
            raise ValueError(f"{version_path} is not MAJOR.MINOR.PATCH: {script_version!r}")
    except (ValueError, TypeError, tomllib.TOMLDecodeError, OSError) as exc:
        print(f"configuration error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    now = now or datetime.now(timezone.utc)
    results = fetcher(sources)
    variants = {v: normalize([n for r in results if v in r.source.variants
                              for n in r.networks], allowlist) for v in VARIANTS}
    total = len(variants["full"])

    text, md = _summary(results, total)
    print(text, end="")
    print("".join(f"total {v}: {len(nets)}\n" for v, nets in variants.items()), end="")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(md)

    failed = [r.source.name for r in results if r.source.required and r.error]
    previous = _previous_totals(previous_stats_url)
    errors = []
    for v, nets in variants.items():
        low, high = LIMITS[v]
        errors += [f"{v}: {e}" for e in safety_errors(
            len(nets), previous.get(v), failed, min_total=low, max_total=high,
            allow_growth=allow_growth)]
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    write_outputs(Path(out_dir), variants, results, now, script_version)
    return 0
