"""Build pipeline: fetch, normalize, check and write the blocklist."""
import json
import os
import re
import sys
import tomllib
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from mbl.checks import LIMITS, LIMITS6, MAX_DROP, safety_errors
from mbl.fetch import USER_AGENT, SourceResult, fetch_all
from mbl.normalize import normalize, normalize6
from mbl.render import ipv6_files, write_outputs
from mbl.sources import VARIANTS, load_allowlist, load_sources

PREVIOUS_TIMEOUT = 15
IPV6_PREFIX = "ipv6:"


def _int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _previous_stats(url: str | None) -> tuple[dict[str, int], dict[str, int]]:
    """Previous total per variant and entries per source; empty when unavailable.

    IPv6 values share the dicts under an "ipv6:" prefix ("ipv6:full" total,
    "ipv6:<source>" entries); without an ipv6 section there are none.

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
    ipv6 = data.get("ipv6")
    variants6 = ipv6.get("variants") if isinstance(ipv6, dict) else None
    for name in VARIANTS:
        entry = variants6.get(name) if isinstance(variants6, dict) else None
        total = entry.get("total") if isinstance(entry, dict) else None
        if _int(total):
            totals[f"{IPV6_PREFIX}{name}"] = total
    sources = data.get("sources")
    entries: dict[str, int] = {}
    for name, info in (sources.items() if isinstance(sources, dict) else ()):
        if not isinstance(info, dict):
            continue
        if _int(info.get("entries")):
            entries[name] = info["entries"]
        if _int(info.get("entries6")):
            entries[f"{IPV6_PREFIX}{name}"] = info["entries6"]
    return totals, entries


def _previous_totals(url: str | None) -> dict[str, int]:
    """Previous total per variant; empty when unavailable (checks are skipped)."""
    return _previous_stats(url)[0]


def _summary(results: list[SourceResult], total: int) -> tuple[str, str]:
    rows = [(r.source.name, r.source.category, str(sum(n.version == 4 for n in r.networks)),
             str(sum(n.version == 6 for n in r.networks)), str(r.invalid),
             "yes" if r.source.required else "no", r.error or "ok") for r in results]
    head = ("source", "category", "entries", "entries6", "invalid", "required", "status")
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

    def check(v, nets, limits, prefix="", label=""):
        low, high = limits[v]
        mine = [r for r in results if v in r.source.variants and r.error]
        failed = [r.source.name for r in mine if r.source.required]
        optional = [r.source.name for r in mine if not r.source.required]
        explained = sum(previous_entries.get(prefix + name, 0) for name in optional)
        prev = previous.get(prefix + v)
        drop = prev - len(nets) if prev else 0
        if prev and optional and drop > prev * MAX_DROP and drop <= explained:
            print(f"warning: {label}{v}: drop of {drop} explained by failed sources "
                  f"({', '.join(optional)}), drop check skipped", file=sys.stderr)
        return [f"{label}{v}: {e}" for e in safety_errors(
            len(nets), prev, failed, min_total=low, max_total=high,
            allow_growth=allow_growth, explained_drop=explained)]

    errors = []
    for v, nets in variants.items():
        errors += check(v, nets, LIMITS)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    # IPv6 is best effort: any problem (a failed check or an unexpected exception)
    # withholds all IPv6 files, never fails the build nor blocks the IPv4 files.
    variants6, files6, errors6 = None, None, []
    try:
        variants6 = {v: normalize6([n for r in results if v in r.source.variants
                                    for n in r.networks], allowlist) for v in VARIANTS}
        print("".join(f"total ipv6 {v}: {len(nets)}\n" for v, nets in variants6.items()),
              end="")
        for v, nets in variants6.items():
            errors6 += check(v, nets, LIMITS6, IPV6_PREFIX, "ipv6 ")
        if not errors6:
            files6 = ipv6_files(variants6, now, script_version)
    except Exception as exc:
        errors6 = [f"ipv6: unexpected {type(exc).__name__}: {exc}"]
    if errors6:
        for error in errors6:
            print(f"warning: IPv6 not published, {error}", file=sys.stderr)
        if summary_path:
            with open(summary_path, "a", encoding="utf-8") as fh:
                fh.write("\n**Warning: IPv6 lists not published**\n\n"
                         + "".join(f"- {e}\n" for e in errors6))
        variants6, files6 = None, None

    # A withheld day keeps the last published IPv6 totals in stats.json, so the
    # next build still compares against that baseline, not against today's.
    baseline6 = {v: previous[IPV6_PREFIX + v] for v in VARIANTS if IPV6_PREFIX + v in previous}
    write_outputs(Path(out_dir), variants, results, now, script_version, variants6,
                  ipv6_baseline=baseline6, files6=files6)
    return 0
