"""Permitted public sources for research verbs: check the address, fetch it, extract its text.

Only two kinds of address are fetched: the request's own https links, and query or document URLs on
the allowlist of official open APIs in the `eranos.instructions/worker` noun. Nothing is crawled, no
form is submitted and no login is used. Every address must be https on port 443 and resolve only to
public IP addresses, so a link in a public request cannot reach this machine or its network.

Text extraction is deliberately simple and documented, so an independent checker can repeat it:
- HTML: drop `script`, `style`, `noscript`, `template`, `svg` and `head` content except `title`;
  block-level tags end a line; entities are decoded; whitespace inside a line collapses to one space.
- JSON: every string value, in document order, on its own line.
- Plain text: as served, with the same whitespace rule.
Standard library only.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
import time
import urllib.error
import urllib.request
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
    """Fetch limits. `allow_private` exists only for tests against a local fixture server."""

    max_bytes: int = 2_000_000
    timeout_seconds: float = 20.0
    max_redirects: int = 3
    allow_private: bool = False
    allow_http_hosts: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class Fetched:
    url: str
    final_url: str
    status: int
    content_type: str
    raw: bytes
    fetched_at: float


def _public_address(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return False
    addresses = {str(info[4][0]) for info in infos}
    for text in addresses:
        address = ipaddress.ip_address(text.split("%", 1)[0])
        if not address.is_global or address.is_multicast:
            return False
    return bool(addresses)


def check_address(url: str, policy: SourcePolicy) -> None:
    """Raise SourceRefused unless the URL is a public https address this worker may fetch."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.username or parts.password:
        raise SourceRefused("addresses with credentials are never fetched")
    netloc = f"{host}:{parts.port}" if parts.port else host
    if parts.scheme == "http" and netloc in policy.allow_http_hosts:
        return
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
    if not policy.allow_private and not _public_address(host):
        raise SourceRefused(f"{host} does not resolve only to public addresses")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def fetch(url: str, policy: SourcePolicy) -> Fetched:
    """GET one permitted address; every redirect target is checked like the first address."""
    opener = urllib.request.build_opener(_NoRedirect)
    current = url
    for _ in range(policy.max_redirects + 1):
        check_address(current, policy)
        request = urllib.request.Request(  # noqa: S310 - check_address allows https only
            current,
            headers={"User-Agent": USER_AGENT, "Accept": ", ".join(TEXT_TYPES)},
            method="GET",
        )
        try:
            response = opener.open(request, timeout=policy.timeout_seconds)
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308) and exc.headers.get("location"):
                current = urljoin(current, exc.headers["location"])
                continue
            raise FetchFailed(f"{urlsplit(current).hostname} answered {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise FetchFailed(f"{urlsplit(current).hostname} could not be reached") from exc
        with response:
            content_type = str(response.headers.get("content-type") or "").lower()
            raw = response.read(policy.max_bytes + 1)
            status = int(response.status)
        if len(raw) > policy.max_bytes:
            raise FetchFailed(
                f"{urlsplit(current).hostname} sent more than {policy.max_bytes} bytes"
            )
        if not any(content_type.startswith(t) for t in TEXT_TYPES):
            raise FetchFailed(f"{urlsplit(current).hostname} sent {content_type or 'no type'}")
        return Fetched(url, current, status, content_type, raw, time.time())
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
        "synthetic": False,
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
