"""Harness for end-to-end tests against a real MikroTik CHR (RouterOS v7).

Boots a disposable CHR in QEMU (or reuses an existing one by SSH key), and
serves test files over HTTPS with a throwaway CA. Standard library plus system
tools only (qemu-system-x86_64, ssh, scp, ssh-keygen, openssl).
"""
from __future__ import annotations

import atexit
import functools
import hashlib
import os
import re
import secrets
import shutil
import signal
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import urllib.request
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

IMAGE_URL = "https://download.mikrotik.com/routeros/{version}/chr-{version}.img.zip"
STABLE_URL = "https://upgrade.mikrotik.com/routeros/NEWESTa7.stable"

# Base configuration from the "management path" constraint: ether1 is WAN,
# the LAN is an empty bridge.
BASE_CONFIG = (
    "/interface bridge add name=bridge-lan comment=MBLTEST",
    "/interface list add name=WAN comment=MBLTEST",
    "/interface list add name=LAN comment=MBLTEST",
    "/interface list member add list=WAN interface=ether1 comment=MBLTEST",
    "/interface list member add list=LAN interface=bridge-lan comment=MBLTEST",
)

_PROMPT = rb"\[admin@[^\]\r\n]*\] > "
_SSH_OPTS = (
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "LogLevel=ERROR",
    "-o", "ConnectTimeout=10",
)


class ChrError(Exception):
    """Harness failure. `chr` is the (already stopped) instance, if any."""

    def __init__(self, message: str, chr: "Chr | None" = None):
        super().__init__(message)
        self.chr = chr


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_image(version: str, sha256: str | None, cache: Path) -> Path:
    """Download and unzip chr-<version>.img into `cache`; `sha256` is of the zip."""
    cache.mkdir(parents=True, exist_ok=True)
    zip_path = cache / f"chr-{version}.img.zip"
    img = cache / f"chr-{version}.img"
    if zip_path.exists() and sha256 and _sha256(zip_path) != sha256:
        zip_path.unlink()
        img.unlink(missing_ok=True)
    if not zip_path.exists():
        part = zip_path.with_name(zip_path.name + ".part")
        url = IMAGE_URL.format(version=version)
        try:
            with urllib.request.urlopen(url, timeout=120) as r, open(part, "wb") as f:
                shutil.copyfileobj(r, f)
        except OSError as e:
            part.unlink(missing_ok=True)
            raise ChrError(f"cannot download {url}: {e}") from e
        if sha256:
            got = _sha256(part)
            if got != sha256:
                part.unlink()
                raise ChrError(f"checksum mismatch for {url}: expected {sha256}, got {got}")
        part.replace(zip_path)
        img.unlink(missing_ok=True)
    if not img.exists():
        part = img.with_name(img.name + ".part")
        with zipfile.ZipFile(zip_path) as z, z.open(img.name) as src, open(part, "wb") as dst:
            shutil.copyfileobj(src, dst)
        part.replace(img)
    return img


def latest_stable() -> str:
    with urllib.request.urlopen(STABLE_URL, timeout=30) as r:
        return r.read().decode().split()[0]


class TlsServer:
    """Serves `root` over HTTPS with a certificate for 10.0.2.2 and 127.0.0.1.

    `extra_ips` adds more IP SANs (e.g. this host's LAN address, so that an
    existing CHR on the LAN can verify the certificate).
    """

    def __init__(self, root: Path, extra_ips: tuple[str, ...] = ()):
        self.root = Path(root)
        self.extra_ips = tuple(extra_ips)
        self.fail_paths: set[str] = set()
        # Paths of every GET received, in order (query string stripped).
        self.requests: list[str] = []
        self.port = free_port()
        self._tmp = tempfile.TemporaryDirectory(prefix="mbl-tls-")
        self._dir = Path(self._tmp.name)
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._make_certs()

    @property
    def ca_pem(self) -> Path:
        return self._dir / "ca.crt"

    def _openssl(self, *args: str) -> None:
        r = subprocess.run(["openssl", *args], cwd=self._dir, capture_output=True, text=True)
        if r.returncode != 0:
            raise ChrError(f"openssl {args[0]} failed: {r.stderr.strip()}")

    def _make_certs(self) -> None:
        self._openssl(
            "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "30",
            "-keyout", "ca.key", "-out", "ca.crt", "-subj", "/CN=MBL Test CA",
            "-addext", "basicConstraints=critical,CA:TRUE",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign",
        )
        self._openssl(
            "req", "-newkey", "rsa:2048", "-nodes", "-keyout", "server.key",
            "-out", "server.csr", "-subj", "/CN=10.0.2.2",
        )
        sans = ",".join(f"IP:{ip}" for ip in ("10.0.2.2", "127.0.0.1", *self.extra_ips))
        (self._dir / "server.ext").write_text(
            "basicConstraints=CA:FALSE\n"
            "keyUsage=critical,digitalSignature,keyEncipherment\n"
            "extendedKeyUsage=serverAuth\n"
            f"subjectAltName={sans}\n"
        )
        self._openssl(
            "x509", "-req", "-in", "server.csr", "-CA", "ca.crt", "-CAkey", "ca.key",
            "-CAcreateserial", "-days", "30", "-out", "server.crt", "-extfile", "server.ext",
        )

    def start(self) -> None:
        server = self

        class Handler(SimpleHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_GET(self):
                path = self.path.split("?", 1)[0]
                server.requests.append(path)
                if path in server.fail_paths:
                    self.send_error(404)
                    return
                super().do_GET()

        handler = functools.partial(Handler, directory=str(self.root))
        self._httpd = ThreadingHTTPServer(("0.0.0.0", self.port), handler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(self._dir / "server.crt", self._dir / "server.key")
        self._httpd.socket = ctx.wrap_socket(self._httpd.socket, server_side=True)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        atexit.register(self.stop)

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None


def _expect(sock: socket.socket, pattern: bytes, timeout: float) -> bytes:
    """Read from `sock` until regex `pattern` matches; return everything read."""
    deadline = time.monotonic() + timeout
    buf = b""
    while not re.search(pattern, buf):
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError(f"timed out waiting for {pattern!r}; last output: {buf[-300:]!r}")
        sock.settimeout(min(left, 1.0))
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            continue
        if not chunk:
            raise ChrError(f"serial console closed while waiting for {pattern!r}")
        buf += chunk
    return buf


class Chr:
    def __init__(self, user: str, host: str, port: int, key: Path | None):
        self.user, self.host, self.port, self.key = user, host, port, key
        self.password: str | None = None
        self._proc: subprocess.Popen | None = None
        self._sock: socket.socket | None = None
        self._sockdir: str | None = None

    # -- constructors -------------------------------------------------------

    @classmethod
    def existing(cls, ssh: str, key: Path | None) -> "Chr":
        """Use an already provisioned CHR (`user@host[:port]`), key auth only."""
        user, _, hostport = ssh.rpartition("@")
        host, _, port = hostport.partition(":")
        return cls(user or "admin", host, int(port or 22), key)

    @classmethod
    def boot(cls, image: Path, workdir: Path, boot_timeout=180, ssh_timeout=120) -> "Chr":
        workdir = Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        key = workdir / "id_ed25519"
        chr_ = cls("admin", "127.0.0.1", free_port(), key)
        atexit.register(chr_.stop)
        try:
            chr_._start_qemu(Path(image), workdir)
            chr_._console_login(boot_timeout)
            chr_._console_setup()
            chr_._close_console()
            chr_.wait_ssh(ssh_timeout)
            for cmd in BASE_CONFIG:
                chr_.run(cmd)
        except (ChrError, OSError, TimeoutError) as e:
            chr_.stop()
            raise ChrError(f"CHR boot failed: {e}{chr_._log_tail(workdir)}", chr_) from e
        return chr_

    # -- boot internals -----------------------------------------------------

    def _start_qemu(self, image: Path, workdir: Path) -> None:
        disk = workdir / "chr.img"
        shutil.copyfile(image, disk)
        for p in (self.key, self.key.with_suffix(".pub")):
            p.unlink(missing_ok=True)
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "mbl-test", "-f", str(self.key)],
            check=True, capture_output=True,
        )
        # Unix socket paths are limited to ~108 bytes: keep it in a short dir.
        self._sockdir = tempfile.mkdtemp(prefix="mbl-serial-")
        sock_path = os.path.join(self._sockdir, "serial.sock")
        cmd = [
            "qemu-system-x86_64", "-enable-kvm", "-m", "256", "-smp", "1", "-nographic",
            "-monitor", "none",
            "-serial", f"unix:{sock_path},server,nowait",
            "-drive", f"file={disk},format=raw,if=virtio",
            "-nic", f"user,model=virtio,hostfwd=tcp:127.0.0.1:{self.port}-:22",
        ]
        with open(workdir / "qemu.log", "wb") as log:
            self._proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        self._sock_path = sock_path

    def _check_alive(self) -> None:
        if self._proc is not None and self._proc.poll() is not None:
            raise ChrError(f"qemu exited with code {self._proc.returncode}")

    def _send(self, text: str) -> None:
        self._sock.sendall(text.encode() + b"\r")

    def _console_login(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout

        def left() -> float:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ChrError(f"no RouterOS login prompt within {timeout} s")
            return remaining

        while self._sock is None:
            left()
            self._check_alive()
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(self._sock_path)
                self._sock = s
            except OSError:
                s.close()
                time.sleep(0.2)
        # Poke the console until the login prompt shows up.
        while True:
            self._check_alive()
            self._sock.sendall(b"\r")
            try:
                _expect(self._sock, rb"Login: $", min(left(), 5))
                break
            except TimeoutError:
                continue
        # +ct: no colours, no terminal auto-detection (plain serial console).
        self._send("admin+ct")
        _expect(self._sock, rb"Password: $", min(left(), 30))
        self._send("")
        self.password = secrets.token_hex(12)
        changed = False
        while True:
            out = _expect(
                self._sock,
                rb"\[Y/n\]:?\s*$|new password> ?$|" + _PROMPT + rb"$|Login: $",
                left(),
            )
            if re.search(rb"\[Y/n\]:?\s*$", out):
                self._send("n")
            elif re.search(rb"repeat new password> ?$", out):
                self._send(self.password)
                changed = True
            elif re.search(rb"new password> ?$", out):
                self._send(self.password)
            elif re.search(rb"Login: $", out):
                raise ChrError("console login as admin with an empty password was rejected")
            else:
                break
        if not changed:
            self._console(f'/user set [find name=admin] password="{self.password}"')

    def _console(self, cmd: str, timeout: float = 30) -> bytes:
        self._send(cmd)
        return _expect(self._sock, _PROMPT + rb"$", timeout)

    def _console_setup(self) -> None:
        pub = self.key.with_suffix(".pub").read_text().strip()
        self._console(f'/file add name=mbl-test.pub contents="{pub}"')
        out = self._console("/user ssh-keys import public-key-file=mbl-test.pub user=admin")
        if b"failure" in out or b"error" in out.lower():
            raise ChrError(f"ssh key import failed: {out[-300:]!r}")

    def _close_console(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def _log_tail(self, workdir: Path) -> str:
        try:
            tail = (workdir / "qemu.log").read_text(errors="replace").strip()[-500:]
        except OSError:
            return ""
        return f"\nqemu output: {tail}" if tail else ""

    # -- public API ---------------------------------------------------------

    def _ssh_base(self, tool: str) -> list[str]:
        args = [tool, *_SSH_OPTS]
        if self.key is not None:
            args += ["-i", str(self.key), "-o", "IdentitiesOnly=yes"]
        return args

    def run(self, cmd: str, timeout=120) -> str:
        args = self._ssh_base("ssh") + ["-p", str(self.port), f"{self.user}@{self.host}", cmd]
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            raise ChrError(f"timeout after {timeout} s running {cmd!r}") from e
        if r.returncode != 0:
            raise ChrError(f"{cmd!r} failed ({r.returncode}): {r.stderr.strip()}")
        return r.stdout.replace("\r", "")

    def upload(self, local: Path, name: str) -> None:
        args = self._ssh_base("scp") + [
            "-P", str(self.port), str(local), f"{self.user}@{self.host}:{name}",
        ]
        r = subprocess.run(args, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise ChrError(f"upload of {local} failed: {r.stderr.strip()}")

    def _ssh_ok(self) -> bool:
        try:
            return self.run(":put ok", timeout=20).strip() == "ok"
        except ChrError:
            return False

    def wait_ssh(self, timeout: float = 120) -> None:
        deadline = time.monotonic() + timeout
        while not self._ssh_ok():
            self._check_alive()
            if time.monotonic() > deadline:
                raise ChrError(f"SSH not reachable on port {self.port} within {timeout} s")
            time.sleep(2)

    def reboot(self, wait=True) -> None:
        self.run(":execute {/system reboot}")
        if not wait:
            return
        deadline = time.monotonic() + 60
        while self._ssh_ok():
            if time.monotonic() > deadline:
                raise ChrError("router did not go down after reboot")
            time.sleep(1)
        self.wait_ssh(180)

    def stop(self) -> None:
        self._close_console()
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=10)
            except ProcessLookupError:
                pass
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
        elif proc is not None:
            proc.wait()
        if self._sockdir is not None:
            shutil.rmtree(self._sockdir, ignore_errors=True)
            self._sockdir = None
