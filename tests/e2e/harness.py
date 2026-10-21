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
    "-o", "LogLevel=ERROR",
    "-o", "ConnectTimeout=10",
)
# Only for VMs the harness boots itself: their host key is new every run.
_THROWAWAY_HOST_OPTS = (
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
)
# Existing hosts: the user's known_hosts; only a first-seen key is accepted.
_EXISTING_HOST_OPTS = ("-o", "StrictHostKeyChecking=accept-new")
# Download attempts and the first back-off delay (doubles every attempt).
ATTEMPTS = 3
BACKOFF = 5.0
# A client that does not finish the TLS handshake (or goes idle) is dropped.
TLS_TIMEOUT = 15.0


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


def _retry(fn, what: str, backoff: float):
    """Call `fn` up to ATTEMPTS times on OSError, sleeping backoff, 2x, ... between."""
    for attempt in range(ATTEMPTS):
        try:
            return fn()
        except OSError as e:
            if attempt == ATTEMPTS - 1:
                raise ChrError(f"cannot download {what} after {ATTEMPTS} attempts: {e}") from e
            time.sleep(backoff * 2 ** attempt)


def ensure_image(version: str, sha256: str | None, cache: Path, backoff: float = BACKOFF) -> Path:
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

        def download() -> None:
            try:
                with urllib.request.urlopen(url, timeout=120) as r, open(part, "wb") as f:
                    shutil.copyfileobj(r, f)
            except OSError:
                part.unlink(missing_ok=True)
                raise

        _retry(download, url, backoff)
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


def latest_stable(backoff: float = BACKOFF) -> str:
    def fetch() -> str:
        with urllib.request.urlopen(STABLE_URL, timeout=30) as r:
            return r.read().decode().split()[0]

    return _retry(fetch, STABLE_URL, backoff)


class _TlsHttpServer(ThreadingHTTPServer):
    """HTTPS server doing each TLS handshake in the connection's own thread.

    Wrapping the listening socket would handshake inside accept(), so a single
    client that never sends a ClientHello would block every other request.
    """

    def __init__(self, address, handler, ctx: ssl.SSLContext):
        self.ctx = ctx
        super().__init__(address, handler)

    def get_request(self):
        sock, addr = self.socket.accept()
        return self.ctx.wrap_socket(sock, server_side=True, do_handshake_on_connect=False), addr

    def finish_request(self, request, client_address):
        request.settimeout(TLS_TIMEOUT)
        request.do_handshake()
        super().finish_request(request, client_address)

    def handle_error(self, request, client_address):
        pass  # dropped/idle/non-TLS clients: not the test's business


class TlsServer:
    """Serves `root` over HTTPS with a certificate for 10.0.2.2 and 127.0.0.1.

    Listens on 127.0.0.1 only (QEMU user networking reaches it as 10.0.2.2).
    `extra_ips` adds more IP SANs (e.g. this host's LAN address, so that an
    existing CHR on the LAN can verify the certificate) and then listens on
    all addresses.
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
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(self._dir / "server.crt", self._dir / "server.key")
        bind = "0.0.0.0" if self.extra_ips else "127.0.0.1"
        httpd = _TlsHttpServer((bind, self.port), handler, ctx)
        try:
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
        except BaseException:
            httpd.server_close()
            raise
        # Only a server whose serve_forever thread runs is ever shut down.
        self._httpd, self._thread = httpd, thread
        atexit.register(self.stop)

    def stop(self) -> None:
        httpd, self._httpd = self._httpd, None
        thread, self._thread = self._thread, None
        if httpd is not None:
            if thread is not None and thread.is_alive():
                httpd.shutdown()
            httpd.server_close()
        if thread is not None:
            thread.join(timeout=5)
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None


class _TeeSocket:
    """Socket wrapper that appends everything received to a log file."""

    def __init__(self, sock: socket.socket, log_path: Path):
        self._sock = sock
        self._log = open(log_path, "ab", buffering=0)

    def recv(self, n: int) -> bytes:
        data = self._sock.recv(n)
        self._log.write(data)
        return data

    def close(self) -> None:
        self._sock.close()
        self._log.close()

    def __getattr__(self, name):
        return getattr(self._sock, name)


def _expect(sock: "socket.socket | _TeeSocket", pattern: bytes, timeout: float) -> bytes:
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
    def __init__(self, user: str, host: str, port: int, key: Path | None,
                 throwaway: bool = False):
        self.user, self.host, self.port, self.key = user, host, port, key
        # True for a VM booted here: its host key is not checked or recorded.
        self.throwaway = throwaway
        self.password: str | None = None
        self._proc: subprocess.Popen | None = None
        self._sock: socket.socket | _TeeSocket | None = None
        self._sockdir: str | None = None

    # -- constructors -------------------------------------------------------

    @classmethod
    def existing(cls, ssh: str, key: Path | None) -> "Chr":
        """Use an already provisioned CHR (`user@host[:port]`), key auth only."""
        user, _, hostport = ssh.rpartition("@")
        host, _, port = hostport.partition(":")
        return cls(user or "admin", host, int(port or 22), key)

    @classmethod
    def boot(cls, image: Path, workdir: Path, boot_timeout=180, ssh_timeout=120,
             log_dir: Path | None = None) -> "Chr":
        """Boot a disposable CHR from a copy of `image` in `workdir`.

        console.log and qemu.log are written to `log_dir` (default `workdir`)
        as they happen, so they survive even if the process is killed.
        """
        workdir = Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        log_dir = Path(log_dir) if log_dir is not None else workdir
        log_dir.mkdir(parents=True, exist_ok=True)
        key = workdir / "id_ed25519"
        chr_ = cls("admin", "127.0.0.1", free_port(), key, throwaway=True)
        atexit.register(chr_.stop)
        try:
            chr_._start_qemu(Path(image), workdir, log_dir)
            chr_._console_login(boot_timeout)
            chr_._console_setup()
            chr_._close_console()
            chr_.wait_ssh(ssh_timeout)
            for cmd in BASE_CONFIG:
                chr_.run(cmd)
        except (ChrError, OSError, TimeoutError) as e:
            chr_.stop()
            raise ChrError(f"CHR boot failed: {e}{chr_._log_tail(log_dir)}", chr_) from e
        return chr_

    # -- boot internals -----------------------------------------------------

    def _start_qemu(self, image: Path, workdir: Path, log_dir: Path) -> None:
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
        self.console_log = log_dir / "console.log"
        self.console_log.write_bytes(b"")
        with open(log_dir / "qemu.log", "wb") as log:
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
                self._sock = _TeeSocket(s, self.console_log)
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

    def _log_tail(self, log_dir: Path) -> str:
        try:
            tail = (log_dir / "qemu.log").read_text(errors="replace").strip()[-500:]
        except OSError:
            return ""
        return f"\nqemu output: {tail}" if tail else ""

    # -- public API ---------------------------------------------------------

    def _ssh_base(self, tool: str) -> list[str]:
        args = [tool, *_SSH_OPTS]
        args += _THROWAWAY_HOST_OPTS if self.throwaway else _EXISTING_HOST_OPTS
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
