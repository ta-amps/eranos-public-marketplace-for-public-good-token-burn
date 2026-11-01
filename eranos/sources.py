"""Permitted public sources for research verbs: check the address, fetch it, extract its text.

Only two kinds of address are fetched: the request's own https links, and query or document URLs on
the allowlist of official open APIs in the `eranos.instructions/worker` noun. Nothing is crawled, no
form is submitted, no login and no proxy are used. Every address must be https on port 443 and
resolve only to public IP addresses (address-translation prefixes count as internal), and the
connection goes to the address that was checked, so a link in a public request cannot reach this
machine or its network, even by changing its DNS answer between the check and the connection.

Text extraction is deliberately simple and documented, so an independent checker can repeat it:
- HTML: drop `script`, `style`, `noscript`, `template`, `svg` and `head` content except `title`;
  block-level tags end a line; entities are decoded; whitespace inside a line collapses to one space.
- JSON: every string value, in document order, on its own line.
- Plain text: as served, with the same whitespace rule.
Standard library only.
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote_plus, urljoin, urlsplit

EXTRACTOR = "eranos-text-v1"
USER_AGENT = "eranos-volunteer-worker/0.1 (+https://eranos.ta-amps.workers.dev)"
TEXT_TYPES = ("text/html", "application/xhtml+xml", "text/plain", "application/json")
BLOCK_TAGS = frozenset(
    [
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    ]
)
SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "svg", "head"})
_SPACE = re.compile(r"[ \t\f\v\r\xa0]+")


class SourceRefused(ValueError):
    """The address is not one this worker may fetch; nothing was requested."""


class FetchFailed(RuntimeError):
    """The address was permitted but the fetch did not return usable public text."""


@dataclass(frozen=True)
class SourcePolicy:
    """Fetch limits. `deadline_seconds` bounds a whole fetch, redirects included; `timeout_seconds`
    bounds each socket operation. `allow_private` and `allow_http_hosts` exist only for tests."""

    max_bytes: int = 2_000_000
    timeout_seconds: float = 10.0
    deadline_seconds: float = 30.0
    max_redirects: int = 3
    allow_private: bool = False
    allow_http_hosts: frozenset[str] = field(default_factory=frozenset)


def policy_from_rules(rules: dict[str, Any]) -> SourcePolicy:
    """The fetch limits the `eranos.instructions/worker` noun sets, within this module's ceilings."""
    sources = rules.get("sources") or {}
    return SourcePolicy(
        max_bytes=min(int(sources.get("max_bytes") or 2_000_000), 4_000_000),
        timeout_seconds=min(float(sources.get("timeout_seconds") or 10.0), 30.0),
        deadline_seconds=min(float(sources.get("deadline_seconds") or 30.0), 120.0),
    )


@dataclass(frozen=True)
class Fetched:
    url: str
    final_url: str
    status: int
    content_type: str
    raw: bytes
    fetched_at: float


# Address-translation prefixes can carry an internal IPv4 address inside a "global" IPv6 address.
_TRANSLATED = tuple(
    ipaddress.ip_network(n) for n in ("64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32")
)


def _is_public(text: str) -> bool:
    address = ipaddress.ip_address(text.split("%", 1)[0])
    if not address.is_global or address.is_multicast:
        return False
    return not (address.version == 6 and any(address in net for net in _TRANSLATED))


def _resolve_public(host: str) -> str | None:
    """The address to connect to, when every address the host resolves to is public."""
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return None
    addresses = [str(info[4][0]) for info in infos]
    if not addresses or not all(_is_public(a) for a in addresses):
        return None
    return addresses[0]


def check_address(url: str, policy: SourcePolicy) -> str:
    """The checked IP address to connect to; SourceRefused unless the URL may be fetched."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.username or parts.password:
        raise SourceRefused("addresses with credentials are never fetched")
    netloc = f"{host}:{parts.port}" if parts.port else host
    if parts.scheme == "http" and netloc in policy.allow_http_hosts:
        return host
    if parts.scheme != "https" or not host:
        raise SourceRefused("only https addresses are fetched")
    if parts.port not in (None, 443):
        raise SourceRefused("only the standard https port is fetched")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise SourceRefused("addresses must name a host, not an IP address")
    if policy.allow_private:
        return host
    address = _resolve_public(host)
    if address is None:
        raise SourceRefused(f"{host} does not resolve only to public addresses")
    return address


class _Pinned(http.client.HTTPSConnection):
    """An https connection to the address that was checked, with SNI and Host set to the name."""

    def __init__(self, host: str, address: str, timeout: float) -> None:
        self._tls = ssl.create_default_context()
        super().__init__(host, 443, timeout=timeout, context=self._tls)
        self._address = address

    def connect(self) -> None:
        sock = socket.create_connection((self._address, 443), timeout=self.timeout)
        peer = str(sock.getpeername()[0])
        if peer != self._address:
            sock.close()
            raise SourceRefused("the connection reached a different address than the one checked")
        self.sock = self._tls.wrap_socket(sock, server_hostname=self.host)


def _connection(url: str, address: str, timeout: float) -> http.client.HTTPConnection:
    parts = urlsplit(url)
    if parts.scheme == "http":  # test fixtures only (SourcePolicy.allow_http_hosts)
        return http.client.HTTPConnection(parts.hostname or "", parts.port or 80, timeout=timeout)
    return _Pinned(parts.hostname or "", address, timeout)


def fetch(url: str, policy: SourcePolicy) -> Fetched:
    """GET one permitted address within one total deadline; every redirect is checked again.

    No proxy is used (http.client reads no proxy settings); the type is checked before the body
    is read; the body is read in pieces against the deadline and the size cap.
    """
    deadline = time.monotonic() + policy.deadline_seconds
    current = url
    for _ in range(policy.max_redirects + 1):
        address = check_address(current, policy)
        parts = urlsplit(current)
        host = parts.hostname or "?"
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        conn = _connection(
            current, address, min(policy.timeout_seconds, max(0.1, deadline - time.monotonic()))
        )
        try:
            conn.request(
                "GET",
                path,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": ", ".join(TEXT_TYPES),
                    "Accept-Encoding": "identity",
                },
            )
            response = conn.getresponse()
            if response.status in (301, 302, 303, 307, 308) and response.getheader("location"):
                current = urljoin(current, str(response.getheader("location")))
                continue
            if response.status >= 400:
                raise FetchFailed(f"{host} answered {response.status}")
            content_type = str(response.getheader("content-type") or "").lower()
            if not any(content_type.startswith(t) for t in TEXT_TYPES):
                raise FetchFailed(f"{host} sent {content_type or 'no type'}")
            declared = response.getheader("content-length")
            if declared and declared.isdigit() and int(declared) > policy.max_bytes:
                raise FetchFailed(f"{host} would send more than {policy.max_bytes} bytes")
            chunks: list[bytes] = []
            size = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise FetchFailed(f"{host} took longer than {policy.deadline_seconds:.0f} s")
                if conn.sock is not None:
                    conn.sock.settimeout(min(policy.timeout_seconds, remaining))
                chunk = (
                    response.read1(65536) if hasattr(response, "read1") else response.read(65536)
                )
                if not chunk:
                    break
                size += len(chunk)
                if size > policy.max_bytes:
                    raise FetchFailed(f"{host} sent more than {policy.max_bytes} bytes")
                chunks.append(chunk)
            return Fetched(
                url, current, int(response.status), content_type, b"".join(chunks), time.time()
            )
        except (OSError, http.client.HTTPException) as exc:
            raise FetchFailed(f"{host} could not be reached ({type(exc).__name__})") from exc
        finally:
            conn.close()
    raise FetchFailed("too many redirects")


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = [""]
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        elif tag in SKIP_TAGS:
            self._skip += 1
        elif tag in BLOCK_TAGS:
            self.lines.append("")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in BLOCK_TAGS:
            self.lines.append("")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag in SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in BLOCK_TAGS:
            self.lines.append("")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.lines[-1] += data


def _lines(text: str) -> str:
    out = [_SPACE.sub(" ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in out if line)


def _json_strings(value: Any, out: list[str]) -> None:
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            _json_strings(item, out)
    elif isinstance(value, list):
        for item in value:
            _json_strings(item, out)


def _charset(content_type: str) -> str:
    match = re.search(r"charset=([\w.-]+)", content_type)
    return match.group(1) if match else "utf-8"


def extract_text(content_type: str, raw: bytes) -> tuple[str, str]:
    """(title, text) of a fetched body, by the documented rules above."""
    try:
        decoded = raw.decode(_charset(content_type), errors="replace")
    except LookupError:
        decoded = raw.decode("utf-8", errors="replace")
    if content_type.startswith("application/json"):
        strings: list[str] = []
        _json_strings(json.loads(decoded), strings)
        return "", _lines("\n".join(s.replace("\n", " ") for s in strings))
    if content_type.startswith("text/plain"):
        return "", _lines(decoded)
    parser = _Text()
    parser.feed(decoded)
    parser.close()
    return _lines(parser.title.replace("\n", " ")), _lines("\n".join(parser.lines))


def sha256_hex(data: bytes | str) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def api_query_url(api: dict[str, Any], terms: list[str]) -> str:
    return str(api["query"]).replace("{terms}", quote_plus(" ".join(terms)))


def permitted_api(url: str, apis: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The allowlisted official API an https URL belongs to, by exact host and path prefix."""
    parts = urlsplit(url)
    for api in apis:
        same_host = parts.scheme == "https" and (parts.hostname or "").lower() == api["host"]
        if same_host and any(parts.path.startswith(p) for p in api.get("path_prefixes") or []):
            return api
    return None


def source_record(
    fetched: Fetched,
    *,
    source_id: str,
    access: str,
    publisher: str | None,
    max_text_chars: int,
    request_id: str,
    part: Any,
) -> dict[str, Any]:
    """A source noun: where it came from, when, its digests, and the extracted text it may cite."""
    title, text = extract_text(fetched.content_type, fetched.raw)
    host = (urlsplit(fetched.final_url).hostname or "").lower()
    kept = text[:max_text_chars]
    return {
        "schema_version": 1,
        "id": source_id,
        "title": (title or host)[:300],
        "publisher": (publisher or host)[:200],
        "url": fetched.url,
        "final_url": fetched.final_url,
        "access": access,
        "public": True,
        "made_up_sample": False,
        "fetched_at": round(fetched.fetched_at, 3),
        "http_status": fetched.status,
        "content_type": fetched.content_type[:100],
        "raw_sha256": sha256_hex(fetched.raw),
        "text_sha256": sha256_hex(kept),
        "extractor": EXTRACTOR,
        "chars": len(kept),
        "truncated": len(text) > len(kept),
        "text": kept,
        "request_id": request_id,
        "part": part,
    }
