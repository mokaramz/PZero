"""The outbound boundary (review 017, Codex H-113): the SSRF refusals, each hop pinned to the address validated for it
(also across redirects), the size cap, the deadline, and TLS verified on the ORIGINAL hostname with no insecure
fallback. Everything runs against fakes or local servers; nothing leaves the machine."""

from __future__ import annotations

import contextlib
import http.server
import shutil
import socketserver
import ssl
import subprocess
import threading
import time
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, ClassVar

import pytest

from projectzero.core import net
from projectzero.core.net import FetchError, PinnedTransport, Response, ResponseTooLargeError, Target, UnsafeURLError

PUBLIC = "93.184.215.14"


def resolver(table: Mapping[str, list[str]]) -> net.Resolver:
    return lambda host: list(table.get(host, []))


@pytest.mark.parametrize(
    ("url", "why"),
    [
        ("http://127.0.0.1/x", "non-public IP literal"),
        ("http://10.1.2.3/", "non-public IP literal"),
        ("http://169.254.169.254/latest/meta-data", "non-public IP literal"),
        ("http://[::1]/", "non-public IP literal"),
        ("http://[::ffff:127.0.0.1]/", "non-public IP literal"),  # IPv4-mapped IPv6
        ("http://[fe80::1]/", "non-public IP literal"),
        ("ftp://example.com/x", "scheme not allowed"),
        ("file:///etc/passwd", "scheme not allowed"),
        ("http://user:pw@example.com/", "userinfo in URL"),
        ("http://localhost:8000/", "local host name"),
        ("http://printer.local/", "local host name"),
        ("http://private.example.com/", "DNS resolves to a non-public address (10.0.0.5)"),
        ("http://mixed.example.com/", "DNS resolves to a non-public address (192.168.1.9)"),  # ONE bad answer refuses
        ("http://nowhere.example.com/", "DNS resolution failed"),
        ("http:///nohost", "no host"),
    ],
)
def test_unsafe_destinations_are_refused(url: str, why: str) -> None:
    table = {"private.example.com": ["10.0.0.5"], "mixed.example.com": [PUBLIC, "192.168.1.9"]}
    with pytest.raises(UnsafeURLError, match=why.replace("(", r"\(").replace(")", r"\)")):
        net.validate(url, resolver(table))


def test_a_public_destination_is_pinned_to_its_checked_address() -> None:
    t = net.validate("https://Events.Example.com/list?q=1", resolver({"events.example.com": [PUBLIC]}))
    assert t == Target("https", "events.example.com", 443, PUBLIC, "/list?q=1")


class FakeTransport:
    """Answers from a script and records which address every hop was sent to."""

    def __init__(self, answers: Mapping[str, Response]) -> None:
        self.answers = answers
        self.sent: list[tuple[str, str, str]] = []

    def send(
        self,
        target: Target,
        method: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
        max_bytes: int,
        deadline: float | None = None,
    ) -> Response:  # fmt: skip
        self.sent.append((target.host, target.ip, method))
        return self.answers[f"{target.host}{target.path}"]


def test_every_redirect_hop_is_validated_and_pinned_and_a_private_hop_is_never_sent() -> None:
    names = {"a.example.com": [PUBLIC], "b.example.com": ["93.184.215.15"], "evil.example.com": ["10.0.0.7"]}
    fake = FakeTransport({
        "a.example.com/start": Response("", 302, {"location": "https://b.example.com/next"}),
        "b.example.com/next": Response("", 200, {}, b"ok"),
        "a.example.com/bad": Response("", 302, {"location": "http://evil.example.com/internal"}),
    })  # fmt: skip
    r = net.fetch("https://a.example.com/start", resolver=resolver(names), transport=fake)
    assert (r.status, r.text()) == (200, "ok")
    assert fake.sent == [("a.example.com", PUBLIC, "GET"), ("b.example.com", "93.184.215.15", "GET")]
    with pytest.raises(UnsafeURLError, match="non-public"):
        net.fetch("https://a.example.com/bad", resolver=resolver(names), transport=fake)
    assert ("evil.example.com", "10.0.0.7", "GET") not in fake.sent


def test_redirect_limits_errors_and_the_deadline() -> None:
    names = {"a.example.com": [PUBLIC]}
    loop = FakeTransport({"a.example.com/loop": Response("", 301, {"location": "/loop"})})
    with pytest.raises(FetchError, match="more than 5 redirects"):
        net.fetch("https://a.example.com/loop", resolver=resolver(names), transport=loop)
    assert len(loop.sent) == 6
    err = FakeTransport({"a.example.com/x": Response("", 500, {}, b"")})
    with pytest.raises(FetchError, match="HTTP Error 500"):
        net.fetch("https://a.example.com/x", resolver=resolver(names), transport=err)
    late = FakeTransport({})
    with pytest.raises(FetchError, match="deadline"):
        net.fetch("https://a.example.com/x", resolver=resolver(names), transport=late, deadline=time.monotonic() - 1)
    assert late.sent == []  # nothing is sent after the deadline


def test_a_303_after_a_post_becomes_a_get() -> None:
    fake = FakeTransport({
        "a.example.com/form": Response("", 303, {"location": "/done"}),
        "a.example.com/done": Response("", 200, {}, b"{}"),
    })  # fmt: skip
    net.fetch("https://a.example.com/form", data=b"x=1", resolver=resolver({"a.example.com": [PUBLIC]}), transport=fake)
    assert [m for _, _, m in fake.sent] == ["POST", "GET"]


# ── the real transport against local servers (the address is given, so the guard is bypassed on purpose) ──────
class _Handler(http.server.BaseHTTPRequestHandler):
    seen_hosts: ClassVar[list[str]] = []
    body = b"hello"

    def do_GET(self) -> None:
        type(self).seen_hosts.append(self.headers.get("Host", ""))
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *_: Any) -> None:
        return


@pytest.fixture
def http_server() -> Iterator[int]:
    srv = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield int(srv.server_address[1])
    finally:
        srv.shutdown()
        srv.server_close()


def test_the_pinned_transport_connects_to_the_given_address_and_sends_the_hostname(http_server: int) -> None:
    _Handler.seen_hosts = []
    t = Target("http", "pinned.example.com", http_server, "127.0.0.1", "/")
    r = PinnedTransport().send(t, "GET", {}, None, 5, 1_000)
    assert r.text() == "hello" and _Handler.seen_hosts == [f"pinned.example.com:{http_server}"]
    with pytest.raises(ResponseTooLargeError):
        PinnedTransport().send(t, "GET", {}, None, 5, 3)


@pytest.fixture(scope="module")
def tls_files(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    if not shutil.which("openssl"):
        pytest.skip("openssl is needed to make a throw-away test certificate")
    d = tmp_path_factory.mktemp("tls")
    key, cert = d / "key.pem", d / "cert.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=pinned.example.com",
         "-addext", "subjectAltName=DNS:pinned.example.com", "-days", "2", "-keyout", str(key), "-out", str(cert)],
        check=True, capture_output=True,
    )  # fmt: skip
    return key, cert


@pytest.fixture
def tls_server(tls_files: tuple[Path, Path]) -> Iterator[tuple[int, list[str | None]]]:
    key, cert = tls_files
    sni: list[str | None] = []
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert), str(key))
    ctx.sni_callback = lambda sock, name, _ctx: sni.append(name)
    srv = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield int(srv.server_address[1]), sni
    finally:
        srv.shutdown()
        srv.server_close()


def test_tls_is_verified_on_the_hostname_and_never_falls_back(
    tls_server: tuple[int, list[str | None]], tls_files: tuple[Path, Path]
) -> None:
    port, sni = tls_server
    t = Target("https", "pinned.example.com", port, "127.0.0.1", "/")
    with pytest.raises(ssl.SSLCertVerificationError):  # an untrusted certificate: refused, no second attempt
        PinnedTransport().send(t, "GET", {}, None, 5, 1_000)
    trusting = ssl.create_default_context(cafile=str(tls_files[1]))
    assert PinnedTransport(trusting).send(t, "GET", {}, None, 5, 1_000).text() == "hello"
    assert sni[-1] == "pinned.example.com"  # SNI carried the hostname although the socket went to the address
    wrong = Target("https", "other.example.com", port, "127.0.0.1", "/")
    with pytest.raises(ssl.SSLCertVerificationError):  # the certificate is checked against the hostname
        PinnedTransport(trusting).send(wrong, "GET", {}, None, 5, 1_000)


# ── the deadline bounds the whole fetch in wall-clock time (Codex H-115) ────────────────────────────────────────
def test_a_slow_resolver_cannot_hold_a_fetch_past_its_deadline() -> None:
    def slow(_host: str) -> list[str]:
        time.sleep(2)
        return [PUBLIC]

    fake = FakeTransport({})
    t0 = time.monotonic()
    with pytest.raises(FetchError, match=r"deadline reached \(DNS resolution\)"):
        net.fetch("https://slow.example.com/", resolver=slow, transport=fake, deadline=time.monotonic() + 0.3)
    assert time.monotonic() - t0 < 1.5 and fake.sent == []


class _Trickle(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Length", "100")
        self.end_headers()
        for _ in range(100):  # one byte every 0.1 s: never idle long enough for a socket timeout
            try:
                self.wfile.write(b"x")
                self.wfile.flush()
            except OSError:
                return
            time.sleep(0.1)

    def log_message(self, *_: Any) -> None:
        return


def test_a_trickling_response_cannot_hold_a_read_past_the_deadline() -> None:
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Trickle)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        t = Target("http", "slow.example.com", int(srv.server_address[1]), "127.0.0.1", "/")
        t0 = time.monotonic()
        with pytest.raises(FetchError, match="deadline reached"):
            PinnedTransport().send(t, "GET", {}, None, 5, 1_000, deadline=time.monotonic() + 0.8)
        assert time.monotonic() - t0 < 2.0  # the 5 s socket timeout alone would have read for 10 s
    finally:
        srv.shutdown()
        srv.server_close()


def test_no_hop_starts_after_the_deadline() -> None:
    fake = FakeTransport({"a.example.com/x": Response("", 200, {}, b"")})
    asked: list[str] = []

    def resolver_(host: str) -> list[str]:
        asked.append(host)
        return [PUBLIC]

    with pytest.raises(FetchError, match="deadline"):
        net.fetch("https://a.example.com/x", resolver=resolver_, transport=fake, deadline=time.monotonic() - 0.01)
    assert asked == [] and fake.sent == []  # not even resolved


class _Silent(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Length", "10")
        self.end_headers()
        self.wfile.write(b"x")
        self.wfile.flush()
        time.sleep(10)  # then nothing at all

    def log_message(self, *_: Any) -> None:
        return


def test_a_server_that_goes_silent_mid_body_is_cut_off_at_the_deadline_not_the_socket_timeout() -> None:
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Silent)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        t = Target("http", "quiet.example.com", int(srv.server_address[1]), "127.0.0.1", "/")
        t0 = time.monotonic()
        with pytest.raises(FetchError, match="deadline reached"):
            PinnedTransport().send(t, "GET", {}, None, 6, 1_000, deadline=time.monotonic() + 0.8)
        assert time.monotonic() - t0 < 3.0  # the 6 s socket timeout would have held the read for 6 s
    finally:
        srv.shutdown()
        srv.server_close()


class _HeaderTrickle(socketserver.BaseRequestHandler):
    """Sends the status line and then ONE header byte every 0.1 s: the headers never finish."""

    def handle(self) -> None:
        self.request.recv(4096)
        with contextlib.suppress(OSError):
            self.request.sendall(b"HTTP/1.1 200 OK\r\n")
            for _ in range(200):
                self.request.sendall(b"X")
                time.sleep(0.1)


def test_a_server_trickling_its_headers_is_cut_off_at_the_deadline() -> None:
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _HeaderTrickle)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        t = Target("http", "headers.example.com", int(srv.server_address[1]), "127.0.0.1", "/")
        t0 = time.monotonic()
        with pytest.raises(FetchError, match="deadline reached"):
            PinnedTransport().send(t, "GET", {}, None, 6, 1_000, deadline=time.monotonic() + 0.8)
        assert time.monotonic() - t0 < 2.0  # the headers alone would have taken 20 s, never idle 6 s
    finally:
        srv.shutdown()
        srv.server_close()
