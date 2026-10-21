"""End-to-end cases for routeros/install.rsc and uninstall.rsc on a real CHR.

Skipped unless MBL_E2E=1. By default boots a disposable CHR in QEMU (image
cached in MBL_E2E_CACHE, default <tmp>/mbl-e2e-cache). With
MBL_E2E_SSH=user@host[:port] (and optionally MBL_E2E_KEY) it uses that CHR by
SSH key instead; the HTTPS test server is then served on this host's LAN
address as seen from that router.

Existing-host mode is DESTRUCTIVE: it reinstalls MBL, reboots the router and
finally runs uninstall.rsc, so any previous MBL installation there is gone.
It therefore also requires MBL_E2E_DESTRUCTIVE=1; without it the class is
skipped. A best-effort uninstall also runs if a case aborts early or the run
is interrupted (atexit); after a run killed outright, run uninstall.rsc by hand.

Other environment variables: MBL_E2E_CHR_VERSION / MBL_E2E_CHR_SHA256 override the
pinned tests/e2e/chr-version.txt (an empty SHA256 skips the checksum), and
MBL_E2E_ARTIFACTS=<dir> receives console.log and qemu.log (written there while
the VM runs, so they survive a killed run) and router-log.txt (the router's
/log print, when the run ends), for CI failure artifacts.

The cases share one router and run in order (test_01 ... test_15).
"""
from __future__ import annotations

import atexit
import os
import re
import subprocess
import tempfile
import threading
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
DEFAULT_HOST = "raw.githubusercontent.com"
DEFAULT_URL = f"https://{DEFAULT_HOST}/Psycomy/MikrotikBlockList/lists/routeros-full.txt"
UNREACHABLE = "192.0.2.1"  # TEST-NET-1 (RFC 5737)
DNS_COMMENT = "MBLTEST"
TEST_CA_CN = "MBL Test CA"
# routeros-full.txt must reach mbl-update's 100,000-byte minimum size:
# 10,000 entries from 45.0.0.0 are ~113 KB (5,000 would be ~55 KB).
LIST_SIZE = 10000
MIN_ENTRIES = 1000
# Lines that must never run on the router: they are only data, counted as invalid.
# 12 lines, under the 1 % budget (100 with LIST_SIZE entries).
MALICIOUS = [
    "/system reboot",
    "/ip firewall address-list add list=mbl-pwned address=1.1.1.1",
    "1.2.3.4; /ip firewall address-list add list=mbl-pwned address=1.1.1.2",
    "$([/ip firewall address-list add list=mbl-pwned address=1.1.1.3])",
    "[/ip firewall address-list add list=mbl-pwned address=1.1.1.4]",
    ':execute "/ip firewall address-list add list=mbl-pwned address=1.1.1.5"',
    "999.1.1.1",
    "1.2.3.0/40",
    "1.2.3.0/4",
    "abc",
    "",
    "9" * 100_000,  # over-long line: spans several 32 KiB chunks
]


def _synthetic_list(out_dir: Path) -> None:
    """LIST_SIZE consecutive global /32s from 45.0.0.0; no real sources."""
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
        lines = (served / "routeros-full.txt").read_text().splitlines(keepends=True)
        assert lines[-1] == f"# MBL-END entries={LIST_SIZE}\n", lines[-1]
        (served / "routeros-full-truncated.txt").write_text("".join(lines[:-1]))
        header, body, footer = lines[0], [ln.rstrip("\n") for ln in lines[1:-1]], lines[-1]
        assert len(body) == LIST_SIZE
        nl = "\n"

        def variant(name: str, head: str, entries: list[str], foot: str, eol: str = nl) -> None:
            text = eol.join([head.rstrip("\n"), *entries, foot.rstrip("\n")]) + eol
            (served / name).write_bytes(text.encode())

        variant("routeros-full-injected.txt", header, body + MALICIOUS, footer)
        wrong = LIST_SIZE + 100
        variant("routeros-full-mismatch.txt",
                header.replace(f"entries={LIST_SIZE}", f"entries={wrong}"), body,
                footer.replace(f"entries={LIST_SIZE}", f"entries={wrong}"))
        variant("routeros-full-crlf.txt", header,
                [ln + (" " if i < 10 else "") for i, ln in enumerate(body)], footer, "\r\n")
        variant("routeros-full-invalid.txt", header,
                body + [f"bad-line-{i}" for i in range(LIST_SIZE // 50)], footer)

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
            if os.environ.get("MBL_E2E_CHR_VERSION"):
                version = os.environ["MBL_E2E_CHR_VERSION"]
                sha256 = os.environ.get("MBL_E2E_CHR_SHA256") or None
            cache = Path(os.environ.get("MBL_E2E_CACHE")
                         or Path(tempfile.gettempdir()) / "mbl-e2e-cache")
            image = ensure_image(version, sha256, cache)
            cls.chr = Chr.boot(image, tmpdir / "vm", log_dir=cls._artifacts())
            cls.addClassCleanup(cls.chr.stop)
        cls.addClassCleanup(cls._save_router_log)

        cls.addClassCleanup(cls._remove_test_ca)
        cls._remove_test_ca()
        cls.chr.upload(cls.server.ca_pem, "ca.crt")
        cls.chr.run("/certificate import file-name=ca.crt trusted=yes passphrase=\"\"")
        cls.chr.run('/file remove [find where name="ca.crt"]')
        if ssh:
            # Never leave the user's router half-installed or pointing at the
            # (gone) test server if a case aborts early. Runs before the CA
            # removal and the server stop (cleanups are LIFO); atexit covers
            # an interrupted run (Ctrl-C) that skips the class cleanups.
            cls._uninstalled = False
            cls.addClassCleanup(cls._best_effort_uninstall)
            atexit.register(cls._best_effort_uninstall)

    @classmethod
    def _best_effort_uninstall(cls):
        if cls._uninstalled:
            return
        cls._uninstalled = True
        with suppress(ChrError, OSError):
            cls.chr.upload(ROUTEROS / "uninstall.rsc", "uninstall.rsc")
            cls.chr.run("/import uninstall.rsc", timeout=300)
        with suppress(ChrError, OSError):
            cls.chr.run(':global mblUrlBase ""')

    @classmethod
    def _artifacts(cls) -> Path | None:
        d = os.environ.get("MBL_E2E_ARTIFACTS")
        if not d:
            return None
        Path(d).mkdir(parents=True, exist_ok=True)
        return Path(d)

    @classmethod
    def _save_router_log(cls):
        out = cls._artifacts()
        if out is not None:
            with suppress(ChrError, OSError):
                (out / "router-log.txt").write_text(cls.chr.run("/log print", timeout=60))

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

    def serve_variant(self, name: str) -> None:
        self.set_update_path("/routeros-full.txt", f"/{name}")

    def restore_path(self, name: str) -> None:
        # no assertions: this runs in `finally` and must not mask the real failure
        self.set_update_path(f"/{name}", "/routeros-full.txt")

    def sample_protection(self) -> str:
        """'<list the MBL: in rule points to> <its entries>', or 'none 0' without the rule."""
        return self.chr.run(
            '{:local r [/ip firewall raw find where comment="MBL: in"];'
            ':if ([:len $r] = 0) do={:put "none 0"} else={'
            ':local l [/ip firewall raw get ($r->0) src-address-list];'
            ':put ($l . " " . [:len [/ip firewall address-list find where list=$l]])}}'
        ).strip()

    # -- cases --------------------------------------------------------------

    def test_01_clean_install(self):
        out = self.install(self.base)
        self.assertEqual(self.num("/ip firewall raw", 'comment~"^MBL:"'), 6, out)
        for name in ("mbl-daily", "mbl-boot"):
            self.assertEqual(self.num("/system scheduler", f'name="{name}"'), 1, name)
        # every line is loaded, including those cut between two /file read chunks
        self.assertEqual(self.count(self.active_list()), LIST_SIZE)
        log = self.log()
        self.assertIn("MBL: installed", log)
        warning = f"MBL: using test URL base {self.base}"
        self.assertTrue(any(warning in ln and "warning" in ln.split(" ", 1)[0]
                            for ln in log.splitlines()), log)
        self.assertIn(warning, out)

    def test_02_update_alternates(self):
        old = self.active_list()
        self.update()
        new = self.active_list()
        self.assertEqual({old, new}, {"mbl-a", "mbl-b"})
        self.assertEqual(self.count(old), 0)
        self.assertEqual(self.count(new), LIST_SIZE)

    def test_03_truncated_keeps_active(self):
        try:
            self.set_update_path("/routeros-full.txt", "/routeros-full-truncated.txt")
            self.assertIn("/routeros-full-truncated.txt", self.update_source())
            # the footer is missing: the file is rejected
            self.assert_failed_update_keeps_active(
                "/routeros-full-truncated.txt", "MBL: mbl-new.txt rejected (no footer)")
        except BaseException:
            # restore on a best-effort basis without masking the real error
            with suppress(ChrError):
                self.set_update_path("/routeros-full-truncated.txt", "/routeros-full.txt")
            raise
        self.set_update_path("/routeros-full-truncated.txt", "/routeros-full.txt")
        self.assertIn(f"{self.base}/routeros-full.txt", self.update_source())

    def test_04_dead_url_keeps_active(self):
        self.server.fail_paths = {"/routeros-full.txt"}
        try:
            self.assert_failed_update_keeps_active("/routeros-full.txt", "MBL: download failed (")
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
            self.assertEqual(self.num("/file", 'name="flash/mbl-last.txt"'), 1,
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
        self.assertEqual(self.num("/file", 'name~"mbl-.*\\\\.(rsc|txt)"'), 0,
                         self.chr.run("/file print"))
        self.assertEqual(self.num("/interface list", lists), 2)
        self.assertEqual(self.num("/interface list", lists), n_lists)
        self.assertEqual(self.num("/interface list member", members), n_members)

    def test_09_default_url_without_override(self):
        # No internet needed: the default host resolves to an unreachable
        # address, so the first load fails (fetch timeout, ~10 s) and only
        # the URL is checked.
        dns = f'/ip dns static remove [find where comment="{DNS_COMMENT}"]'
        try:
            self.chr.run(f'/ip dns static add name={DEFAULT_HOST} '
                         f'address={UNREACHABLE} comment="{DNS_COMMENT}"')
            self.chr.run("/ip dns cache flush")
            self.chr.run(':global mblUrlBase ""')
            self.install(None)
            self.assertIn(DEFAULT_URL, self.update_source())
        finally:
            try:
                self.uninstall()
            finally:
                self.chr.run(dns)

    def test_10_upgrade_from_v2(self):
        v2 = subprocess.run(["git", "show", "v2.0.0:routeros/install.rsc"], cwd=REPO,
                            capture_output=True, check=True).stdout
        self.uninstall()
        with tempfile.TemporaryDirectory(prefix="mbl-v2-") as d:
            f = Path(d) / "install.rsc"
            f.write_bytes(v2)
            self.chr.upload(f, "install.rsc")
        self.chr.run(f':global mblUrlBase "{self.base}"; /import install.rsc', timeout=600)
        self.assertEqual(self.num("/file", 'name="mbl-last.rsc"'), 1, self.chr.run("/file print"))
        before = self.count(self.active_list())
        self.assertGreaterEqual(before, MIN_ENTRIES)
        v2_list = self.active_list()
        rsc = 'name~"^mbl-.*\\\\.rsc"'
        self.assertEqual(self.num("/file", rsc), 1, self.chr.run("/file print"))  # pattern control
        token = self.mark()
        samples: list[str] = []
        stop = threading.Event()

        def poll():
            while not stop.is_set():
                try:
                    samples.append(self.sample_protection())
                except ChrError as e:
                    samples.append(f"error {e}")
                stop.wait(0.5)

        poller = threading.Thread(target=poll, daemon=True)
        poller.start()
        try:
            self.install(self.base)
        finally:
            stop.set()
            poller.join(30)
        samples.append(self.sample_protection())
        self.assertGreaterEqual(len(samples), 3, samples)
        # every sample sees a populated list. The installer removes and recreates
        # the rules, so a single sample without the rule is tolerated, no more.
        prev_none = False
        for smp in samples:
            name, _, n = smp.partition(" ")
            if name == "none":
                self.assertFalse(prev_none, f"rule missing in 2 consecutive samples: {samples}")
                prev_none = True
                continue
            prev_none = False
            self.assertTrue(n.isdigit() and int(n) >= MIN_ENTRIES, f"{smp!r} in {samples}")
        log = self.log_after(token)
        # the v3 load itself happened, whatever the final count says
        self.assertIn(f"MBL: loaded {LIST_SIZE} entries", log)
        self.assertIn("MBL: removed v2 files", log)
        self.assertEqual(self.num("/ip firewall raw", 'comment~"^MBL:"'), 6)
        self.assertEqual(self.num("/file", rsc), 0, self.chr.run("/file print"))
        self.assertEqual(self.num("/file", 'name="mbl-last.txt"'), 1, self.chr.run("/file print"))
        # the v3 load went to the other list (it does not clear the v2 one first)
        self.assertNotEqual(self.active_list(), v2_list)
        self.assertEqual(self.count(self.active_list()), LIST_SIZE)

    def test_11_injected_lines_never_run(self):
        name = "routeros-full-injected.txt"
        self.serve_variant(name)
        try:
            old = self.active_list()
            # a global variable is lost on reboot: proves `/system reboot` did not run
            self.chr.run(':global mblE2eAlive "yes"')
            token = self.mark()
            self.server.requests.clear()
            self.update()
            self.assertEqual(self.chr.run(":global mblE2eAlive; :put $mblE2eAlive").strip(), "yes")
            self.assertIn(token, self.log())
            self.assertNotEqual(self.active_list(), old)
            self.assertEqual(self.count(self.active_list()), LIST_SIZE)
            self.assertEqual(self.count("mbl-pwned"), 0)
            self.assertIn(f"/{name}", self.server.requests)
            self.assertIn("MBL: loaded", self.log_after(token))
        finally:
            self.restore_path(name)
            with suppress(ChrError, OSError):
                self.chr.run('/system script environment remove [find where name="mblE2eAlive"]')

    def test_12_count_mismatch_rejected(self):
        name = "routeros-full-mismatch.txt"
        self.serve_variant(name)
        try:
            self.assert_failed_update_keeps_active(
                f"/{name}", "MBL: mbl-new.txt rejected (count mismatch)")
        finally:
            self.restore_path(name)

    def test_13_crlf_accepted(self):
        name = "routeros-full-crlf.txt"
        self.serve_variant(name)
        try:
            old = self.active_list()
            token = self.mark()
            self.update()
            self.assertNotEqual(self.active_list(), old)
            self.assertEqual(self.count(self.active_list()), LIST_SIZE)
            self.assertIn(f"MBL: loaded {LIST_SIZE} entries", self.log_after(token))
        finally:
            self.restore_path(name)

    def test_14_too_many_invalid_rejected(self):
        name = "routeros-full-invalid.txt"
        self.serve_variant(name)
        try:
            self.assert_failed_update_keeps_active(
                f"/{name}", "MBL: mbl-new.txt rejected (too many invalid lines")
        finally:
            self.restore_path(name)

    def test_15_final_uninstall(self):
        self.uninstall()
        self.assertEqual(self.num("/ip firewall raw", 'comment~"^MBL:"'), 0)
        self.assertEqual(self.num("/system script", 'name~"^mbl-"'), 0)
        self.assertEqual(self.count("mbl-a") + self.count("mbl-b"), 0)


if __name__ == "__main__":
    unittest.main()
