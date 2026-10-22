import unittest
from ipaddress import IPv4Network, ip_network
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
            result.networks,
            [*_nets("1.1.1.1/32", "2.2.2.2/32", "1.2.3.0/24", "3.3.3.3/32"), ip_network("::1/128")],
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

    def test_plain_accepts_ipv6(self):
        result = parse("plain", "2001:db8::1\n2a00:1450::/32\n1.2.3.4\n")
        self.assertEqual(
            result.networks,
            [ip_network("2001:db8::1/128"), ip_network("2a00:1450::/32"), ip_network("1.2.3.4/32")],
        )
        self.assertEqual(result.invalid, 0)

    def test_threatfox_ipv6_in_brackets(self):
        text = '"t", "1", "[2a00::1]:443", "ip:port", "botnet_cc"\n"t", "2", "1.2.3.4:80", "ip:port", "x"\n'
        result = parse("threatfox_csv", text)
        self.assertEqual(result.networks, [ip_network("2a00::1/128"), ip_network("1.2.3.4/32")])
        self.assertEqual(result.invalid, 0)

    def test_jsonl_cidr(self):
        result = parse("jsonl_cidr", _fixture("spamhaus_v6.jsonl"))
        self.assertEqual(
            result.networks,
            [ip_network("2001:678:254::/48"), ip_network("2a0b:7080::/32"), ip_network("2602:fed2:1000::/36")],
        )
        self.assertEqual(result.invalid, 0)

    def test_jsonl_cidr_bad_lines_invalid(self):
        result = parse("jsonl_cidr", 'not json\n{"cidr":"zzz"}\n{"cidr":"2a00::/32"}\n')
        self.assertEqual(result.networks, [ip_network("2a00::/32")])
        self.assertEqual(result.invalid, 2)

    def test_html_page_yields_nothing(self):
        result = parse("plain", "<html><body>Just a moment...</body></html>")
        self.assertEqual(result.networks, [])

    def test_unknown_format(self):
        with self.assertRaises(ValueError):
            parse("nope", "1.2.3.4")

    def test_plain_keeps_copyright_notice(self):
        text = ("; Spamhaus DROP List 2026/10/22 - (c) 2026 The Spamhaus Project SLU\n"
                "; https://x\n; Last-Modified: Wed, 21 Oct 2026 14:04:29 GMT\n"
                "1.10.16.0/20 ; SBL1\n")
        self.assertEqual(
            parse("plain", text).notice,
            "Spamhaus DROP List 2026/10/22 - (c) 2026 The Spamhaus Project SLU; "
            "Last-Modified: Wed, 21 Oct 2026 14:04:29 GMT")

    def test_plain_without_copyright_has_empty_notice(self):
        self.assertEqual(parse("plain", "1.1.1.1\n").notice, "")

    def test_jsonl_keeps_metadata_notice(self):
        text = ('{"cidr":"1.10.16.0/20"}\n'
                '{"type":"metadata","timestamp":1792673042,'
                '"copyright":"(c) 2026 The Spamhaus Project SLU"}\n')
        self.assertEqual(parse("jsonl_cidr", text).notice,
                         "(c) 2026 The Spamhaus Project SLU; timestamp 2026-10-22T12:44:02Z")


if __name__ == "__main__":
    unittest.main()
