"""Automatic CDN allowlist: live provider lists with a committed snapshot fallback."""
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from functools import partial
from ipaddress import IPv4Network, IPv6Network, ip_network
from pathlib import Path

from mbl.fetch import _download

Network = IPv4Network | IPv6Network

MIN_PREFIXES4 = 5
MIN_PREFIXES6 = 1
MIN_PREFIXLEN4 = 8   # a wider IPv4 prefix is rejected
MIN_PREFIXLEN6 = 16  # a wider IPv6 prefix is rejected
DEFAULT_SNAPSHOT = Path("allowlist-cdn.snapshot.txt")


def _lines(text: str) -> tuple[list[str], list[str]]:
    entries = [line.strip() for line in text.splitlines() if line.strip()]
    return [e for e in entries if ":" not in e], [e for e in entries if ":" in e]


def _cloudflare(texts: list[str]) -> tuple[list[str], list[str]]:
    return _lines(texts[0])[0], _lines(texts[1])[1]


def _fastly(texts: list[str]) -> tuple[list[str], list[str]]:
    data = json.loads(texts[0])
    return list(data["addresses"]), list(data["ipv6_addresses"])


def _cloudfront(texts: list[str]) -> tuple[list[str], list[str]]:
    data = json.loads(texts[0])
    return ([p["ip_prefix"] for p in data["prefixes"] if p["service"] == "CLOUDFRONT"],
            [p["ipv6_prefix"] for p in data["ipv6_prefixes"] if p["service"] == "CLOUDFRONT"])


@dataclass(frozen=True)
class Provider:
    urls: tuple[str, ...]
    extract: Callable[[list[str]], tuple[list[str], list[str]]]


PROVIDERS: dict[str, Provider] = {
    "cloudflare": Provider(("https://www.cloudflare.com/ips-v4",
                            "https://www.cloudflare.com/ips-v6"), _cloudflare),
    "fastly": Provider(("https://api.fastly.com/public-ip-list",), _fastly),
    "cloudfront": Provider(("https://ip-ranges.amazonaws.com/ip-ranges.json",), _cloudfront),
}


@dataclass
class CdnResult:
    networks: list[Network] = field(default_factory=list)
    info: dict[str, dict] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _validate(nets4: list[IPv4Network], nets6: list[IPv6Network]) -> None:
    """Raise ValueError if a provider's prefixes are unusable."""
    if len(nets4) < MIN_PREFIXES4:
        raise ValueError(f"only {len(nets4)} IPv4 prefixes (need {MIN_PREFIXES4})")
    if len(nets6) < MIN_PREFIXES6:
        raise ValueError("no IPv6 prefixes")
    for net in nets4:
        if net.prefixlen < MIN_PREFIXLEN4:
            raise ValueError(f"IPv4 prefix {net} is wider than /{MIN_PREFIXLEN4}")
    for net in nets6:
        if net.prefixlen < MIN_PREFIXLEN6:
            raise ValueError(f"IPv6 prefix {net} is wider than /{MIN_PREFIXLEN6}")


def _checked(strings4: list[str], strings6: list[str]) -> list[Network]:
    nets4 = [IPv4Network(s, strict=False) for s in strings4]
    nets6 = [IPv6Network(s, strict=False) for s in strings6]
    _validate(nets4, nets6)
    return [*nets4, *nets6]


def _live(provider: Provider, fetcher: Callable[[str], str]) -> list[Network]:
    texts = [fetcher(url) for url in provider.urls]
    return _checked(*provider.extract(texts))


def fetch_live(fetcher: Callable[[str], str] | None = None,
               backoff: float = 2) -> dict[str, list[Network]]:
    """Download every provider; raise ValueError naming the first one that is rejected."""
    fetcher = fetcher or partial(_download, timeout=30, retries=2, backoff=backoff)
    blocks = {}
    for name, provider in PROVIDERS.items():
        try:
            blocks[name] = _live(provider, fetcher)
        except Exception as exc:
            raise ValueError(f"{name}: {type(exc).__name__}: {exc}") from exc
    return blocks


def read_snapshot(path: Path) -> dict[str, list[Network]]:
    """Provider blocks of the snapshot; an unreadable file or invalid block is left out."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return {}
    raw: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        line = line.strip()
        header = re.fullmatch(r"#\s*provider\s+(\S+)(?:\s+\S+)?", line)
        if header:
            current = header.group(1)
            raw[current] = []
        elif line and not line.startswith("#") and current:
            raw[current].append(line)
    blocks = {}
    for name, entries in raw.items():
        if name not in PROVIDERS:
            continue
        try:
            blocks[name] = _checked(*_lines("\n".join(entries)))
        except ValueError:
            continue
    return blocks


def write_snapshot(path: Path, blocks: dict[str, list[Network]], day: date) -> None:
    """One '# provider <name> <date>' header and one CIDR per line, per provider."""
    lines = []
    for name in PROVIDERS:
        if name in blocks:
            lines.append(f"# provider {name} {day.isoformat()}")
            lines.extend(str(n) for n in blocks[name])
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _info(source: str, nets: list[Network]) -> dict:
    return {"source": source,
            "prefixes4": sum(n.version == 4 for n in nets),
            "prefixes6": sum(n.version == 6 for n in nets)}


def fetch_cdn(snapshot_path: Path = DEFAULT_SNAPSHOT,
              fetcher: Callable[[str], str] | None = None, backoff: float = 2) -> CdnResult:
    """Live lists per provider; a rejected provider falls back to its snapshot block.

    Never raises: a provider with neither is left out and reported as missing.
    """
    fetcher = fetcher or partial(_download, timeout=30, retries=2, backoff=backoff)
    snapshot = None
    result = CdnResult()
    for name, provider in PROVIDERS.items():
        try:
            nets, source, problem = _live(provider, fetcher), "live", None
        except Exception as exc:
            problem = f"{type(exc).__name__}: {exc}"
            if snapshot is None:
                snapshot = read_snapshot(snapshot_path)
            if name in snapshot:
                nets, source = snapshot[name], "snapshot"
                warning = f"CDN allowlist {name}: live list rejected ({problem}); using snapshot"
            else:
                nets, source = [], "missing"
                warning = (f"CDN allowlist {name}: live list rejected ({problem}) and no "
                           "snapshot block; building without it")
            result.warnings.append(warning)
            print(f"warning: {warning}", file=sys.stderr)
        result.networks.extend(nets)
        result.info[name] = _info(source, nets)
    return result
