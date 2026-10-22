import tempfile
import unittest
from ipaddress import IPv4Network, IPv6Network
from pathlib import Path

from mbl.sources import VARIANTS, load_allowlist, load_sources


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

    def _load(self, extra):
        text = ENTRY.format(name="a", fmt="plain", cat="attack", extra=extra)
        with tempfile.TemporaryDirectory() as tmp:
            return load_sources(_write(tmp, text))

    def test_variants_default_full(self):
        self.assertEqual(VARIANTS, ("full", "lite"))
        self.assertEqual(self._load("")[0].variants, ("full",))
        self.assertEqual(self._load('variants = ["lite", "full"]')[0].variants, ("lite", "full"))

    def test_unknown_variant_rejected(self):
        for extra in ('variants = ["full", "mini"]', "variants = []"):
            with self.subTest(extra=extra):
                with self.assertRaises(ValueError):
                    self._load(extra)

    def test_lite_requires_full(self):
        with self.assertRaises(ValueError):
            self._load('variants = ["lite"]')

    def test_repo_catalog_lite_sources(self):
        sources = load_sources(Path("sources.toml"))
        lite = {s.name for s in sources if "lite" in s.variants}
        self.assertEqual(lite, {"spamhaus-drop", "spamhaus-drop-v6", "dshield", "et-compromised", "threatfox", "threatcluster"})

    def test_allowlist_parses(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "allow.txt"
            path.write_text("# x\n1.1.1.1\n\n8.8.8.0/24\n", encoding="utf-8")
            nets = load_allowlist(path)
        self.assertEqual(nets, [IPv4Network("1.1.1.1/32"), IPv4Network("8.8.8.0/24")])

    def test_allowlist_inline_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "allow.txt"
            path.write_text("1.1.1.1 # dns\n8.8.8.0/24\t#google\n", encoding="utf-8")
            nets = load_allowlist(path)
        self.assertEqual(nets, [IPv4Network("1.1.1.1/32"), IPv4Network("8.8.8.0/24")])

    def test_allowlist_invalid_entry_names_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "allow.txt"
            path.write_text("# x\n1.1.1.1\nnot-an-ip\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, r"line 3"):
                load_allowlist(path)

    def test_allowlist_reads_ipv6(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "allow.txt"
            path.write_text("1.1.1.1\n2606:4700::/32 # cf\n2620:fe::fe\n", encoding="utf-8")
            nets = load_allowlist(path)
        self.assertEqual(nets, [IPv4Network("1.1.1.1/32"), IPv6Network("2606:4700::/32"),
                                IPv6Network("2620:fe::fe/128")])

    def test_repo_catalog_has_spamhaus_v6(self):
        s = {x.name: x for x in load_sources(Path("sources.toml"))}["spamhaus-drop-v6"]
        self.assertEqual(s.format, "jsonl_cidr")
        self.assertFalse(s.required)
        self.assertEqual(s.category, "attack")
        self.assertEqual(s.variants, ("lite", "full"))
        self.assertEqual(s.url, "https://www.spamhaus.org/drop/drop_v6.json")

    def test_auth_fields_default_empty(self):
        s = self._load("")[0]
        self.assertEqual((s.auth_env, s.auth_header, s.post_body), ("", "Auth-Key", ""))

    def test_auth_fields_loaded(self):
        s = self._load('auth_env = "K"\nauth_header = "X-Key"\npost_body = \'{"q": 1}\'')[0]
        self.assertEqual((s.auth_env, s.auth_header, s.post_body), ("K", "X-Key", '{"q": 1}'))

    def test_rejects_invalid_post_body(self):
        with self.assertRaises(ValueError):
            self._load('post_body = "{not json"')

    def test_rejects_empty_auth_header(self):
        with self.assertRaises(ValueError):
            self._load('auth_env = "K"\nauth_header = ""')

    def test_repo_catalog_has_threatfox_api(self):
        s = {x.name: x for x in load_sources(Path("sources.toml"))}["threatfox"]
        self.assertEqual(s.format, "threatfox_json")
        self.assertEqual(s.url, "https://threatfox-api.abuse.ch/api/v1/")
        self.assertEqual(s.auth_env, "THREATFOX_AUTH_KEY")
        self.assertEqual(s.auth_header, "Auth-Key")
        self.assertFalse(s.required)
        self.assertEqual(s.variants, ("lite", "full"))

    def test_repo_allowlist_has_ipv6(self):
        nets = load_allowlist(Path("allowlist.txt"))
        self.assertIn(IPv6Network("2606:50c0::/32"), nets)
        self.assertIn(IPv6Network("2620:fe::fe/128"), nets)
        self.assertNotIn(IPv6Network("2a06:98c0::/29"), nets)  # Cloudflare comes from the CDN lists

    def test_repo_allowlist_is_valid(self):
        nets = load_allowlist(Path("allowlist.txt"))
        self.assertIn(IPv4Network("185.199.108.0/22"), nets)
        self.assertIn(IPv4Network("1.1.1.1/32"), nets)


if __name__ == "__main__":
    unittest.main()
