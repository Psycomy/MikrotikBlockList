import unittest
from ipaddress import IPv4Network
from pathlib import Path

from mbl.parsers import ParseResult, parse

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _nets(*cidrs: str) -> list[IPv4Network]:
    return [IPv4Network(c) for c in cidrs]


class ParserTests(unittest.TestCase):
    def test_plain_spamhaus(self):
        result = parse("plain", _fixture("plain_spamhaus.txt"))
        self.assertIsInstance(result, ParseResult)
        self.assertEqual(
            result.networks,
            _nets(
                "1.10.16.0/20",
                "1.19.0.0/16",
                "1.32.128.0/18",
                "2.26.75.0/24",
                "2.27.5.0/24",
                "2.27.62.0/24",
            ),
        )
        self.assertEqual(result.invalid, 0)

    def test_plain_ipsum(self):
        result = parse("plain", _fixture("plain_ipsum.txt"))
        self.assertEqual(len(result.networks), 10)
        self.assertTrue(all(n.prefixlen == 32 for n in result.networks))
        self.assertEqual(result.invalid, 0)

    def test_plain_edge_cases(self):
        text = "﻿1.1.1.1\r\n  2.2.2.2  \n1.2.3.4/24\n010.1.1.1\nfoo\n3.3.3.3 # c\n::1\n"
        result = parse("plain", text)
        self.assertEqual(
            result.networks, _nets("1.1.1.1/32", "2.2.2.2/32", "1.2.3.0/24", "3.3.3.3/32")
        )
        self.assertEqual(result.invalid, 2)

    def test_dshield(self):
        result = parse("dshield", "64.62.156.0\t64.62.156.255\t24\t345\tHURRICANE")
        self.assertEqual(result.networks, _nets("64.62.156.0/24"))
        self.assertEqual(result.invalid, 0)

    def test_dshield_fixture_and_header(self):
        result = parse("dshield", "Start\tEnd\tNetblock\tAttacks\n" + _fixture("dshield.txt"))
        self.assertEqual(len(result.networks), 6)
        self.assertTrue(all(n.prefixlen == 24 for n in result.networks))
        self.assertEqual(result.invalid, 0)

    def test_threatfox_csv(self):
        result = parse("threatfox_csv", _fixture("threatfox.csv"))
        self.assertEqual(len(result.networks), 7)
        self.assertTrue(all(n.prefixlen == 32 for n in result.networks))
        self.assertIn(IPv4Network("96.62.71.6/32"), result.networks)
        self.assertEqual(result.invalid, 0)

    def test_c2intel_csv(self):
        result = parse("c2intel_csv", _fixture("c2intel.csv"))
        self.assertEqual(len(result.networks), 9)
        self.assertTrue(all(n.prefixlen == 32 for n in result.networks))
        self.assertIn(IPv4Network("1.117.74.144/32"), result.networks)
        self.assertEqual(result.invalid, 0)

    def test_c2intel_plain_header_not_invalid(self):
        result = parse("c2intel_csv", "ip,ioc\n1.2.3.4,x\n")
        self.assertEqual(result.networks, _nets("1.2.3.4/32"))
        self.assertEqual(result.invalid, 0)

    def test_csv_first_column_turris(self):
        result = parse("csv", _fixture("turris.csv"))
        self.assertEqual(len(result.networks), 6)
        self.assertIn(IPv4Network("89.37.172.132/32"), result.networks)
        self.assertEqual(result.invalid, 0)

    def test_html_page_yields_nothing(self):
        result = parse("plain", "<html><body>Just a moment...</body></html>")
        self.assertEqual(result.networks, [])

    def test_unknown_format(self):
        with self.assertRaises(ValueError):
            parse("nope", "1.2.3.4")


if __name__ == "__main__":
    unittest.main()
