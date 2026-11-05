"""HTTP for untrusted URLs, using only the standard library.

Search results point at arbitrary pages, so a naive fetch could reach internal
services. Addresses are checked when each connection is made, not beforehand, so
a host cannot pass the check and then resolve to a private address. Every redirect
opens a new checked connection. Proxies from the environment are not used.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import time
import zlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import SplitResult, quote, urljoin, urlsplit

_ALLOWED_SCHEMES = {"http", "https"}
_ALLOWED_PORTS = {None, 80, 443}
_REDIRECTS = {301, 302, 303, 307, 308}
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_READ_SIZE = 64 * 1024


class HttpBlocked(Exception):
    """The safety rules refused this request. The reason is safe to show."""


class HttpFailed(Exception):
    """The request failed. ``kind`` is timeout, network, too_large or decode."""

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


@dataclass(frozen=True)
class HttpResponse:
    url: str
    status: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""


class Requester(Protocol):
    def __call__(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        timeout_s: float = 5.0,
        max_bytes: int = 2 * 1024 * 1024,
        deadline: float | None = None,
        max_redirects: int = 3,
    ) -> HttpResponse: ...


def is_public_ip(value: str) -> bool:
    """True only for addresses on the public internet, including embedded IPv4."""
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address):
        if address in _NAT64 or address.sixtofour is not None or address.teredo is not None:
            return False
        if int(address) < 2**32:  # The old IPv4-compatible form, such as ::127.0.0.1.
            return False
        if address.ipv4_mapped is not None:
            address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


def _connect_public(host: str, port: int, timeout: float) -> socket.socket:
    """Open a socket to ``host``, refusing it if any resolved address is not public."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as exc:
        raise HttpFailed("network") from exc
    if not infos:
        raise HttpFailed("network")
    if not all(is_public_ip(info[4][0]) for info in infos):
        raise HttpBlocked("The address is not on the public internet.")
    last_error: OSError | None = None
    # Two tries, because a network without IPv6 can still be handed an IPv6 address first.
    for family, kind, protocol, _, address in infos[:2]:
        sock = socket.socket(family, kind, protocol)
        try:
            sock.settimeout(timeout)
            sock.connect(address)
            return sock
        except OSError as exc:
            sock.close()
            last_error = exc
        except BaseException:
            sock.close()
            raise
    raise last_error


class _PublicHTTPConnection(http.client.HTTPConnection):
    def connect(self) -> None:
        self.sock = _connect_public(self.host, self.port, self.timeout)


class _PublicHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int | None, timeout: float) -> None:
        self._public_context = ssl.create_default_context()
        super().__init__(host, port, timeout=timeout, context=self._public_context)

    def connect(self) -> None:
        raw = _connect_public(self.host, self.port, self.timeout)
        try:
            self.sock = self._public_context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def _validate_url(url: str) -> SplitResult:
    if any(ord(ch) <= 0x20 or ord(ch) == 0x7F for ch in url):
        raise HttpBlocked("The URL contains control characters or spaces.")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise HttpBlocked("The URL is malformed.") from exc
    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        raise HttpBlocked("Only http and https URLs are allowed.")
    if not parts.hostname:
        raise HttpBlocked("The URL has no host.")
    if parts.username is not None or parts.password is not None:
        raise HttpBlocked("URLs with embedded credentials are not allowed.")
    if port not in _ALLOWED_PORTS:
        raise HttpBlocked("Only the standard web ports are allowed.")
    return parts


def _open(parts: SplitResult, method: str, headers: Mapping[str, str], body: bytes | None, timeout: float):
    """Send one request and return ``(connection, response)``. Tests replace this."""
    target = quote(parts.path or "/", safe="/%:@!$&'()*+,;=~-._")
    if parts.query:
        target += "?" + quote(parts.query, safe="/%:@!$&'()*+,;=~-._?")
    # The port is always passed, because http.client would read part of an IPv6 address as a port.
    connection: http.client.HTTPConnection
    if parts.scheme.lower() == "https":
        connection = _PublicHTTPSConnection(parts.hostname, parts.port or 443, timeout)
    else:
        connection = _PublicHTTPConnection(parts.hostname, parts.port or 80, timeout=timeout)
    try:
        connection.request(method, target, body=body, headers=dict(headers))
        return connection, connection.getresponse()
    except BaseException:
        connection.close()
        raise


def _read_limited(response, max_bytes: int, deadline: float) -> bytes:
    declared = response.getheader("Content-Length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise HttpFailed("too_large")
    chunks: list[bytes] = []
    total = 0
    while True:
        if time.monotonic() > deadline:
            raise HttpFailed("timeout")
        # read1 returns after one read, so a slow sender cannot outrun the deadline.
        chunk = response.read1(_READ_SIZE)
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > max_bytes:
            raise HttpFailed("too_large")
        chunks.append(chunk)


def _decode(data: bytes, encoding: str | None, max_bytes: int) -> bytes:
    encoding = (encoding or "identity").strip().lower()
    if encoding == "identity":
        return data
    if encoding not in {"gzip", "x-gzip"}:
        raise HttpFailed("decode")
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        output = decoder.decompress(data, max_bytes + 1)
    except zlib.error as exc:
        raise HttpFailed("decode") from exc
    if len(output) > max_bytes or decoder.unconsumed_tail:
        raise HttpFailed("too_large")
    return output


def safe_request(
    url: str,
    *,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
    body: bytes | None = None,
    timeout_s: float = 5.0,
    max_bytes: int = 2 * 1024 * 1024,
    deadline: float | None = None,
    max_redirects: int = 3,
) -> HttpResponse:
    """Fetch a URL within the safety rules. Raises HttpBlocked or HttpFailed.

    Exceptions never carry the URL, because provider URLs can contain keys.
    """
    limit = time.monotonic() + timeout_s * (max_redirects + 1) if deadline is None else deadline
    sent = {"Accept-Encoding": "identity", "Connection": "close", **(headers or {})}
    current = url
    for _ in range(max_redirects + 1):
        parts = _validate_url(current)
        remaining = limit - time.monotonic()
        if remaining <= 0:
            raise HttpFailed("timeout")
        connection = None
        try:
            connection, response = _open(parts, method, sent, body, min(timeout_s, remaining))
            location = response.getheader("Location")
            if response.status in _REDIRECTS and location and max_redirects > 0:
                current = urljoin(current, location)
                continue
            data = _read_limited(response, max_bytes, limit)
            lowered = {name.lower(): value for name, value in response.getheaders()}
            return HttpResponse(
                url=current,
                status=response.status,
                headers=lowered,
                body=_decode(data, lowered.get("content-encoding"), max_bytes),
            )
        except (TimeoutError, socket.timeout) as exc:
            raise HttpFailed("timeout") from exc
        except (OSError, http.client.HTTPException, UnicodeError, ValueError) as exc:
            raise HttpFailed("network") from exc
        finally:
            if connection is not None:
                connection.close()
    raise HttpBlocked("The URL redirected too many times.")


RequestFunction = Callable[..., HttpResponse]
