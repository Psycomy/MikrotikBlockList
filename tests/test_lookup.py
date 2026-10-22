import gzip
import json
import tempfile
import unittest
from datetime import datetime, timezone
from ipaddress import IPv4Network, IPv6Network
from pathlib import Path

from mbl.fetch import SourceResult
from mbl.lookup import lookup_data, write_lookup
from mbl.sources import Source

WHEN = datetime(2026, 10, 22, 4, 17, 0, tzinfo=timezone.utc)


def _result(name, nets, error=None, notice=""):
    src = Source(name, f"https://example.invalid/{name}", "plain", "attack",
                 license_note=f"{name} terms")
    return SourceResult(src, [IPv4Network(n) if ":" not in n else IPv6Network(n) for n in nets],
                        0, error, notice)


def _v4(*cidrs):
    return [IPv4Network(c) for c in cidrs]


class FakeGeo:
    month = "2026-10"

    def country(self, first, last, version):
        return "DE" if version == 4 else "NL"


class ZzGeo:
    month = "2026-10"

    def country(self, first, last, version):
        return "ZZ"


class LookupTest(unittest.TestCase):
    def test_unknown_country_code_is_passed_through(self):
        results = [_result("a", ["1.2.3.0/24"])]
        data = lookup_data({"full": _v4("1.2.3.0/24"), "lite": []}, None, results, WHEN, ZzGeo())
        self.assertEqual(data["v4"]["full"][0][2], "ZZ")
        self.assertEqual(data["dbip_month"], "2026-10")

    def test_membership_on_collapsed_entry(self):
        results = [_result("a", ["1.2.3.0/25"]), _result("b", ["1.2.3.128/25"])]
        data = lookup_data({"full": _v4("1.2.3.0/24"), "lite": []}, None, results, WHEN, None)
        self.assertEqual(data["v4"]["full"], [["1.2.3.0/24", [0, 1], ""]])

    def test_membership_partial_overlap_after_allowlist(self):
        results = [_result("a", ["9.9.9.9/32"]), _result("b", ["10.0.0.0/8"])]
        data = lookup_data({"full": _v4("10.1.0.0/16"), "lite": []}, None, results, WHEN, None)
        self.assertEqual(data["v4"]["full"], [["10.1.0.0/16", [1], ""]])

    def test_membership_exact_and_non_adjacent(self):
        results = [_result("a", ["1.0.0.0/24", "3.0.0.0/24"]), _result("b", ["2.0.0.0/24"])]
        data = lookup_data({"full": _v4("1.0.0.0/24", "2.0.0.0/24", "3.0.0.0/24"),
                            "lite": []}, None, results, WHEN, None)
        self.assertEqual([e[1] for e in data["v4"]["full"]], [[0], [1], [0]])

    def test_errored_source_never_member(self):
        results = [_result("a", ["1.2.3.0/24"]), _result("b", ["1.2.3.0/24"], error="boom")]
        data = lookup_data({"full": _v4("1.2.3.0/24"), "lite": []}, None, results, WHEN, None)
        self.assertEqual(data["v4"]["full"][0][1], [0])
        self.assertEqual([s["ok"] for s in data["sources"]], [True, False])

    def test_lite_is_separate_list(self):
        results = [_result("a", ["1.2.3.0/24", "5.5.5.5/32"])]
        lite = _v4("1.2.3.0/25", "5.5.5.5/32")
        data = lookup_data({"full": _v4("1.2.3.0/24"), "lite": lite}, None, results, WHEN, None)
        self.assertEqual(data["v4"]["lite"], ["1.2.3.0/25", "5.5.5.5/32"])

    def test_ipv6_withheld(self):
        results = [_result("a", ["1.2.3.0/24", "2a0e::/32"])]
        data = lookup_data({"full": _v4("1.2.3.0/24"), "lite": []}, None, results, WHEN, None)
        self.assertIsNone(data["v6"])
        self.assertIs(data["ipv6_published"], False)

    def test_ipv6_published(self):
        results = [_result("a", ["2a0e::/32"]), _result("b", ["2a0e:1::/48"])]
        v6 = {"full": [IPv6Network("2a0e::/31")], "lite": [IPv6Network("2a0e::/32")]}
        data = lookup_data({"full": [], "lite": []}, v6, results, WHEN, FakeGeo())
        self.assertIs(data["ipv6_published"], True)
        self.assertEqual(data["v6"], {"full": [["2a0e::/31", [0, 1], "NL"]],
                                      "lite": ["2a0e::/32"]})
        self.assertEqual([(s["entries"], s["entries6"]) for s in data["sources"]],
                         [(0, 1), (0, 1)])

    def test_countries_and_month(self):
        results = [_result("a", ["1.2.3.0/24"])]
        variants = {"full": _v4("1.2.3.0/24"), "lite": []}
        data = lookup_data(variants, None, results, WHEN, FakeGeo())
        self.assertEqual(data["v4"]["full"][0][2], "DE")
        self.assertEqual(data["dbip_month"], "2026-10")
        data = lookup_data(variants, None, results, WHEN, None)
        self.assertEqual(data["v4"]["full"][0][2], "")
        self.assertIsNone(data["dbip_month"])

    def test_empty_geo_month_is_null(self):
        geo = FakeGeo()
        geo.month = ""
        data = lookup_data({"full": [], "lite": []}, None, [], WHEN, geo)
        self.assertIsNone(data["dbip_month"])

    def test_header_and_sources(self):
        results = [_result("spamhaus-drop", ["1.2.3.0/24"])]
        data = lookup_data({"full": _v4("1.2.3.0/24"), "lite": []}, None, results, WHEN, None)
        self.assertEqual(data["format"], 1)
        self.assertEqual(data["generated_at"], "2026-10-22T04:17:00Z")
        source = data["sources"][0]
        self.assertEqual(source["name"], "spamhaus-drop")
        self.assertEqual(source["category"], "attack")
        self.assertEqual(source["url"], "https://example.invalid/spamhaus-drop")
        self.assertEqual(source["license_note"], "spamhaus-drop terms")
        self.assertIn("Spamhaus", source["notice"])  # render.source_notice fallback
        self.assertEqual((source["entries"], source["entries6"], source["ok"]), (1, 0, True))

    def test_write_lookup_compact(self):
        data = lookup_data({"full": _v4("1.2.3.0/24"), "lite": []}, None,
                           [_result("a", ["1.2.3.0/24"])], WHEN, None)
        with tempfile.TemporaryDirectory() as tmp:
            write_lookup(Path(tmp) / "out", data)
            text = (Path(tmp) / "out" / "lookup.json").read_text(encoding="utf-8")
        self.assertNotIn(" ", text.replace("a terms", ""))
        self.assertEqual(json.loads(text), data)

    def test_size_budget(self):
        nets = [IPv4Network(f"{10 + i // 65536}.{i // 256 % 256}.{i % 256}.1/32")
                for i in range(40000)]
        results = [_result("a", [str(n) for n in nets[::2]]),
                   _result("b", [str(n) for n in nets[1::2]]),
                   _result("c", [str(n) for n in nets])]
        data = lookup_data({"full": nets, "lite": nets[:5000]}, None, results, WHEN, FakeGeo())
        self.assertTrue(all(len(e[1]) == 2 and e[2] == "DE" for e in data["v4"]["full"]))
        with tempfile.TemporaryDirectory() as tmp:
            write_lookup(Path(tmp), data)
            body = (Path(tmp) / "lookup.json").read_bytes()
        self.assertLessEqual(len(gzip.compress(body)), 3 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
