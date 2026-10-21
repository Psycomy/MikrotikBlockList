import random
import unittest
from ipaddress import IPv4Network, ip_network

from mbl.normalize import normalize, normalize6


def nets(*items):
    return [ip_network(i) for i in items]


class Normalize6Tests(unittest.TestCase):
    def test_drops_non_global(self):
        src = nets(
            "2001:db8::/32", "fe80::1/128", "fc00::1/128", "ff02::1/128", "::ffff:1.2.3.4/128",
            "2002::/16", "2001::/32", "::/0", "64:ff9b::1/128", "fd00::/8", "::1/128",
        )
        self.assertEqual(normalize6(src, []), [])

    def test_drops_wider_than_slash19(self):
        self.assertEqual(normalize6(nets("2a00::/16", "2a00::/18"), []), [])
        self.assertEqual(normalize6(nets("2a00::/19"), []), nets("2a00::/19"))
        self.assertEqual(normalize6(nets("2a00::/16"), [], min_prefixlen=16), nets("2a00::/16"))

    def test_keeps_global_host(self):
        self.assertEqual(normalize6(nets("2a00:1450::1/128"), []), nets("2a00:1450::1/128"))

    def test_allowlist_subtracts_and_aggregates(self):
        out = normalize6(nets("2606:4700::/32", "2a00::/32", "2a00:1::/32"), nets("2606:4700::/33"))
        self.assertEqual(out, sorted(nets("2606:4700:8000::/33", "2a00::/31")))
        self.assertTrue(all(n.version == 6 for n in out))

    def test_allowlist_covering_removes_all(self):
        self.assertEqual(normalize6(nets("2606:4700:1::/48"), nets("2606:4700::/32")), [])

    def test_ignores_ipv4_networks_and_allowlist(self):
        out = normalize6(nets("1.2.3.0/24", "2a00::/32"), nets("1.2.3.0/24", "2a00::/33"))
        self.assertEqual(out, nets("2a00:0:8000::/33"))

    def test_sorted_and_deduplicated(self):
        out = normalize6(nets("2b00::1/128", "2a00::1/128", "2a00::1/128"), [])
        self.assertEqual(out, nets("2a00::1/128", "2b00::1/128"))


class NormalizeTests(unittest.TestCase):
    def test_drops_private_cgnat_bogons(self):
        src = nets(
            "10.0.0.0/8", "192.168.1.0/24", "100.64.0.0/10", "127.0.0.1/32",
            "0.0.0.0/8", "224.0.0.0/3", "169.254.0.0/16", "172.16.0.0/12",
            "198.18.0.0/15",
        )
        self.assertEqual(normalize(src, []), [])

    def test_drops_wider_than_slash8(self):
        self.assertEqual(normalize(nets("0.0.0.0/0", "16.0.0.0/4", "8.0.0.0/7"), []), [])
        self.assertEqual(normalize(nets("8.0.0.0/8"), []), nets("8.0.0.0/8"))

    def test_drops_overlapping_non_global(self):
        self.assertEqual(normalize(nets("100.0.0.0/8"), []), [])

    def test_allowlist_excludes(self):
        out = normalize(nets("1.1.1.0/24"), nets("1.1.1.1/32"))
        self.assertEqual(len(out), 8)
        self.assertTrue(all(not n.supernet_of(ip_network("1.1.1.1/32")) for n in out))
        self.assertEqual(sum(n.num_addresses for n in out), 255)

    def test_allowlist_larger_than_network_and_multiple_entries(self):
        out = normalize(nets("1.1.1.0/24", "2.2.2.0/24"), nets("1.0.0.0/8", "2.2.2.0/25", "2.2.2.200/32"))
        self.assertEqual(sum(n.num_addresses for n in out), 127)
        self.assertTrue(all(n.network_address.packed[0] == 2 for n in out))

    def test_collapse_and_sort(self):
        out = normalize(nets("5.5.5.1/32", "1.2.3.0/25", "1.2.3.128/25", "5.5.5.1/32"), [])
        self.assertEqual(out, nets("1.2.3.0/24", "5.5.5.1/32"))

    def test_deterministic(self):
        src = nets("5.5.5.1/32", "1.2.3.0/25", "1.2.3.128/25", "9.9.9.0/24", "4.4.4.4/32")
        a = list(src)
        b = list(src)
        random.Random(1).shuffle(a)
        random.Random(2).shuffle(b)
        self.assertEqual(normalize(a, []), normalize(b, []))
        self.assertIsInstance(normalize(a, [])[0], IPv4Network)

    def test_ignores_ipv6_networks_and_allowlist(self):
        out = normalize(nets("1.1.1.0/24", "2a00::/32"), nets("2a00::/32", "1.1.1.1/32"))
        self.assertTrue(all(n.version == 4 for n in out))
        self.assertEqual(len(out), 8)


if __name__ == "__main__":
    unittest.main()
