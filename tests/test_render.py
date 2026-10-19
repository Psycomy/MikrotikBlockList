import json
import re
import tempfile
import unittest
from datetime import datetime, timezone
from ipaddress import IPv4Network
from pathlib import Path

from mbl.fetch import SourceResult
from mbl.render import write_outputs
from mbl.sources import Source

ADD_RE = re.compile(r"^add list=\$mblTarget timeout=7d address=\d+\.\d+\.\d+\.\d+(/\d+)?$")
WHEN = datetime(2026, 10, 19, 4, 17, 0, tzinfo=timezone.utc)


def _results(nets):
    src = Source("spamhaus-drop", "https://x", "plain", "attack", required=True)
    return [SourceResult(src, list(nets), 2, None)]


class RenderTest(unittest.TestCase):
    def _write(self, nets, tmp):
        write_outputs(Path(tmp) / "out", nets, _results(nets), WHEN)
        return Path(tmp) / "out"

    def test_rsc_structure(self):
        nets = [IPv4Network("1.10.16.0/20"), IPv4Network("8.8.8.8/32")]
        with tempfile.TemporaryDirectory() as tmp:
            out = self._write(nets, tmp)
            text = (out / "blocklist.rsc").read_text()
            txt = (out / "blocklist.txt").read_text()
        self.assertTrue(text.endswith("# MBL-END\n"))
        lines = text.splitlines()
        self.assertTrue(lines[0].startswith("# MikrotikBlockList v2"))
        self.assertEqual(lines[-2:], [":global mblImportOk true", "# MBL-END"])
        self.assertIn("# generated: 2026-10-19T04:17:00Z entries: 2", lines)
        start = lines.index("/ip firewall address-list")
        body = lines[start + 1 : -2]
        self.assertEqual(len(body), 2)
        for line in body:
            self.assertRegex(line, ADD_RE)
        self.assertIn("address=8.8.8.8", body[1])
        self.assertNotIn("/32", text)
        self.assertEqual(txt, "1.10.16.0/20\n8.8.8.8\n")

    def test_rsc_contains_only_expected_commands(self):
        nets = [IPv4Network("1.10.16.0/20")]
        with tempfile.TemporaryDirectory() as tmp:
            text = (self._write(nets, tmp) / "blocklist.rsc").read_text()
        others = [l for l in text.splitlines() if not l.startswith("add ")]
        self.assertEqual(
            others,
            [
                "# MikrotikBlockList v2 - https://github.com/Psycomy/MikrotikBlockList",
                "# For home / non-commercial use only (see source licenses in README)",
                "# generated: 2026-10-19T04:17:00Z entries: 1",
                "# Sources and terms: https://github.com/Psycomy/MikrotikBlockList/blob/lists/NOTICE.md",
                ":global mblTarget",
                "/ip firewall address-list",
                ":global mblImportOk true",
                "# MBL-END",
            ],
        )

    def test_stats_and_badges(self):
        nets = [IPv4Network(f"10.{i // 256}.{i % 256}.0/24") for i in range(61234)]
        with tempfile.TemporaryDirectory() as tmp:
            out = self._write(nets, tmp)
            stats = json.loads((out / "stats.json").read_text())
            entries = json.loads((out / "badge-entries.json").read_text())
            updated = json.loads((out / "badge-updated.json").read_text())
        self.assertEqual(stats["total"], 61234)
        self.assertEqual(stats["generated_at"], "2026-10-19T04:17:00Z")
        self.assertEqual(
            stats["sources"]["spamhaus-drop"],
            {"category": "attack", "entries": 61234, "invalid": 2, "error": None},
        )
        self.assertEqual(
            entries,
            {"schemaVersion": 1, "label": "entries", "message": "61,234", "color": "blue"},
        )
        self.assertEqual(
            updated,
            {"schemaVersion": 1, "label": "updated", "message": "2026-10-19", "color": "brightgreen"},
        )

    def test_notice(self):
        ok = Source("spamhaus-drop", "https://www.spamhaus.org/drop/drop.txt", "plain",
                    "attack", required=True, license_note="Spamhaus DROP terms")
        bad = Source("dshield", "https://www.dshield.org/block.txt", "dshield",
                     "attack", license_note="CC BY-NC-SA")
        nets = [IPv4Network("1.10.16.0/20"), IPv4Network("8.8.8.8/32")]
        results = [SourceResult(ok, nets, 0, None),
                   SourceResult(bad, [], 0, "HTTPError: HTTP Error 503: down")]
        with tempfile.TemporaryDirectory() as tmp:
            write_outputs(Path(tmp), nets, results, WHEN)
            notice = (Path(tmp) / "NOTICE.md").read_text()
        self.assertIn("MikrotikBlockList", notice)
        self.assertIn("https://github.com/Psycomy/MikrotikBlockList", notice)
        self.assertIn("For home / non-commercial use only", notice)
        self.assertIn("third-party sources", notice)
        self.assertIn("GPL-3.0", notice)
        self.assertIn("2026-10-19T04:17:00Z", notice)
        rows = [l for l in notice.splitlines() if l.startswith("| ")]
        self.assertEqual(rows[0], "| source | url | category | license / terms | entries | error |")
        self.assertIn("| spamhaus-drop | https://www.spamhaus.org/drop/drop.txt | attack "
                      "| Spamhaus DROP terms | 2 |  |", rows)
        self.assertIn("| dshield | https://www.dshield.org/block.txt | attack | CC BY-NC-SA "
                      "| 0 | HTTPError: HTTP Error 503: down |", rows)

    def test_notice_escapes_pipes(self):
        src = Source("s", "https://x", "plain", "attack", license_note="a | b")
        with tempfile.TemporaryDirectory() as tmp:
            write_outputs(Path(tmp), [], [SourceResult(src, [], 0, "x|y")], WHEN)
            notice = (Path(tmp) / "NOTICE.md").read_text()
        self.assertIn("| s | https://x | attack | a \\| b | 0 | x\\|y |", notice)


if __name__ == "__main__":
    unittest.main()
