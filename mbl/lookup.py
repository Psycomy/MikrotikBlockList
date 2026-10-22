"""lookup.json: the published entries with their sources and countries, for the lookup page."""
import json
from bisect import bisect_right
from datetime import datetime, timezone
from ipaddress import IPv4Network, IPv6Network
from pathlib import Path

from mbl.fetch import SourceResult
from mbl.geo import CountryDb
from mbl.render import TIME_FORMAT, source_notice

FORMAT = 1


def _intervals(networks, version: int) -> tuple[list[int], list[int]]:
    """Sorted starts, and the running maximum of the ends, of one version's networks."""
    ranges = sorted((int(n.network_address), int(n.broadcast_address))
                    for n in networks if n.version == version)
    starts = [first for first, _ in ranges]
    max_ends, top = [], -1
    for _, last in ranges:
        top = max(top, last)
        max_ends.append(top)
    return starts, max_ends


def _overlaps(intervals: tuple[list[int], list[int]], first: int, last: int) -> bool:
    # among the networks starting at or before the entry's last address, one overlaps
    # the entry exactly when the largest end reaches the entry's first address
    starts, max_ends = intervals
    i = bisect_right(starts, last) - 1
    return i >= 0 and max_ends[i] >= first


def _entries(nets, results, geo: CountryDb | None, version: int) -> list[list]:
    # errored sources are never members, even when they carry stale networks
    members = [(i, _intervals(r.networks, version))
               for i, r in enumerate(results) if not r.error]
    out = []
    for net in nets:
        first, last = int(net.network_address), int(net.broadcast_address)
        indexes = [i for i, iv in members if _overlaps(iv, first, last)]
        cc = geo.country(first, last, version) if geo else ""
        out.append([str(net), indexes, cc])
    return out


def _family(variants, results, geo, version: int) -> dict:
    return {"full": _entries(variants["full"], results, geo, version),
            "lite": [str(n) for n in variants.get("lite", [])]}


def lookup_data(variants: dict[str, list[IPv4Network]],
                variants6: dict[str, list[IPv6Network]] | None,
                results: list[SourceResult], generated_at: datetime,
                geo: CountryDb | None) -> dict:
    """The lookup.json content (format 1); v6 is None when IPv6 is withheld."""
    stamp = generated_at.astimezone(timezone.utc).strftime(TIME_FORMAT)
    sources = [{
        "name": r.source.name,
        "category": r.source.category,
        "url": r.source.url,
        "license_note": r.source.license_note,
        "notice": source_notice(r, stamp),
        "entries": sum(1 for n in r.networks if n.version == 4),
        "entries6": sum(1 for n in r.networks if n.version == 6),
        "ok": not r.error,
    } for r in results]
    return {
        "format": FORMAT,
        "generated_at": stamp,
        "ipv6_published": variants6 is not None,
        "dbip_month": (geo.month or None) if geo else None,
        "sources": sources,
        "v4": _family(variants, results, geo, 4),
        "v6": _family(variants6, results, geo, 6) if variants6 is not None else None,
    }


def write_lookup(out_dir: Path, data: dict) -> None:
    """Write lookup.json, compact (no spaces)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    (out_dir / "lookup.json").write_text(text + "\n", encoding="utf-8", newline="\n")
