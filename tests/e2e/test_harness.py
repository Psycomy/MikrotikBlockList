"""Unit tests for the CHR harness. Fast, no VM, run in the normal discover."""
import hashlib
import io
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from unittest import mock

from tests.e2e import harness
from tests.e2e.harness import (
    Chr, ChrError, TlsServer, ensure_image, free_port, latest_stable,
)


class FreePortTest(unittest.TestCase):
    def test_free_port(self):
        ports = [free_port(), free_port()]
        for port in ports:
            self.assertIsInstance(port, int)
            self.assertTrue(1024 <= port <= 65535, port)
            with socket.socket() as s:
                s.bind(("127.0.0.1", port))


@unittest.skipUnless(shutil.which("openssl"), "openssl not available")
class TlsServerTest(unittest.TestCase):
    def test_tls_server_serves_with_ca(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "x.txt").write_text("hello")
            server = TlsServer(Path(root))
            server.fail_paths = {"/missing"}
            server.start()
            try:
                ctx = ssl.create_default_context(cafile=str(server.ca_pem))
                base = f"https://127.0.0.1:{server.port}"
                with urllib.request.urlopen(f"{base}/x.txt", context=ctx, timeout=10) as r:
                    self.assertEqual(r.read(), b"hello")
                with self.assertRaises(urllib.error.HTTPError) as cm:
                    urllib.request.urlopen(f"{base}/missing", context=ctx, timeout=10)
                self.assertEqual(cm.exception.code, 404)
                cm.exception.close()
            finally:
                server.stop()
                server.stop()

    def test_binds_loopback_without_extra_ips(self):
        with tempfile.TemporaryDirectory() as root:
            server = TlsServer(Path(root))
            server.start()
            try:
                self.assertEqual(server._httpd.server_address[0], "127.0.0.1")
            finally:
                server.stop()

    def test_idle_connection_does_not_block(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "x.txt").write_text("hello")
            server = TlsServer(Path(root))
            server.start()
            try:
                # A client that connects and never starts the TLS handshake.
                with socket.create_connection(("127.0.0.1", server.port)):
                    time.sleep(0.2)
                    ctx = ssl.create_default_context(cafile=str(server.ca_pem))
                    url = f"https://127.0.0.1:{server.port}/x.txt"
                    with urllib.request.urlopen(url, context=ctx, timeout=5) as r:
                        self.assertEqual(r.read(), b"hello")
            finally:
                server.stop()

    def test_stop_after_failed_start_returns(self):
        with tempfile.TemporaryDirectory() as root:
            server = TlsServer(Path(root))
            (server._dir / "server.crt").unlink()
            with self.assertRaises(OSError):
                server.start()
            t = threading.Thread(target=server.stop, daemon=True)
            t.start()
            t.join(2)
            self.assertFalse(t.is_alive(), "stop() hung after a failed start()")


class EnsureImageTest(unittest.TestCase):
    def test_ensure_image_checksum_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp, "src.zip")
            with zipfile.ZipFile(src, "w") as z:
                z.writestr("chr-test.img", b"not really a disk")
            cache = Path(tmp, "cache")
            url = src.as_uri()
            with mock.patch.object(harness, "IMAGE_URL", url):
                with self.assertRaises(ChrError):
                    ensure_image("test", "0" * 64, cache)
                self.assertFalse(Path(cache, "chr-test.img").exists())
                # The right checksum is accepted and the image extracted.
                good = hashlib.sha256(src.read_bytes()).hexdigest()
                img = ensure_image("test", good, cache)
                self.assertEqual(img.read_bytes(), b"not really a disk")

    def test_ensure_image_retries_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp, "src.zip")
            with zipfile.ZipFile(src, "w") as z:
                z.writestr("chr-test.img", b"disk")
            real = urllib.request.urlopen
            calls = []

            def flaky(url, timeout):
                calls.append(url)
                if len(calls) < 3:
                    raise urllib.error.URLError("temporary failure")
                return real(url, timeout=timeout)

            with mock.patch.object(harness, "IMAGE_URL", src.as_uri()), \
                    mock.patch.object(urllib.request, "urlopen", flaky):
                img = ensure_image("test", None, Path(tmp, "cache"), backoff=0)
            self.assertEqual(img.read_bytes(), b"disk")
            self.assertEqual(len(calls), 3)

    def test_ensure_image_retries_truncated_download(self):
        # download.mikrotik.com sometimes closes the connection before the full
        # Content-Length; http.client returns the short body without an error.
        import http.server
        import threading

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp, "src.zip")
            with zipfile.ZipFile(src, "w") as z:
                z.writestr("chr-test.img", b"disk" * 10000)
            body = src.read_bytes()
            hits = []

            class Handler(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    hits.append(self.path)
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body if len(hits) > 1 else body[: len(body) // 2])
                    self.close_connection = True

                def log_message(self, *args):
                    pass

            srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            self.addCleanup(srv.server_close)
            self.addCleanup(srv.shutdown)
            url = f"http://127.0.0.1:{srv.server_port}/chr-{{version}}.img.zip"
            good = hashlib.sha256(body).hexdigest()
            with mock.patch.object(harness, "IMAGE_URL", url):
                img = ensure_image("test", good, Path(tmp, "cache"), backoff=0)
            self.assertEqual(img.read_bytes(), b"disk" * 10000)
            self.assertEqual(len(hits), 2)

    def test_ensure_image_gives_up_after_three_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            down = mock.Mock(side_effect=urllib.error.URLError("down"))
            with mock.patch.object(urllib.request, "urlopen", down):
                with self.assertRaises(ChrError):
                    ensure_image("test", None, Path(tmp, "cache"), backoff=0)
            self.assertEqual(down.call_count, 3)


class LatestStableTest(unittest.TestCase):
    def test_latest_stable_retries(self):
        ok = mock.MagicMock()
        ok.__enter__.return_value = io.BytesIO(b"7.24.5 1760000000\n")
        flaky = mock.Mock(side_effect=[urllib.error.URLError("x"), OSError("y"), ok])
        with mock.patch.object(urllib.request, "urlopen", flaky):
            self.assertEqual(latest_stable(backoff=0), "7.24.5")
        self.assertEqual(flaky.call_count, 3)


class SshOptionsTest(unittest.TestCase):
    def test_existing_host_uses_known_hosts(self):
        args = Chr.existing("admin@192.0.2.10", None)._ssh_base("ssh")
        self.assertIn("StrictHostKeyChecking=accept-new", args)
        self.assertNotIn("UserKnownHostsFile=/dev/null", args)
        self.assertNotIn("StrictHostKeyChecking=no", args)


@unittest.skipUnless(shutil.which("ssh-keygen"), "ssh-keygen not available")
class BootTimeoutTest(unittest.TestCase):
    """A QEMU that never shows a login prompt must not hang the harness."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        bindir = tmp / "bin"
        bindir.mkdir()
        cls.pidfile = tmp / "qemu.pid"
        fake = bindir / "qemu-system-x86_64"
        fake.write_text(f'#!/bin/sh\necho $$ > "{cls.pidfile}"\nexec sleep 60\n')
        fake.chmod(0o755)
        image = tmp / "chr.img"
        image.write_bytes(b"\0" * 512)
        workdir = tmp / "work"
        workdir.mkdir()
        path = f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}"
        cls.error = None
        start = time.monotonic()
        with mock.patch.dict(os.environ, {"PATH": path}):
            try:
                Chr.boot(image, workdir, boot_timeout=2, ssh_timeout=2)
            except ChrError as e:
                cls.error = e
        cls.elapsed = time.monotonic() - start

    @classmethod
    def tearDownClass(cls):
        if cls.error is not None and cls.error.chr is not None:
            cls.error.chr.stop()
        cls.tmp.cleanup()

    def test_boot_timeout_raises(self):
        self.assertIsNotNone(self.error, "Chr.boot did not raise ChrError")
        self.assertLess(self.elapsed, 10)
        pid = int(self.pidfile.read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_stop_is_idempotent(self):
        self.assertIsNotNone(self.error, "Chr.boot did not raise ChrError")
        chr_ = self.error.chr
        self.assertIsInstance(chr_, Chr)
        chr_.stop()
        chr_.stop()

    def test_booted_vm_uses_throwaway_host_keys(self):
        self.assertIsNotNone(self.error, "Chr.boot did not raise ChrError")
        args = self.error.chr._ssh_base("ssh")
        self.assertIn("UserKnownHostsFile=/dev/null", args)
        self.assertIn("StrictHostKeyChecking=no", args)


class E2eSkipTest(unittest.TestCase):
    def test_e2e_skipped_without_flag(self):
        """The real CHR cases never run in a normal discover (no MBL_E2E=1)."""
        env = {k: v for k, v in os.environ.items() if k != "MBL_E2E"}
        root = Path(__file__).resolve().parents[2]
        r = subprocess.run(
            [sys.executable, "-m", "unittest", "tests.e2e.test_routeros"],
            cwd=root, env=env, capture_output=True, text=True, timeout=60,
        )
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, out)
        self.assertIn("skipped", out)


if __name__ == "__main__":
    unittest.main()
