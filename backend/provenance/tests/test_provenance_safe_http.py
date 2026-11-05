"""The fetcher's safety rules. Nothing here uses a real connection."""

from __future__ import annotations

import gzip
import socket
import time

import pytest

from backend.provenance import safe_http
from backend.provenance.safe_http import HttpBlocked, HttpFailed, is_public_ip, safe_request


class FakeRaw:
    def __init__(self, status=200, headers=None, chunks=(b"ok",)) -> None:
        self.status = status
        self._headers = headers or {}
        self._chunks = list(chunks)

    def getheader(self, name, default=None):
        return {k.lower(): v for k, v in self._headers.items()}.get(name.lower(), default)

    def getheaders(self):
        return list(self._headers.items())

    def read1(self, _size):
        return self._chunks.pop(0) if self._chunks else b""


class FakeConnection:
    def close(self):
        pass


def serve(monkeypatch, responses):
    """Replace the socket layer. ``responses`` maps URL paths to FakeRaw objects."""
    seen = []

    def fake_open(parts, method, headers, body, timeout):
        seen.append(parts.geturl())
        return FakeConnection(), responses[parts.geturl()]

    monkeypatch.setattr(safe_http, "_open", fake_open)
    return seen


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.8",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "224.0.0.1",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:127.0.0.1",
        "::ffff:169.254.169.254",
        "64:ff9b::a00:1",
        "2002:7f00:1::",
        "::7f00:1",
        "not-an-address",
    ],
)
def test_private_and_special_addresses_are_not_public(address):
    assert is_public_ip(address) is False


@pytest.mark.parametrize("address", ["93.184.216.34", "8.8.8.8", "2606:2800:220:1:248:1893:25c8:1946"])
def test_public_addresses_are_public(address):
    assert is_public_ip(address) is True


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://site.test/x",
        "gopher://site.test/",
        "javascript:alert(1)",
        "https://user:secret@site.test/",
        "https://site.test:22/",
        "http://site.test:8080/",
        "https://",
        "https://site.test/a b",
        "https://site.test/a\r\nHost: evil",
    ],
)
def test_unsafe_urls_are_refused_before_connecting(monkeypatch, url):
    monkeypatch.setattr(safe_http, "_open", lambda *a: pytest.fail("It tried to connect."))
    with pytest.raises(HttpBlocked):
        safe_request(url)


@pytest.mark.parametrize(
    "resolved",
    ["127.0.0.1", "10.1.2.3", "169.254.169.254", "::1", "::ffff:10.0.0.1"],
)
def test_host_resolving_to_a_private_address_is_refused(monkeypatch, resolved):
    family = socket.AF_INET6 if ":" in resolved else socket.AF_INET
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: [(family, socket.SOCK_STREAM, 6, "", (resolved, 443))]
    )
    with pytest.raises(HttpBlocked):
        safe_request("https://looks-public.test/")


@pytest.mark.parametrize("url", ["http://[::1]/", "https://[::1]/", "http://[::ffff:10.0.0.1]/", "http://127.0.0.1/"])
def test_address_literals_reach_the_address_check(url):
    with pytest.raises(HttpBlocked):
        safe_request(url)


def test_host_with_any_private_address_is_refused(monkeypatch):
    infos = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443)),
    ]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: infos)
    with pytest.raises(HttpBlocked):
        safe_request("https://mixed.test/")


def test_address_is_checked_when_connecting_on_plain_http_too(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]
    )
    with pytest.raises(HttpBlocked):
        safe_request("http://rebinding.test/")


def test_public_host_reaches_the_connect_step(monkeypatch):
    """The guard allows public addresses, and the no_network fixture then stops the attempt."""
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]
    )
    with pytest.raises(AssertionError, match="network"):
        safe_request("http://public.test/")


def test_dns_failure_is_a_network_failure(monkeypatch):
    def fail(*args, **kwargs):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    with pytest.raises(HttpFailed) as caught:
        safe_request("https://missing.test/")
    assert caught.value.kind == "network"


def test_redirect_is_followed_and_each_hop_is_validated(monkeypatch):
    seen = serve(
        monkeypatch,
        {
            "https://a.test/start": FakeRaw(302, {"Location": "/next"}),
            "https://a.test/next": FakeRaw(200, chunks=[b"done"]),
        },
    )
    response = safe_request("https://a.test/start")
    assert response.body == b"done"
    assert response.url == "https://a.test/next"
    assert seen == ["https://a.test/start", "https://a.test/next"]


@pytest.mark.parametrize(
    "target",
    ["file:///etc/passwd", "https://user:pw@a.test/", "https://a.test:8080/", "gopher://a.test/"],
)
def test_redirect_to_an_unsafe_url_is_refused(monkeypatch, target):
    serve(monkeypatch, {"https://a.test/start": FakeRaw(302, {"Location": target})})
    with pytest.raises(HttpBlocked):
        safe_request("https://a.test/start")


def test_redirect_to_a_private_address_is_refused(monkeypatch):
    """Real connection classes run for the second hop, with DNS pointing somewhere private."""
    real_open = safe_http._open

    def first_hop_then_real(parts, method, headers, body, timeout):
        if parts.hostname == "public.test":
            return FakeConnection(), FakeRaw(302, {"Location": "http://169.254.169.254/latest/meta-data/"})
        return real_open(parts, method, headers, body, timeout)

    monkeypatch.setattr(safe_http, "_open", first_hop_then_real)
    with pytest.raises(HttpBlocked):
        safe_request("https://public.test/start")


def test_redirect_loop_stops(monkeypatch):
    monkeypatch.setattr(safe_http, "_open", lambda *a: (FakeConnection(), FakeRaw(302, {"Location": "/loop"})))
    with pytest.raises(HttpBlocked):
        safe_request("https://a.test/loop", max_redirects=2)


def test_no_redirects_for_provider_calls(monkeypatch):
    serve(monkeypatch, {"https://a.test/": FakeRaw(302, {"Location": "http://10.0.0.1/"}, chunks=[b""])})
    assert safe_request("https://a.test/", max_redirects=0).status == 302


def test_declared_size_over_the_limit_is_refused_without_reading(monkeypatch):
    raw = FakeRaw(200, {"Content-Length": "5000"}, chunks=[])
    raw.read1 = lambda _size: pytest.fail("It read the body.")
    serve(monkeypatch, {"https://a.test/": raw})
    with pytest.raises(HttpFailed) as caught:
        safe_request("https://a.test/", max_bytes=100)
    assert caught.value.kind == "too_large"


def test_undeclared_oversized_body_stops_at_the_limit(monkeypatch):
    serve(monkeypatch, {"https://a.test/": FakeRaw(chunks=[b"x" * 60, b"x" * 60, b"x" * 60])})
    with pytest.raises(HttpFailed) as caught:
        safe_request("https://a.test/", max_bytes=100)
    assert caught.value.kind == "too_large"


def test_gzip_bomb_is_refused(monkeypatch):
    bomb = gzip.compress(b"\0" * 5_000_000)
    serve(monkeypatch, {"https://a.test/": FakeRaw(headers={"Content-Encoding": "gzip"}, chunks=[bomb])})
    with pytest.raises(HttpFailed) as caught:
        safe_request("https://a.test/", max_bytes=100_000)
    assert caught.value.kind == "too_large"


def test_gzip_body_is_decoded(monkeypatch):
    serve(monkeypatch, {"https://a.test/": FakeRaw(headers={"Content-Encoding": "gzip"}, chunks=[gzip.compress(b"hi")])})
    assert safe_request("https://a.test/").body == b"hi"


@pytest.mark.parametrize(
    ("encoding", "chunk"),
    [("br", b"anything"), ("gzip", b"not gzip at all")],
)
def test_unreadable_encodings_fail_cleanly(monkeypatch, encoding, chunk):
    serve(monkeypatch, {"https://a.test/": FakeRaw(headers={"Content-Encoding": encoding}, chunks=[chunk])})
    with pytest.raises(HttpFailed) as caught:
        safe_request("https://a.test/")
    assert caught.value.kind == "decode"


def test_slow_body_stops_at_the_deadline(monkeypatch):
    class Slow(FakeRaw):
        def read1(self, _size):
            time.sleep(0.02)
            return b"x"

    serve(monkeypatch, {"https://a.test/": Slow()})
    with pytest.raises(HttpFailed) as caught:
        safe_request("https://a.test/", deadline=time.monotonic() + 0.1)
    assert caught.value.kind == "timeout"


def test_expired_deadline_never_connects(monkeypatch):
    monkeypatch.setattr(safe_http, "_open", lambda *a: pytest.fail("It tried to connect."))
    with pytest.raises(HttpFailed) as caught:
        safe_request("https://a.test/", deadline=time.monotonic() - 1)
    assert caught.value.kind == "timeout"


def test_socket_timeout_is_reported_as_a_timeout(monkeypatch):
    def fail(*args):
        raise TimeoutError

    monkeypatch.setattr(safe_http, "_open", fail)
    with pytest.raises(HttpFailed) as caught:
        safe_request("https://a.test/")
    assert caught.value.kind == "timeout"


def test_errors_never_contain_the_url(monkeypatch):
    def fail(*args):
        raise OSError("connection refused")

    monkeypatch.setattr(safe_http, "_open", fail)
    with pytest.raises(HttpFailed) as caught:
        safe_request("https://a.test/search?api_key=SECRET")
    assert "SECRET" not in str(caught.value)
    assert "SECRET" not in repr(caught.value)


def test_proxy_settings_are_ignored(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://10.0.0.1:3128")
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda host, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
    )
    with pytest.raises(HttpBlocked):
        safe_request("https://a.test/")
