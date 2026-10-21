"""Network normalization: filtering, allowlist subtraction, collapse and sort."""
from bisect import bisect_right
from collections.abc import Iterable
from ipaddress import IPv4Network, IPv6Network, collapse_addresses

# IANA special-purpose / non-global IPv4 blocks. A network overlapping any of
# these is dropped entirely (is_global alone misses partial overlaps such as
# 100.0.0.0/8, which contains the CGNAT range).
NON_GLOBAL_BLOCKS: tuple[IPv4Network, ...] = tuple(
    IPv4Network(n)
    for n in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.88.99.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "255.255.255.255/32",
    )
)


# (first, last) integer bounds of each block: same as overlaps(), much cheaper.
_NON_GLOBAL_RANGES = tuple((int(b.network_address), int(b.broadcast_address)) for b in NON_GLOBAL_BLOCKS)


def _is_blockable(net: IPv4Network) -> bool:
    first, last = int(net.network_address), int(net.broadcast_address)
    if any(first <= hi and lo <= last for lo, hi in _NON_GLOBAL_RANGES):
        return False
    return net.is_global and not net.is_multicast and not net.is_reserved


def _subtract(net, allow: list, starts: list[int]) -> list:
    """Remove allowlist entries (sorted, disjoint) from net; only touches overlaps."""
    i = max(bisect_right(starts, int(net.network_address)) - 1, 0)
    pieces = [net]
    while i < len(allow) and int(allow[i].network_address) <= int(net.broadcast_address):
        a = allow[i]
        i += 1
        if not a.overlaps(net):
            continue
        nxt: list = []
        for p in pieces:
            if not p.overlaps(a) or p.subnet_of(a):
                if not p.overlaps(a):
                    nxt.append(p)
            else:  # a is strictly inside p
                nxt.extend(p.address_exclude(a))
        pieces = nxt
    return pieces


def _clean(networks, allowlist, version, min_prefixlen, blockable):
    kept = [n for n in networks if n.version == version and n.prefixlen >= min_prefixlen
            and blockable(n)]
    allow = sorted(collapse_addresses(a for a in allowlist if a.version == version))
    starts = [int(a.network_address) for a in allow]
    out: list = []
    for net in kept:
        out.extend(_subtract(net, allow, starts) if allow else [net])
    return sorted(collapse_addresses(out))


def normalize(
    networks: Iterable[IPv4Network | IPv6Network],
    allowlist: Iterable[IPv4Network | IPv6Network],
    min_prefixlen: int = 8,
) -> list[IPv4Network]:
    """IPv4 only: IPv6 networks (and IPv6 allowlist entries) are ignored."""
    return _clean(networks, allowlist, 4, min_prefixlen, _is_blockable)


# Non-global IPv6 blocks: unspecified/loopback/IPv4-mapped (::/8), NAT64,
# Teredo, documentation, 6to4, ULA, link-local and multicast. Overlap drops.
NON_GLOBAL_BLOCKS6: tuple[IPv6Network, ...] = tuple(
    IPv6Network(n)
    for n in (
        "::/8",
        "64:ff9b::/96",
        "64:ff9b:1::/48",
        "2001::/32",
        "2001:db8::/32",
        "2002::/16",
        "fc00::/7",
        "fe80::/10",
        "ff00::/8",
    )
)
_NON_GLOBAL_RANGES6 = tuple((int(b.network_address), int(b.broadcast_address)) for b in NON_GLOBAL_BLOCKS6)


def _is_blockable6(net: IPv6Network) -> bool:
    first, last = int(net.network_address), int(net.broadcast_address)
    return not any(first <= hi and lo <= last for lo, hi in _NON_GLOBAL_RANGES6)


def normalize6(
    networks: Iterable[IPv4Network | IPv6Network],
    allowlist: Iterable[IPv4Network | IPv6Network],
    min_prefixlen: int = 19,
) -> list[IPv6Network]:
    """IPv6 only: drop non-global and anything wider than min_prefixlen, subtract allowlist."""
    return _clean(networks, allowlist, 6, min_prefixlen, _is_blockable6)
