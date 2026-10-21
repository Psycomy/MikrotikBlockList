import contextlib
import io
import tempfile
import unittest
import urllib.error
from datetime import date
from ipaddress import ip_network
from pathlib import Path
from unittest import mock

from mbl import cdn
from mbl.__main__ import main

FIXTURES = Path(__file__).parent / "fixtures"
URL_FILES = {
    "https://www.cloudflare.com/ips-v4": "cdn_cloudflare_v4.txt",
    "https://www.cloudflare.com/ips-v6": "cdn_cloudflare_v6.txt",
    "https://api.fastly.com/public-ip-list": "cdn_fastly.json",
    "https://ip-ranges.amazonaws.com/ip-ranges.json": "cdn_cloudfront.json",
}


def _text(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def _fetcher(overrides=None):
    """Serve the fixtures; an override is text to return or an Exception to raise."""
    overrides = overrides or {}

    def fetch(url):
        value = overrides.get(url, None)
        if isinstance(value, Exception):
            raise value
        return _text(URL_FILES[url]) if value is None else value
    return fetch


def _snapshot_text():
    return (
        "# provider cloudflare 2026-01-01\n"
        + "".join(f"10{i}.0.0.0/24\n".replace("10", "20", 1) for i in range(1, 7))
        + "2606:4700::/32\n"
        + "# provider fastly 2026-01-01\n"
        + "".join(f"21{i}.0.0.0/24\n" for i in range(1, 7))
        + "2a04:4e40::/32\n"
        + "# provider cloudfront 2026-01-01\n"
        + "".join(f"22{i}.0.0.0/24\n" for i in range(1, 7))
        + "2600:9000::/28\n"
    )


class CdnTestBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.snapshot = self.tmp / "allowlist-cdn.snapshot.txt"
        self.snapshot.write_text(_snapshot_text())

    def fetch(self, overrides=None, snapshot=None):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            result = cdn.fetch_cdn(snapshot or self.snapshot, _fetcher(overrides), backoff=0)
        return result, err.getvalue()


class ExtractionTest(CdnTestBase):
    def test_all_live(self):
        result, err = self.fetch()
        self.assertEqual(err, "")
        self.assertEqual({n: i["source"] for n, i in result.info.items()},
                         {"cloudflare": "live", "fastly": "live", "cloudfront": "live"})
        self.assertEqual(result.info["cloudflare"]["prefixes4"], 15)
        self.assertEqual(result.info["cloudflare"]["prefixes6"], 7)
        self.assertEqual(result.info["fastly"]["prefixes4"], 21)
        self.assertEqual(result.info["fastly"]["prefixes6"], 3)
        self.assertIn(ip_network("104.16.0.0/13"), result.networks)
        self.assertIn(ip_network("151.101.0.0/16"), result.networks)
        self.assertIn(ip_network("2a04:4e40::/32"), result.networks)

    def test_cloudfront_only_cloudfront_service(self):
        result, _ = self.fetch()
        # fixture: 6 CLOUDFRONT and 3 other prefixes per family
        self.assertEqual(result.info["cloudfront"]["prefixes4"], 6)
        self.assertEqual(result.info["cloudfront"]["prefixes6"], 6)

    def test_provider_table(self):
        self.assertEqual(set(cdn.PROVIDERS), {"cloudflare", "fastly", "cloudfront"})


class FallbackTest(CdnTestBase):
    def test_cdn_html_falls_back_to_snapshot(self):
        html = "<html><body>Just a moment...</body></html>"
        result, err = self.fetch({"https://www.cloudflare.com/ips-v4": html})
        self.assertEqual(result.info["cloudflare"],
                         {"source": "snapshot", "prefixes4": 6, "prefixes6": 1})
        self.assertIn("cloudflare", err)
        self.assertIn(ip_network("201.0.0.0/24"), result.networks)
        self.assertEqual(result.info["fastly"]["source"], "live")
        self.assertTrue(any("cloudflare" in w for w in result.warnings))

    def test_cdn_rejects_too_wide(self):
        for wide in ("0.0.0.0/0", "10.0.0.0/7"):
            text = _text("cdn_cloudflare_v4.txt") + "\n" + wide + "\n"
            result, _ = self.fetch({"https://www.cloudflare.com/ips-v4": text})
            self.assertEqual(result.info["cloudflare"]["source"], "snapshot", wide)
            self.assertNotIn(ip_network(wide), result.networks)
        text = _text("cdn_cloudflare_v6.txt") + "\n::/0\n"
        result, _ = self.fetch({"https://www.cloudflare.com/ips-v6": text})
        self.assertEqual(result.info["cloudflare"]["source"], "snapshot")
        self.assertNotIn(ip_network("::/0"), result.networks)

    def test_cdn_accepts_exact_limits(self):
        text = _text("cdn_cloudflare_v4.txt") + "\n20.0.0.0/8\n"
        result, _ = self.fetch({"https://www.cloudflare.com/ips-v4": text})
        self.assertEqual(result.info["cloudflare"]["source"], "live")
        text = _text("cdn_cloudflare_v6.txt") + "\n2000::/16\n"
        result, _ = self.fetch({"https://www.cloudflare.com/ips-v6": text})
        self.assertEqual(result.info["cloudflare"]["source"], "live")

    def test_cdn_too_few_ipv4_rejected(self):
        few = "\n".join(_text("cdn_cloudflare_v4.txt").splitlines()[:4])
        result, _ = self.fetch({"https://www.cloudflare.com/ips-v4": few})
        self.assertEqual(result.info["cloudflare"]["source"], "snapshot")

    def test_cdn_no_ipv6_rejected(self):
        result, _ = self.fetch({"https://www.cloudflare.com/ips-v6": ""})
        self.assertEqual(result.info["cloudflare"]["source"], "snapshot")

    def test_cdn_network_error_falls_back(self):
        result, _ = self.fetch({"https://api.fastly.com/public-ip-list": OSError("down")})
        self.assertEqual(result.info["fastly"]["source"], "snapshot")

    def test_cdn_bad_json_falls_back(self):
        result, _ = self.fetch({"https://ip-ranges.amazonaws.com/ip-ranges.json": "{}"})
        self.assertEqual(result.info["cloudfront"]["source"], "snapshot")

    def test_cdn_missing_everywhere_warns_and_continues(self):
        down = {u: OSError("down") for u in URL_FILES}
        empty = self.tmp / "none.txt"
        result, err = self.fetch(down, snapshot=empty)
        self.assertEqual(result.networks, [])
        self.assertEqual(result.info, {n: {"source": "missing", "prefixes4": 0, "prefixes6": 0}
                                       for n in cdn.PROVIDERS})
        self.assertEqual(len(result.warnings), 3)
        for name in cdn.PROVIDERS:
            self.assertIn(name, err)

    def test_invalid_snapshot_block_counts_as_missing(self):
        self.snapshot.write_text("# provider cloudflare 2026-01-01\n0.0.0.0/0\n")
        down = {u: OSError("down") for u in URL_FILES}
        result, _ = self.fetch(down)
        self.assertEqual(result.info["cloudflare"]["source"], "missing")

    def test_default_fetcher_retries_then_falls_back(self):
        err = urllib.error.URLError("down")
        with mock.patch("mbl.fetch.urllib.request.urlopen", side_effect=err) as urlopen, \
                contextlib.redirect_stderr(io.StringIO()):
            result = cdn.fetch_cdn(self.snapshot, backoff=0)
        self.assertEqual(urlopen.call_count, 9)  # 3 attempts for each of 3 providers
        self.assertEqual({i["source"] for i in result.info.values()}, {"snapshot"})


class SnapshotTest(CdnTestBase):
    def test_write_snapshot_roundtrip(self):
        live, _ = self.fetch()
        blocks = cdn.fetch_live(_fetcher())
        out = self.tmp / "snap.txt"
        cdn.write_snapshot(out, blocks, date(2026, 10, 21))
        text = out.read_text()
        self.assertTrue(text.startswith("# provider cloudflare 2026-10-21\n"))
        self.assertIn("# provider fastly 2026-10-21\n", text)
        self.assertIn("# provider cloudfront 2026-10-21\n", text)
        result, _ = self.fetch({u: OSError("down") for u in URL_FILES}, snapshot=out)
        self.assertEqual({i["source"] for i in result.info.values()}, {"snapshot"})
        self.assertEqual(sorted(map(str, result.networks)), sorted(map(str, live.networks)))

    def test_cdn_snapshot_cli(self):
        out = self.tmp / "cli.txt"
        blocks = cdn.fetch_live(_fetcher())
        with mock.patch("mbl.__main__.fetch_live", return_value=blocks), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["cdn-snapshot", "--out", str(out)]), 0)
        self.assertIn("# provider cloudflare ", out.read_text())

    def test_cdn_snapshot_cli_failure_writes_nothing(self):
        out = self.tmp / "cli.txt"
        with mock.patch("mbl.__main__.fetch_live", side_effect=ValueError("cloudflare: bad")), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["cdn-snapshot", "--out", str(out)]), 1)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
