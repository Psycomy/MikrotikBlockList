"""Build pipeline: fetch, normalize, check and write the blocklist."""
import json
import os
import re
import sys
import tomllib
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from mbl.checks import LIMITS, MAX_DROP, safety_errors
from mbl.fetch import USER_AGENT, SourceResult, fetch_all
from mbl.normalize import normalize
from mbl.render import write_outputs
from mbl.sources import VARIANTS, load_allowlist, load_sources

PREVIOUS_TIMEOUT = 15


def _int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _previous_stats(url: str | None) -> tuple[dict[str, int], dict[str, int]]:
    """Previous total per variant and entries per source; empty when unavailable.

    A variant with a missing or malformed total is left out (its drop and growth
    checks are skipped); a source without integer entries is left out (counts as 0).
    """
    if not url:
        return {}, {}
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=PREVIOUS_TIMEOUT) as resp:
            data = json.load(resp)
        if not isinstance(data, dict):
            raise ValueError("stats.json is not an object")
    except Exception as exc:  # network error, 404, malformed JSON...
        print(f"warning: previous stats unavailable ({type(exc).__name__}: {exc}); "
              "skipping drop check", file=sys.stderr)
        return {}, {}
    totals: dict[str, int] = {}
    variants = data.get("variants")
    for name in VARIANTS:
        entry = variants.get(name) if isinstance(variants, dict) else None
        total = entry.get("total") if isinstance(entry, dict) else None
        if total is None and name == "full":
            total = data.get("total")  # stats.json from before the variants
        if total is None:
            continue
        if not _int(total):
            print(f"warning: previous {name} total is not an integer ({total!r}); "
                  f"skipping {name} drop and growth checks", file=sys.stderr)
            continue
        totals[name] = total
    sources = data.get("sources")
    entries = {name: info["entries"] for name, info in sources.items()
               if isinstance(info, dict) and _int(info.get("entries"))
               } if isinstance(sources, dict) else {}
    return totals, entries


def _previous_totals(url: str | None) -> dict[str, int]:
    """Previous total per variant; empty when unavailable (checks are skipped)."""
    return _previous_stats(url)[0]


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

    previous, previous_entries = _previous_stats(previous_stats_url)
    errors = []
    for v, nets in variants.items():
        low, high = LIMITS[v]
        mine = [r for r in results if v in r.source.variants and r.error]
        failed = [r.source.name for r in mine if r.source.required]
        optional = [r.source.name for r in mine if not r.source.required]
        explained = sum(previous_entries.get(name, 0) for name in optional)
        prev = previous.get(v)
        drop = prev - len(nets) if prev else 0
        if optional and drop > prev * MAX_DROP and drop <= explained:
            print(f"warning: {v}: drop of {drop} explained by failed sources "
                  f"({', '.join(optional)}), drop check skipped", file=sys.stderr)
        errors += [f"{v}: {e}" for e in safety_errors(
            len(nets), prev, failed, min_total=low, max_total=high,
            allow_growth=allow_growth, explained_drop=explained)]
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    write_outputs(Path(out_dir), variants, results, now, script_version)
    return 0
