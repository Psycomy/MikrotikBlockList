"""Rendering of the published output files."""
import json
from datetime import datetime, timezone
from ipaddress import IPv4Network
from pathlib import Path

from mbl.fetch import SourceResult

TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _cidr(net: IPv4Network) -> str:
    return str(net.network_address) if net.prefixlen == 32 else str(net)


def _rsc(addresses: list[str], stamp: str) -> str:
    lines = [
        "# MikrotikBlockList v2 - https://github.com/Psycomy/MikrotikBlockList",
        "# For home / non-commercial use only (see source licenses in README)",
        f"# generated: {stamp} entries: {len(addresses)}",
        ":global mblTarget",
        "/ip firewall address-list",
    ]
    lines += [f"add list=$mblTarget timeout=7d address={a}" for a in addresses]
    lines += [":global mblImportOk true", "# MBL-END"]
    return "\n".join(lines) + "\n"


def _json(data: dict) -> str:
    return json.dumps(data, indent=2) + "\n"


def write_outputs(
    out_dir: Path,
    networks: list[IPv4Network],
    results: list[SourceResult],
    generated_at: datetime,
) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    generated_at = generated_at.astimezone(timezone.utc)
    stamp = generated_at.strftime(TIME_FORMAT)
    addresses = [_cidr(n) for n in networks]
    total = len(addresses)

    stats = {
        "generated_at": stamp,
        "total": total,
        "sources": {
            r.source.name: {
                "category": r.source.category,
                "entries": len(r.networks),
                "invalid": r.invalid,
                "error": r.error,
            }
            for r in results
        },
    }
    badge_entries = {
        "schemaVersion": 1,
        "label": "entries",
        "message": f"{total:,}",
        "color": "blue",
    }
    badge_updated = {
        "schemaVersion": 1,
        "label": "updated",
        "message": generated_at.strftime("%Y-%m-%d"),
        "color": "brightgreen",
    }

    files = {
        "blocklist.rsc": _rsc(addresses, stamp),
        "blocklist.txt": "".join(a + "\n" for a in addresses),
        "stats.json": _json(stats),
        "badge-entries.json": _json(badge_entries),
        "badge-updated.json": _json(badge_updated),
    }
    for name, content in files.items():
        (out_dir / name).write_text(content, encoding="utf-8", newline="\n")
