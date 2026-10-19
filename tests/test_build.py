import contextlib
import io
import tempfile
import unittest
from datetime import datetime, timezone
from ipaddress import IPv4Network
from pathlib import Path

from mbl.build import build
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
"""
FILES = {"blocklist.rsc", "blocklist.txt", "stats.json",
         "badge-entries.json", "badge-updated.json", "NOTICE.md"}


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

    def _build(self, fetcher, previous=None, sources=None):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return build(sources or self.sources, self.allow, self.out, previous,
                         now=WHEN, fetcher=fetcher)

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


if __name__ == "__main__":
    unittest.main()
