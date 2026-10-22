import gzip
import io
import shutil
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from pathlib import Path

from mbl.__main__ import main
from mbl.geo import CountryDb, fetch_dbip

SAMPLE = Path(__file__).parent / "fixtures" / "dbip_sample.csv.gz"


def ip4(text):
    a, b, c, d = map(int, text.split("."))
    return (a << 24) | (b << 16) | (c << 8) | d


def ip6(text):
    import ipaddress
    return int(ipaddress.IPv6Address(text))


def _not_found(url):
    raise urllib.error.HTTPError(url, 404, "Not Found", None, None)


class CountryDbTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.path = cls.tmp / "dbip-country-lite-2026-10.csv.gz"
        shutil.copy(SAMPLE, cls.path)
        cls.db = CountryDb.load(cls.path)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_country_single_row(self):
        self.assertEqual(self.db.country(ip4("1.0.0.0"), ip4("1.0.0.255"), 4), "AU")
        self.assertEqual(self.db.country(ip4("1.0.0.64"), ip4("1.0.0.127"), 4), "AU")

    def test_country_spanning_two_rows_is_empty(self):
        self.assertEqual(self.db.country(ip4("2.0.0.0"), ip4("2.0.0.255"), 4), "")
        self.assertEqual(self.db.country(ip4("2.0.0.0"), ip4("2.0.0.127"), 4), "FR")
        self.assertEqual(self.db.country(ip4("1.0.0.0"), ip4("1.0.1.255"), 4), "")

    def test_adjacent_rows_same_country_are_one(self):
        self.assertEqual(self.db.country(ip4("5.0.0.0"), ip4("5.0.1.255"), 4), "ES")

    def test_country_uncovered_and_zz_are_zz(self):
        self.assertEqual(self.db.country(ip4("3.0.0.0"), ip4("3.0.0.255"), 4), "ZZ")
        self.assertEqual(self.db.country(ip4("4.0.0.0"), ip4("4.0.0.255"), 4), "ZZ")
        self.assertEqual(self.db.country(0, 0, 4), "ZZ")

    def test_gap_then_row_is_several(self):
        # starts in the gap before 5.0.0.0/ES and reaches into it: more than one answer
        self.assertEqual(self.db.country(ip4("4.255.255.0"), ip4("5.0.0.10"), 4), "")

    def test_ipv6_lookup(self):
        self.assertEqual(self.db.country(ip6("2001:200::"), ip6("2001:200::ffff"), 6), "JP")
        self.assertEqual(self.db.country(ip6("2a00:1450:4001::"), ip6("2a00:1450:4001::ffff"), 6), "IE")
        self.assertEqual(self.db.country(ip6("2001:db8::"), ip6("2001:db8::1"), 6), "ZZ")
        self.assertEqual(self.db.country(ip6("2001:200::"), ip6("2a00:1450::1"), 6), "")

    def test_month_from_filename(self):
        self.assertEqual(self.db.month, "2026-10")


def gz(text="1.0.0.0,1.0.0.255,AU\n"):
    return gzip.compress(text.encode())


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_fetch_uses_cache(self):
        cached = self.tmp / "dbip-country-lite-2026-10.csv.gz"
        cached.write_bytes(gz())
        calls = []
        got = fetch_dbip(self.tmp, date(2026, 10, 22), fetcher=lambda u: calls.append(u))
        self.assertEqual(got, cached)
        self.assertEqual(calls, [])

    def test_fetch_falls_back_to_previous_month(self):
        urls = []

        def fetcher(url):
            urls.append(url)
            if "2026-10" in url:
                _not_found(url)
            return gz()

        got = fetch_dbip(self.tmp, date(2026, 10, 22), fetcher=fetcher)
        self.assertEqual(got.name, "dbip-country-lite-2026-09.csv.gz")
        self.assertEqual(urls[0], "https://download.db-ip.com/free/dbip-country-lite-2026-10.csv.gz")
        self.assertTrue(got.exists())

    def test_fetch_january_falls_back_to_december(self):
        def fetcher(url):
            if "2026-01" in url:
                _not_found(url)
            return gz()

        got = fetch_dbip(self.tmp, date(2026, 1, 5), fetcher=fetcher)
        self.assertEqual(got.name, "dbip-country-lite-2025-12.csv.gz")

    def test_fetch_rejects_non_gzip(self):
        got = fetch_dbip(self.tmp, date(2026, 10, 22), fetcher=lambda u: b"<html>nope</html>")
        self.assertIsNone(got)
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_fetch_both_missing_returns_none(self):
        self.assertIsNone(fetch_dbip(self.tmp, date(2026, 10, 22), fetcher=_not_found))

    def test_fetch_removes_other_months(self):
        old = self.tmp / "dbip-country-lite-2026-07.csv.gz"
        old.write_bytes(gz())
        got = fetch_dbip(self.tmp, date(2026, 10, 22), fetcher=lambda u: gz())
        self.assertFalse(old.exists())
        self.assertTrue(got.exists())

    def test_cli_dbip_fetch_never_fails(self):
        import mbl.geo
        orig = mbl.geo._download
        mbl.geo._download = _not_found
        self.addCleanup(setattr, mbl.geo, "_download", orig)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["dbip-fetch", "--cache", str(self.tmp / "c")])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("warning", err.getvalue())

    def test_unwritable_cache_returns_none_and_cli_exits_zero(self):
        blocker = self.tmp / "file"
        blocker.write_text("x")
        cache = blocker / "sub"  # cannot be created under a regular file
        self.assertIsNone(fetch_dbip(cache, date(2026, 10, 22), fetcher=lambda u: gz()))
        import mbl.geo
        orig = mbl.geo._download
        mbl.geo._download = lambda u: gz()
        self.addCleanup(setattr, mbl.geo, "_download", orig)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["dbip-fetch", "--cache", str(cache)])
        self.assertEqual((code, out.getvalue()), (0, ""))

    def test_cli_catches_unexpected_exception(self):
        import mbl.__main__ as m
        orig = m.fetch_dbip
        m.fetch_dbip = lambda *a, **k: 1 / 0
        self.addCleanup(setattr, m, "fetch_dbip", orig)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["dbip-fetch", "--cache", str(self.tmp)])
        self.assertEqual((code, out.getvalue()), (0, ""))
        self.assertIn("warning", err.getvalue())

    def test_corrupt_cache_is_refetched(self):
        cached = self.tmp / "dbip-country-lite-2026-10.csv.gz"
        cached.write_bytes(b"garbage")
        got = fetch_dbip(self.tmp, date(2026, 10, 22), fetcher=lambda u: gz())
        self.assertEqual(got, cached)
        self.assertEqual(gzip.decompress(cached.read_bytes()), b"1.0.0.0,1.0.0.255,AU\n")

    def test_cli_dbip_fetch_prints_only_path(self):
        import mbl.geo
        orig = mbl.geo._download
        mbl.geo._download = lambda u: gz()
        self.addCleanup(setattr, mbl.geo, "_download", orig)
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["dbip-fetch", "--cache", str(self.tmp / "c")])
        self.assertEqual(code, 0)
        self.assertTrue(Path(out.getvalue().strip()).exists())
        self.assertEqual(len(out.getvalue().strip().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
