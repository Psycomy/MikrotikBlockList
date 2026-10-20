"""Unit tests for the CHR harness. Fast, no VM, run in the normal discover."""
import hashlib
import os
import shutil
import socket
import ssl
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from unittest import mock

from tests.e2e import harness
from tests.e2e.harness import Chr, ChrError, TlsServer, ensure_image, free_port


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


if __name__ == "__main__":
    unittest.main()
