"""Source catalog and local allowlist loading."""
import tomllib
from dataclasses import dataclass
from ipaddress import IPv4Network
from pathlib import Path

FORMATS = frozenset({"plain", "dshield", "threatfox_csv", "c2intel_csv"})
CATEGORIES = frozenset({"attack", "c2"})


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    format: str
    category: str
    enabled: bool = True
    required: bool = False
    license_note: str = ""


def load_sources(path: Path) -> list[Source]:
    """Return the enabled sources of the catalog; raise ValueError if invalid."""
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    seen: set[str] = set()
    result: list[Source] = []
    for entry in data.get("source", []):
        source = Source(**entry)
        if source.format not in FORMATS:
            raise ValueError(f"{source.name}: unknown format {source.format!r}")
        if source.category not in CATEGORIES:
            raise ValueError(f"{source.name}: unknown category {source.category!r}")
        if source.name in seen:
            raise ValueError(f"duplicate source name {source.name!r}")
        seen.add(source.name)
        if source.enabled:
            result.append(source)
    return result


def load_allowlist(path: Path) -> list[IPv4Network]:
    """Parse one IPv4 address or CIDR per line, ignoring comments and blanks."""
    networks: list[IPv4Network] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            networks.append(IPv4Network(line, strict=False))
    return networks
