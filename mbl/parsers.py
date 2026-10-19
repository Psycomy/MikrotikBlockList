"""Per-format parsers turning raw source text into IPv4 networks."""
import csv
import re
from dataclasses import dataclass, field
from ipaddress import IPv4Network

_PLAIN_TOKEN = re.compile(r"[#;\s]")


@dataclass
class ParseResult:
    networks: list[IPv4Network] = field(default_factory=list)
    invalid: int = 0


def _lines(text: str) -> list[str]:
    return text.lstrip("﻿").splitlines()


def _add(result: ParseResult, token: str) -> None:
    """Append token as an IPv4 network; ignore IPv6, count anything else as invalid."""
    if ":" in token:
        return
    try:
        result.networks.append(IPv4Network(token, strict=False))
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
        if value.startswith("[") or value.count(":") > 1:
            continue  # IPv6
        _add(result, value.split(":", 1)[0])
    return result


def _parse_c2intel_csv(text: str) -> ParseResult:
    result = ParseResult()
    for row in _csv_rows(text):
        value = row[0].strip()
        if value.lower() == "ip":
            continue  # header
        _add(result, value)
    return result


_PARSERS = {
    "plain": _parse_plain,
    "dshield": _parse_dshield,
    "threatfox_csv": _parse_threatfox_csv,
    "c2intel_csv": _parse_c2intel_csv,
}


def parse(fmt: str, text: str) -> ParseResult:
    """Parse text of the given source format; raise ValueError for unknown formats."""
    try:
        parser = _PARSERS[fmt]
    except KeyError:
        raise ValueError(f"unknown source format: {fmt!r}") from None
    return parser(text)
