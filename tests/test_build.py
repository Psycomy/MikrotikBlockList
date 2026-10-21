import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from ipaddress import IPv4Network
from pathlib import Path
from unittest import mock

from mbl.__main__ import main
from mbl.build import _previous_totals, build
from mbl.fetch import SourceResult
from mbl.sources import Source

WHEN = datetime(2026, 10, 19, 4, 17, 0, tzinfo=timezone.utc)
SOURCES_TOML = """
[[source]]
name = "main"
url = "https://example.invalid/main"
format = "plain"
category = "attack"
required = true
variants = ["lite", "full"]
"""
FILES = {"blocklist.rsc", "blocklist.txt", "stats.json",
         "badge-entries.json", "badge-updated.json", "NOTICE.md", "routeros-full.txt",
         "routeros-lite.txt", "blocklist-lite.txt"}


def _nets(count):
    return [IPv4Network(f"1.{i // 256}.{i % 256}.1/32") for i in range(count)]


def _fetcher(count=6000, error=None):
    def fetch(sources):
        src = sources[0]
        if error:
            return [SourceResult(src, [], 0, error)]
        return [SourceResult(src, _nets(count), 0, None)]
    return fetch


class BuildTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.sources = self.tmp / "sources.toml"
        self.sources.write_text(SOURCES_TOML)
        self.allow = self.tmp / "allowlist.txt"
        self.allow.write_text("# none\n")
        self.out = self.tmp / "dist"
        self.version = self.tmp / "VERSION"
        self.version.write_text("3.0.0\n")

    def _build(self, fetcher, previous=None, sources=None, **kwargs):
        kwargs.setdefault("version_path", self.version)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return build(sources or self.sources, self.allow, self.out, previous,
                         now=WHEN, fetcher=fetcher, **kwargs)

    def test_build_writes_outputs(self):
        self.assertEqual(self._build(_fetcher()), 0)
        self.assertEqual({p.name for p in self.out.iterdir()}, FILES)

    def test_build_refuses_on_required_failure(self):
        self.assertEqual(self._build(_fetcher(error="boom")), 1)
        self.assertFalse((self.out / "blocklist.rsc").exists())

    def test_build_skips_drop_check_without_previous(self):
        self.assertEqual(self._build(_fetcher(), previous=None), 0)

    def test_build_refuses_below_minimum(self):
        self.assertEqual(self._build(_fetcher(count=10)), 1)
        self.assertFalse(self.out.exists())

    def test_build_bad_config_returns_2(self):
        self.sources.write_text('[[source]]\nname = "x"\n')
        self.assertEqual(self._build(_fetcher()), 2)
        self.assertEqual(self._build(_fetcher(), sources=self.tmp / "missing.toml"), 2)

    def test_build_unreachable_previous_is_ignored(self):
        self.assertEqual(self._build(_fetcher(), previous="http://127.0.0.1:9/stats.json"), 0)

    @mock.patch("mbl.build._previous_totals", return_value={"full": 6000, "lite": 6000})
    def test_build_refuses_growth_above_double(self, _prev):
        self.assertEqual(self._build(_fetcher(count=12001), previous="x"), 1)
        self.assertFalse(self.out.exists())

    @mock.patch("mbl.build._previous_totals", return_value={"full": 6000, "lite": 6000})
    def test_build_allow_growth_publishes(self, _prev):
        self.assertEqual(self._build(_fetcher(count=12001), previous="x", allow_growth=True), 0)
        self.assertEqual({p.name for p in self.out.iterdir()}, FILES)

    def test_build_splits_by_variant(self):
        two = SOURCES_TOML + """
[[source]]
name = "extra"
url = "https://example.invalid/extra"
format = "plain"
category = "attack"
"""
        self.sources.write_text(two)

        def fetch(sources):
            main, extra = sources
            return [SourceResult(main, _nets(2000), 0, None),
                    SourceResult(extra, [IPv4Network(f"9.{i // 256}.{i % 256}.1/32")
                                         for i in range(4000)], 0, None)]
        self.assertEqual(self._build(fetch), 0)
        lite = (self.out / "blocklist-lite.txt").read_text().splitlines()
        full = (self.out / "blocklist.txt").read_text().splitlines()
        self.assertEqual((len(lite), len(full)), (2000, 6000))
        self.assertTrue(all(line.startswith("1.") for line in lite))

    def test_build_refuses_when_lite_fails(self):
        two = SOURCES_TOML.replace('variants = ["lite", "full"]\n', "") + """
[[source]]
name = "small"
url = "https://example.invalid/small"
format = "plain"
category = "attack"
variants = ["lite", "full"]
"""
        self.sources.write_text(two)

        def fetch(sources):
            main, small = sources
            return [SourceResult(main, _nets(6000), 0, None),
                    SourceResult(small, [IPv4Network(f"9.0.{i // 256}.{i % 256}/32")
                                         for i in range(500)], 0, None)]
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = build(self.sources, self.allow, self.out, None, now=WHEN,
                         fetcher=fetch, version_path=self.version)
        self.assertEqual(code, 1)
        self.assertFalse(self.out.exists())
        self.assertTrue(err.getvalue().startswith("error: lite:"), err.getvalue())

    @mock.patch("mbl.build._previous_totals", return_value={"full": 6000})
    def test_first_lite_publish_skips_drop_and_growth(self, _prev):
        # lite has no previous total: 19000 would exceed 2x of anything small
        self.assertEqual(self._build(_fetcher(count=12000), previous="x"), 0)
        self.assertTrue((self.out / "blocklist-lite.txt").exists())

    def _stats(self, payload):
        resp = io.BytesIO(json.dumps(payload).encode())
        resp.__enter__ = lambda self=resp: self
        resp.__exit__ = lambda *a: None
        return mock.patch("urllib.request.urlopen", return_value=resp)

    def test_previous_full_from_top_level_total(self):
        with self._stats({"total": 7000}):
            self.assertEqual(_previous_totals("http://x"), {"full": 7000})

    def test_previous_totals_per_variant(self):
        with self._stats({"total": 7000, "variants": {"full": {"total": 7001},
                                                      "lite": {"total": 3000}}}):
            self.assertEqual(_previous_totals("http://x"), {"full": 7001, "lite": 3000})

    def test_build_reads_version(self):
        self.version.write_text("9.8.7\n")
        self.assertEqual(self._build(_fetcher()), 0)
        header = (self.out / "routeros-full.txt").read_text().splitlines()[0]
        self.assertIn("script=9.8.7", header)

    def test_build_missing_version_returns_2(self):
        missing = self.tmp / "nope"
        self.assertEqual(self._build(_fetcher(), version_path=missing), 2)
        self.assertFalse(self.out.exists())

    def test_build_empty_version_returns_2(self):
        self.version.write_text("  \n")
        self.assertEqual(self._build(_fetcher()), 2)

    def test_build_malformed_version_returns_2(self):
        for bad in ("3.0", "v3.0.0", "3.0.0 x=1", "3.0.0\nentries=5", "3.0.0-rc1"):
            with self.subTest(version=bad):
                self.version.write_text(bad + "\n")
                self.assertEqual(self._build(_fetcher()), 2)
                self.assertFalse(self.out.exists())


class MainTest(unittest.TestCase):
    @mock.patch("mbl.__main__.build", return_value=0)
    def test_allow_growth_flag(self, build_mock):
        self.assertEqual(main(["build"]), 0)
        self.assertFalse(build_mock.call_args.kwargs["allow_growth"])
        self.assertEqual(main(["build", "--allow-growth"]), 0)
        self.assertTrue(build_mock.call_args.kwargs["allow_growth"])

    @mock.patch("mbl.__main__.build", return_value=0)
    def test_version_file_flag(self, build_mock):
        main(["build"])
        self.assertEqual(build_mock.call_args.kwargs["version_path"], Path("VERSION"))
        main(["build", "--version-file", "x/V"])
        self.assertEqual(build_mock.call_args.kwargs["version_path"], Path("x/V"))


if __name__ == "__main__":
    unittest.main()
