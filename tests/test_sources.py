import tempfile
import unittest
from ipaddress import IPv4Network
from pathlib import Path

from mbl.sources import load_allowlist, load_sources


def _write(tmp: str, text: str) -> Path:
    path = Path(tmp) / "f.toml"
    path.write_text(text, encoding="utf-8")
    return path


ENTRY = '[[source]]\nname = "{name}"\nurl = "https://x/{name}"\nformat = "{fmt}"\ncategory = "{cat}"\n{extra}\n'


class SourcesTest(unittest.TestCase):
    def test_loads_enabled_only(self):
        text = ENTRY.format(name="a", fmt="plain", cat="attack", extra="") + ENTRY.format(
            name="b", fmt="plain", cat="c2", extra="enabled = false"
        )
        with tempfile.TemporaryDirectory() as tmp:
            sources = load_sources(_write(tmp, text))
        self.assertEqual([s.name for s in sources], ["a"])

    def test_rejects_unknown_format(self):
        text = ENTRY.format(name="a", fmt="xml", cat="attack", extra="")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                load_sources(_write(tmp, text))

    def test_rejects_unknown_category(self):
        text = ENTRY.format(name="a", fmt="plain", cat="spam", extra="")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                load_sources(_write(tmp, text))

    def test_rejects_duplicate_name(self):
        text = ENTRY.format(name="a", fmt="plain", cat="attack", extra="") * 2
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                load_sources(_write(tmp, text))

    def test_repo_catalog_is_valid(self):
        sources = load_sources(Path("sources.toml"))
        self.assertGreaterEqual(len(sources), 10)
        by_name = {s.name: s for s in sources}
        self.assertTrue(by_name["spamhaus-drop"].required)

    def test_allowlist_parses(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "allow.txt"
            path.write_text("# x\n1.1.1.1\n\n8.8.8.0/24\n", encoding="utf-8")
            nets = load_allowlist(path)
        self.assertEqual(nets, [IPv4Network("1.1.1.1/32"), IPv4Network("8.8.8.0/24")])


if __name__ == "__main__":
    unittest.main()
