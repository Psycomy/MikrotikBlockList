import random
import unittest
from ipaddress import IPv4Network, ip_network

from mbl.normalize import normalize


def nets(*items):
    return [ip_network(i) for i in items]


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


if __name__ == "__main__":
    unittest.main()
