"""Network normalization: filtering, allowlist subtraction, collapse and sort."""
from bisect import bisect_right
from collections.abc import Iterable
from ipaddress import IPv4Network, collapse_addresses

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


def _subtract(net: IPv4Network, allow: list[IPv4Network], starts: list[int]) -> list[IPv4Network]:
    """Remove allowlist entries (sorted, disjoint) from net; only touches overlaps."""
    i = max(bisect_right(starts, int(net.network_address)) - 1, 0)
    pieces = [net]
    while i < len(allow) and int(allow[i].network_address) <= int(net.broadcast_address):
        a = allow[i]
        i += 1
        if not a.overlaps(net):
            continue
        nxt: list[IPv4Network] = []
        for p in pieces:
            if not p.overlaps(a) or p.subnet_of(a):
                if not p.overlaps(a):
                    nxt.append(p)
            else:  # a is strictly inside p
                nxt.extend(p.address_exclude(a))
        pieces = nxt
    return pieces


def normalize(
    networks: Iterable[IPv4Network],
    allowlist: Iterable[IPv4Network],
    min_prefixlen: int = 8,
) -> list[IPv4Network]:
    kept = [n for n in networks if n.prefixlen >= min_prefixlen and _is_blockable(n)]
    allow = sorted(collapse_addresses(allowlist))
    starts = [int(a.network_address) for a in allow]
    out: list[IPv4Network] = []
    for net in kept:
        out.extend(_subtract(net, allow, starts) if allow else [net])
    return sorted(collapse_addresses(out))
