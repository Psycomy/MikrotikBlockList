"""End-to-end cases for routeros/install.rsc and uninstall.rsc on a real CHR.

Skipped unless MBL_E2E=1. By default boots a disposable CHR in QEMU (image
cached in MBL_E2E_CACHE, default <tmp>/mbl-e2e-cache). With
MBL_E2E_SSH=user@host[:port] (and optionally MBL_E2E_KEY) it uses that CHR by
SSH key instead; the HTTPS test server is then served on this host's LAN
address as seen from that router.

Existing-host mode is DESTRUCTIVE: it reinstalls MBL, reboots the router and
finally runs uninstall.rsc, so any previous MBL installation there is gone.
It therefore also requires MBL_E2E_DESTRUCTIVE=1; without it the class is
skipped. A best-effort uninstall also runs if a case aborts early.

The cases share one router and run in order (test_01 ... test_09).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from contextlib import suppress
from datetime import datetime, timezone
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path

from mbl.render import write_outputs
from tests.e2e.harness import Chr, ChrError, TlsServer, ensure_image

REPO = Path(__file__).resolve().parents[2]
ROUTEROS = REPO / "routeros"
DEFAULT_URL = "https://raw.githubusercontent.com/Psycomy/MikrotikBlockList/lists/blocklist.rsc"
TEST_CA_CN = "MBL Test CA"
LIST_SIZE = 5000
MIN_ENTRIES = 1000


def _synthetic_list(out_dir: Path) -> None:
    """5,000 consecutive global /32s from 45.0.0.0; no real sources."""
    first = int(IPv4Address("45.0.0.0"))
    networks = [IPv4Network(IPv4Address(first + i)) for i in range(LIST_SIZE)]
    write_outputs(out_dir, networks, [], datetime.now(timezone.utc))


def _local_ip_towards(host: str) -> str:
    out = subprocess.run(
        ["ip", "route", "get", host], capture_output=True, text=True, check=True,
    ).stdout
    m = re.search(r"\bsrc (\S+)", out)
    if not m:
        raise RuntimeError(f"cannot find the local address towards {host}: {out!r}")
    return m.group(1)


class RouterOsTest(unittest.TestCase):
    chr: Chr
    server: TlsServer
    base: str

    @classmethod
    def setUpClass(cls):
        if os.environ.get("MBL_E2E") != "1":
            raise unittest.SkipTest("set MBL_E2E=1 to run the CHR end-to-end tests")
        ssh = os.environ.get("MBL_E2E_SSH")
        if ssh and os.environ.get("MBL_E2E_DESTRUCTIVE") != "1":
            raise unittest.SkipTest(
                "MBL_E2E_SSH mode reinstalls, reboots and finally uninstalls MBL on "
                f"{ssh} (a previous MBL install there is lost); "
                "set MBL_E2E_DESTRUCTIVE=1 to allow it"
            )
        tmp = tempfile.TemporaryDirectory(prefix="mbl-e2e-")
        cls.addClassCleanup(tmp.cleanup)
        tmpdir = Path(tmp.name)

        served = tmpdir / "served"
        _synthetic_list(served)
        lines = (served / "blocklist.rsc").read_text().splitlines(keepends=True)
        assert lines[-2:] == [":global mblImportOk true\n", "# MBL-END\n"], lines[-2:]
        (served / "blocklist-truncated.rsc").write_text("".join(lines[:-2]))

        if ssh:
            key = os.environ.get("MBL_E2E_KEY")
            cls.chr = Chr.existing(ssh, Path(key).expanduser() if key else None)
            lan_ip = _local_ip_towards(cls.chr.host)
            cls.server = TlsServer(served, extra_ips=(lan_ip,))
            host = lan_ip
        else:
            cls.server = TlsServer(served)
            host = "10.0.2.2"
        cls.addClassCleanup(cls.server.stop)
        cls.server.start()
        cls.base = f"https://{host}:{cls.server.port}"

        if ssh:
            cls.chr.wait_ssh(30)
        else:
            version, sha256 = (REPO / "tests/e2e/chr-version.txt").read_text().split()
            cache = Path(os.environ.get("MBL_E2E_CACHE")
                         or Path(tempfile.gettempdir()) / "mbl-e2e-cache")
            image = ensure_image(version, sha256, cache)
            cls.chr = Chr.boot(image, tmpdir / "vm")
            cls.addClassCleanup(cls.chr.stop)

        cls.addClassCleanup(cls._remove_test_ca)
        cls._remove_test_ca()
        cls.chr.upload(cls.server.ca_pem, "ca.crt")
        cls.chr.run("/certificate import file-name=ca.crt trusted=yes passphrase=\"\"")
        cls.chr.run('/file remove [find where name="ca.crt"]')
        if ssh:
            # Never leave the user's router half-installed or pointing at the
            # (gone) test server if a case aborts early. Runs before the CA
            # removal and the server stop (cleanups are LIFO).
            cls.addClassCleanup(cls._best_effort_uninstall)

    @classmethod
    def _best_effort_uninstall(cls):
        with suppress(ChrError, OSError):
            cls.chr.upload(ROUTEROS / "uninstall.rsc", "uninstall.rsc")
            cls.chr.run("/import uninstall.rsc", timeout=300)
        with suppress(ChrError, OSError):
            cls.chr.run(':global mblUrlBase ""')

    @classmethod
    def _remove_test_ca(cls):
        cls.chr.run(f'/certificate remove [find where common-name="{TEST_CA_CN}"]')

    # -- helpers ------------------------------------------------------------

    def install(self, base: str | None) -> str:
        self.chr.upload(ROUTEROS / "install.rsc", "install.rsc")
        cmd = "/import install.rsc"
        if base is not None:
            cmd = f':global mblUrlBase "{base}"; ' + cmd
        return self.chr.run(cmd, timeout=600)

    def uninstall(self) -> str:
        self.chr.upload(ROUTEROS / "uninstall.rsc", "uninstall.rsc")
        return self.chr.run("/import uninstall.rsc", timeout=300)

    def update(self, boot: bool = False) -> None:
        cmd = "/system script run mbl-update"
        if boot:
            cmd = ":global mblBoot true; " + cmd
        self.chr.run(cmd, timeout=600)

    def put(self, expr: str) -> str:
        return self.chr.run(f":put ({expr})").strip()

    def active_list(self) -> str:
        return self.put('[/ip firewall raw get [find where comment="MBL: in"] src-address-list]')

    def count(self, list_: str) -> int:
        return int(self.put(f'[:len [/ip firewall address-list find where list="{list_}"]]'))

    def num(self, path: str, where: str) -> int:
        return int(self.put(f"[:len [{path} find where {where}]]"))

    def running(self) -> bool:
        return self.chr.run(":global mblRunning; :put $mblRunning").strip() == "true"

    def log(self) -> str:
        """MBL log lines as '<topics> <message>', oldest first."""
        return self.chr.run(
            ':foreach i in=[/log find where message~"MBL"] do={'
            ':put ([:tostr [/log get $i topics]] . " " . [/log get $i message])}'
        )

    def mark(self) -> str:
        token = f"MBLTEST mark {time.time_ns()}"
        self.chr.run(f':log info "{token}"')
        return token

    def log_after(self, token: str) -> str:
        """Log lines after `token`; the whole log if the token is gone (reboot)."""
        text = self.log()
        i = text.find(token)
        return text if i < 0 else text[i + len(token):]

    def set_update_path(self, old: str, new: str) -> None:
        """Replace `old` with `new` in mbl-update's source, on the router."""
        self.chr.run(
            '{:local s [/system script get [find where name="mbl-update"] source];'
            f':local o "{old}"; :local p [:find $s $o];'
            ':if ([:typeof $p] = "nil") do={:error "MBLTEST: path not found"};'
            '/system script set [find where name="mbl-update"] '
            f'source=([:pick $s 0 $p] . "{new}" . [:pick $s ($p + [:len $o]) [:len $s]])}}'
        )

    def update_source(self) -> str:
        return self.chr.run(':put [/system script get [find where name="mbl-update"] source]')

    def assert_failed_update_keeps_active(self, path: str, error: str) -> None:
        """mbl-update requests `path`, fails with an `error` log line, keeps the list."""
        active, n = self.active_list(), self.count(self.active_list())
        token = self.mark()
        self.server.requests.clear()
        self.update()
        self.assertEqual(self.active_list(), active)
        self.assertEqual(self.count(active), n)
        self.assertIn(path, self.server.requests)
        log = self.log_after(token)
        errors = [ln for ln in log.splitlines()
                  if "error" in ln.split(" ", 1)[0] and "MBL:" in ln]
        self.assertTrue(any(error in ln for ln in errors), log)

    # -- cases --------------------------------------------------------------

    def test_01_clean_install(self):
        out = self.install(self.base)
        self.assertEqual(self.num("/ip firewall raw", 'comment~"^MBL:"'), 6, out)
        for name in ("mbl-daily", "mbl-boot"):
            self.assertEqual(self.num("/system scheduler", f'name="{name}"'), 1, name)
        self.assertGreaterEqual(self.count(self.active_list()), MIN_ENTRIES)
        self.assertIn("MBL: installed", self.log())

    def test_02_update_alternates(self):
        old = self.active_list()
        self.update()
        new = self.active_list()
        self.assertEqual({old, new}, {"mbl-a", "mbl-b"})
        self.assertEqual(self.count(old), 0)
        self.assertGreaterEqual(self.count(new), MIN_ENTRIES)

    def test_03_truncated_keeps_active(self):
        try:
            self.set_update_path("/blocklist.rsc", "/blocklist-truncated.rsc")
            self.assertIn("/blocklist-truncated.rsc", self.update_source())
            # the footer (mblImportOk) is missing: the import is rejected
            self.assert_failed_update_keeps_active(
                "/blocklist-truncated.rsc", "MBL: import of mbl-new.rsc failed (complete=false")
        except BaseException:
            # restore on a best-effort basis without masking the real error
            with suppress(ChrError):
                self.set_update_path("/blocklist-truncated.rsc", "/blocklist.rsc")
            raise
        self.set_update_path("/blocklist-truncated.rsc", "/blocklist.rsc")
        self.assertIn(f"{self.base}/blocklist.rsc", self.update_source())

    def test_04_dead_url_keeps_active(self):
        self.server.fail_paths = {"/blocklist.rsc"}
        try:
            self.assert_failed_update_keeps_active("/blocklist.rsc", "MBL: download failed (")
        finally:
            self.server.fail_paths = set()

    def test_05_reboot_reloads(self):
        token = self.mark()
        self.chr.reboot()
        deadline = time.monotonic() + 150
        while "MBL: loaded" not in self.log_after(token):
            self.assertLess(time.monotonic(), deadline,
                            f"no 'MBL: loaded' after reboot: {self.log_after(token)}")
            time.sleep(3)
        self.assertGreaterEqual(self.count(self.active_list()), MIN_ENTRIES)
        # mbl-boot runs a second (download) update 60 s after boot; let it
        # finish so it does not hold the lock during the next case.
        deadline = time.monotonic() + 180
        while self.log_after(token).count("MBL: loaded") < 2 or self.running():
            self.assertLess(time.monotonic(), deadline,
                            f"boot download update did not finish: {self.log_after(token)}")
            time.sleep(3)

    def test_06_flash_path(self):
        if self.num("/file", 'name="flash"') > 0:
            # never touch a real flash/ (it would be removed at the end)
            self.skipTest("a flash directory already exists on this router")
        self.chr.run("/file add type=directory name=flash")
        try:
            self.update()
            self.assertEqual(self.num("/file", 'name="flash/mbl-last.rsc"'), 1,
                             self.chr.run("/file print"))
            before = self.active_list()
            token = self.mark()
            self.update(boot=True)
            after = self.log_after(token)
            self.assertIn("MBL: loaded", after)
            self.assertNotIn("boot: no", after)
            self.assertNotEqual(self.active_list(), before)
            self.assertGreaterEqual(self.count(self.active_list()), MIN_ENTRIES)
        finally:
            self.chr.run('/file remove [find where name~"^flash/"]')
            self.chr.run('/file remove [find where name="flash"]')
        self.assertEqual(self.num("/file", 'name~"^flash"'), 0)

    def test_07_reinstall_no_duplicates(self):
        admin = 'list="mbl-allow" and comment="MBL: admin"'
        admins = self.num("/ip firewall address-list", admin)
        self.assertGreaterEqual(admins, 1)
        self.install(self.base)
        self.assertEqual(self.num("/ip firewall raw", 'comment~"^MBL:"'), 6)
        self.assertEqual(self.num("/system scheduler", 'name~"^mbl-"'), 2)
        self.assertEqual(self.num("/ip firewall address-list", admin), admins)
        self.assertGreaterEqual(self.count(self.active_list()), MIN_ENTRIES)

    def test_08_uninstall_clean(self):
        lists = 'name="WAN" or name="LAN"'
        members = 'list="WAN" or list="LAN"'
        n_lists = self.num("/interface list", lists)
        n_members = self.num("/interface list member", members)
        self.uninstall()
        self.assertEqual(self.num("/ip firewall raw", 'comment~"^MBL:"'), 0)
        self.assertEqual(self.num("/system script", 'name~"^mbl-"'), 0)
        self.assertEqual(self.num("/system scheduler", 'name~"^mbl-"'), 0)
        self.assertEqual(self.count("mbl-a"), 0)
        self.assertEqual(self.count("mbl-b"), 0)
        self.assertEqual(self.num("/file", 'name~"mbl-.*\\\\.rsc"'), 0,
                         self.chr.run("/file print"))
        self.assertEqual(self.num("/interface list", lists), 2)
        self.assertEqual(self.num("/interface list", lists), n_lists)
        self.assertEqual(self.num("/interface list member", members), n_members)

    def test_09_default_url_without_override(self):
        try:
            self.chr.run(':global mblUrlBase ""')
            self.install(None)
            self.assertIn(DEFAULT_URL, self.update_source())
        finally:
            self.uninstall()


if __name__ == "__main__":
    unittest.main()
