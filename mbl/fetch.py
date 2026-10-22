"""Parallel download of blocklist sources."""
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from ipaddress import IPv4Network, IPv6Network

from mbl.parsers import parse
from mbl.sources import Source

USER_AGENT = "MikrotikBlockList/2.0 (+https://github.com/Psycomy/MikrotikBlockList)"


@dataclass
class SourceResult:
    source: Source
    networks: list[IPv4Network | IPv6Network] = field(default_factory=list)
    invalid: int = 0
    error: str | None = None


def missing_key_error(env: str) -> str:
    """Error of a source skipped because its auth_env variable is unset or empty."""
    return f"{env} not set, source skipped"


def _retryable(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code >= 500 or exc.code == 429
    return True  # network errors and timeouts


def _download(url: str, timeout: float, retries: int, backoff: float,
              headers: dict[str, str] | None = None, body: bytes | None = None) -> str:
    request = urllib.request.Request(url, data=body,
                                     headers={"User-Agent": USER_AGENT, **(headers or {})})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, OSError) as exc:
            if attempt == retries or not _retryable(exc):
                raise
            time.sleep(backoff)
    raise AssertionError("unreachable")


def _fetch_one(source: Source, timeout: float, retries: int, backoff: float) -> SourceResult:
    headers: dict[str, str] = {}
    if source.auth_env:
        key = os.environ.get(source.auth_env, "").strip()
        if not key:
            # never fail the build: an unset key is just a failed optional source
            return SourceResult(source, error=missing_key_error(source.auth_env))
        headers[source.auth_header] = key
    body = None
    if source.post_body:
        headers["Content-Type"] = "application/json"
        body = source.post_body.encode("utf-8")
    try:
        # error messages come from urllib (status and reason), never from the headers
        text = _download(source.url, timeout, retries, backoff, headers, body)
        parsed = parse(source.format, text)
    except Exception as exc:  # any download or parse failure marks this source as failed
        return SourceResult(source, error=f"{type(exc).__name__}: {exc}")
    if not parsed.networks:
        return SourceResult(source, invalid=parsed.invalid, error="no valid entries")
    return SourceResult(source, parsed.networks, parsed.invalid)


def fetch_all(sources: list[Source], timeout: float = 30, retries: int = 2,
              backoff: float = 2) -> list[SourceResult]:
    """Fetch all sources in parallel; results keep the input order."""
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(lambda s: _fetch_one(s, timeout, retries, backoff), sources))
