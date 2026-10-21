"""Per-format parsers turning raw source text into IPv4/IPv6 networks."""
import csv
import re
from dataclasses import dataclass, field
import json
from ipaddress import IPv4Network, IPv6Network, ip_network

_PLAIN_TOKEN = re.compile(r"[#;\s]")


@dataclass
class ParseResult:
    networks: list[IPv4Network | IPv6Network] = field(default_factory=list)
    invalid: int = 0


def _lines(text: str) -> list[str]:
    return text.lstrip("﻿").splitlines()


def _add(result: ParseResult, token: str) -> None:
    """Append token as an IPv4 or IPv6 network; count anything else as invalid."""
    try:
        result.networks.append(ip_network(token, strict=False))
    except ValueError:
        result.invalid += 1


def _parse_plain(text: str) -> ParseResult:
    result = ParseResult()
    for line in _lines(text):
        line = line.strip()
        if not line or line[0] in "#;":
            continue
        _add(result, _PLAIN_TOKEN.split(line, maxsplit=1)[0])
    return result


def _parse_dshield(text: str) -> ParseResult:
    result = ParseResult()
    for line in _lines(text):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("Start"):
            continue
        cols = line.split("\t") if "\t" in line else line.split()
        if len(cols) < 3:
            result.invalid += 1
            continue
        _add(result, f"{cols[0].strip()}/{cols[2].strip()}")
    return result


def _csv_rows(text: str):
    lines = [ln for ln in _lines(text) if ln.strip() and not ln.lstrip().startswith("#")]
    return csv.reader(lines, skipinitialspace=True)


def _parse_threatfox_csv(text: str) -> ParseResult:
    result = ParseResult()
    for row in _csv_rows(text):
        if len(row) < 3:
            result.invalid += 1
            continue
        value = row[2].strip()
        if value.startswith("["):  # "[addr]:port"
            _add(result, value[1:].split("]", 1)[0])
        elif value.count(":") > 1:  # bare IPv6 address
            _add(result, value)
        else:
            _add(result, value.split(":", 1)[0])
    return result


def _parse_csv_first_column(text: str) -> ParseResult:
    result = ParseResult()
    for row in _csv_rows(text):
        value = row[0].strip()
        if value.lower() in ("ip", "address"):
            continue  # header
        _add(result, value)
    return result


def _parse_jsonl_cidr(text: str) -> ParseResult:
    """One JSON object per line; lines without a "cidr" key (metadata) are ignored."""
    result = ParseResult()
    for line in _lines(text):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            result.invalid += 1
            continue
        if not isinstance(obj, dict) or "cidr" not in obj:
            continue
        cidr = obj["cidr"]
        if not isinstance(cidr, str):
            result.invalid += 1
            continue
        _add(result, cidr.strip())
    return result


_PARSERS = {
    "plain": _parse_plain,
    "dshield": _parse_dshield,
    "threatfox_csv": _parse_threatfox_csv,
    "c2intel_csv": _parse_csv_first_column,
    "csv": _parse_csv_first_column,
    "jsonl_cidr": _parse_jsonl_cidr,
}


def parse(fmt: str, text: str) -> ParseResult:
    """Parse text of the given source format; raise ValueError for unknown formats."""
    try:
        parser = _PARSERS[fmt]
    except KeyError:
        raise ValueError(f"unknown source format: {fmt!r}") from None
    return parser(text)
