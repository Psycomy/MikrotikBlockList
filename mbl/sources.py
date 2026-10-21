"""Source catalog and local allowlist loading."""
import tomllib
from dataclasses import dataclass
from ipaddress import IPv4Network, IPv6Network, ip_network
from pathlib import Path

FORMATS = frozenset({"plain", "dshield", "threatfox_csv", "c2intel_csv", "csv", "jsonl_cidr"})
CATEGORIES = frozenset({"attack", "c2"})
VARIANTS = ("full", "lite")


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    format: str
    category: str
    enabled: bool = True
    required: bool = False
    license_note: str = ""
    variants: tuple[str, ...] = ("full",)


def load_sources(path: Path) -> list[Source]:
    """Return the enabled sources of the catalog; raise ValueError if invalid."""
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    seen: set[str] = set()
    result: list[Source] = []
    for entry in data.get("source", []):
        entry = {**entry, "variants": tuple(entry["variants"])} if "variants" in entry else entry
        source = Source(**entry)
        if source.format not in FORMATS:
            raise ValueError(f"{source.name}: unknown format {source.format!r}")
        if source.category not in CATEGORIES:
            raise ValueError(f"{source.name}: unknown category {source.category!r}")
        if not source.variants:
            raise ValueError(f"{source.name}: variants must not be empty")
        for variant in source.variants:
            if variant not in VARIANTS:
                raise ValueError(f"{source.name}: unknown variant {variant!r}")
        if "lite" in source.variants and "full" not in source.variants:
            raise ValueError(f"{source.name}: a lite source must also be full")
        if source.name in seen:
            raise ValueError(f"duplicate source name {source.name!r}")
        seen.add(source.name)
        if source.enabled:
            result.append(source)
    return result


def load_allowlist(path: Path) -> list[IPv4Network | IPv6Network]:
    """Parse one IPv4 or IPv6 address or CIDR per line.

    Blank lines and comments (whole-line or after the entry, starting with #)
    are ignored. Raise ValueError naming the line number for an invalid entry.
    """
    networks: list[IPv4Network | IPv6Network] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(lines, start=1):
        entry = line.split("#", 1)[0].strip()
        if not entry:
            continue
        try:
            networks.append(ip_network(entry, strict=False))
        except ValueError as exc:
            raise ValueError(f"{path}: line {number}: invalid entry {entry!r} ({exc})") from exc
    return networks
