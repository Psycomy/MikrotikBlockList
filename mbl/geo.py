"""DB-IP country lookup: load the monthly lite CSV and fetch it with a cache."""
import gzip
import ipaddress
import re
import sys
import urllib.request
from array import array
from bisect import bisect_right
from datetime import date
from pathlib import Path

from mbl.fetch import USER_AGENT

URL = "https://download.db-ip.com/free/dbip-country-lite-{month}.csv.gz"
NAME_RE = re.compile(r"^dbip-country-lite-(\d{4}-\d{2})\.csv\.gz$")
TIMEOUT = 60


class CountryDb:
    """Sorted, non-overlapping ranges per IP version; adjacent same-country rows are merged."""

    def __init__(self, month: str = ""):
        self.month = month
        # IPv4 fits in unsigned 32 bit arrays; IPv6 needs Python ints.
        self._starts = {4: array("I"), 6: []}
        self._ends = {4: array("I"), 6: []}
        self._codes = {4: [], 6: []}

    @classmethod
    def load(cls, path: Path) -> "CountryDb":
        path = Path(path)
        match = NAME_RE.match(path.name)
        db = cls(match.group(1) if match else "")
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            for line in handle:
                parts = line.strip().split(",")
                if len(parts) < 3:
                    continue
                try:
                    first = ipaddress.ip_address(parts[0])
                    last = ipaddress.ip_address(parts[1])
                except ValueError:
                    continue
                if first.version != last.version:
                    continue
                db._add(first.version, int(first), int(last), parts[2].strip().upper())
        return db

    def _add(self, version: int, first: int, last: int, code: str) -> None:
        starts, ends, codes = self._starts[version], self._ends[version], self._codes[version]
        if starts and first <= ends[-1]:
            return  # overlapping or out of order: keep the earlier row
        if codes and codes[-1] == code and ends[-1] + 1 == first:
            ends[-1] = last
            return
        starts.append(first)
        ends.append(last)
        codes.append(code)

    def country(self, first: int, last: int, version: int) -> str:
        """Country code when one row covers the whole range, else ''. 'ZZ' is unknown."""
        starts = self._starts[version]
        i = bisect_right(starts, first) - 1
        if i < 0 or last > self._ends[version][i] or last < first:
            return ""
        code = self._codes[version][i]
        return "" if code == "ZZ" else code


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read()


def _month(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def _previous_month(day: date) -> date:
    return date(day.year - 1, 12, 1) if day.month == 1 else date(day.year, day.month - 1, 1)


def _valid_gzip(body: bytes) -> bool:
    if body[:2] != b"\x1f\x8b":
        return False
    try:
        gzip.decompress(body)  # also rejects truncated data
    except (OSError, EOFError, ValueError):
        return False
    return True


def fetch_dbip(cache_dir: Path, today: date, fetcher=None) -> Path | None:
    """Return this month's file (cached or downloaded), else last month's, else None.

    Never raises: network, format and filesystem problems warn on stderr and give None.
    """
    cache_dir = Path(cache_dir)
    fetcher = fetcher or _download
    for day in (today, _previous_month(today)):
        name = f"dbip-country-lite-{_month(day)}.csv.gz"
        target = cache_dir / name
        try:
            if target.exists():
                if _valid_gzip(target.read_bytes()):
                    return target
                print(f"warning: DB-IP cached {name} is corrupt, fetching again", file=sys.stderr)
            body = fetcher(URL.format(month=_month(day)))
            if not _valid_gzip(body):
                raise ValueError("not a gzip file")
            cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            tmp.write_bytes(body)
            tmp.replace(target)
            for other in cache_dir.glob("dbip-country-lite-*.csv.gz"):
                if other != target:
                    other.unlink()
        except Exception as exc:  # network, HTTP, format or filesystem: try the next month
            print(f"warning: DB-IP {_month(day)}: {exc}", file=sys.stderr)
            continue
        return target
    return None
