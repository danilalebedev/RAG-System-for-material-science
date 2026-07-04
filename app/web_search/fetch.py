from __future__ import annotations

import ipaddress
import io
import socket
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

from app.web_search.clients import compact_text


PRIVATE_HOSTS = {"localhost", "localhost.localdomain"}
MAX_FETCH_BYTES = 400_000


@dataclass(frozen=True)
class FetchedExcerpt:
    url: str
    text: str
    content_type: str | None
    bytes_read: int
    error: str | None = None


Resolver = Callable[[str, int | None], list[Any]]


def _default_resolver(host: str, port: int | None) -> list[Any]:
    return socket.getaddrinfo(host, port or 443, type=socket.SOCK_STREAM)


def _ip_is_blocked(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def is_safe_external_url(url: str, *, resolver: Resolver = _default_resolver) -> tuple[bool, str | None]:
    parsed = urlparse(str(url or ""))
    if parsed.scheme.lower() != "https":
        return False, "only https URLs are allowed"
    if not parsed.hostname:
        return False, "URL has no hostname"
    if parsed.username or parsed.password:
        return False, "URL userinfo is not allowed"
    host = parsed.hostname.lower().rstrip(".")
    if host in PRIVATE_HOSTS:
        return False, "private host is not allowed"
    try:
        if _ip_is_blocked(host):
            return False, "private IP address is not allowed"
    except ValueError:
        pass
    try:
        records = resolver(host, parsed.port)
    except OSError as exc:
        return False, f"DNS resolution failed: {exc}"
    for record in records:
        address = record[4][0]
        try:
            if _ip_is_blocked(address):
                return False, "resolved private IP address is not allowed"
        except ValueError:
            return False, "resolved non-IP address is not allowed"
    return True, None


def _text_from_pdf(data: bytes, *, max_chars: int) -> str:
    reader = PdfReader(io.BytesIO(data))
    texts: list[str] = []
    for page in reader.pages[:3]:
        texts.append(page.extract_text() or "")
        if sum(len(text) for text in texts) >= max_chars:
            break
    return compact_text(" ".join(texts), max_chars)


def _text_from_html(data: bytes, *, max_chars: int) -> str:
    soup = BeautifulSoup(data, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return compact_text(soup.get_text(" "), max_chars)


def safe_fetch_excerpt(
    url: str,
    *,
    session: requests.Session | None = None,
    timeout_seconds: int = 12,
    max_bytes: int = MAX_FETCH_BYTES,
    max_chars: int = 12_000,
    max_redirects: int = 3,
    resolver: Resolver = _default_resolver,
) -> FetchedExcerpt:
    ok, reason = is_safe_external_url(url, resolver=resolver)
    if not ok:
        return FetchedExcerpt(url=url, text="", content_type=None, bytes_read=0, error=reason)

    client = session or requests.Session()
    current_url = url
    for _ in range(max_redirects + 1):
        try:
            response = client.get(current_url, timeout=timeout_seconds, stream=True, allow_redirects=False)
        except requests.RequestException as exc:
            return FetchedExcerpt(url=current_url, text="", content_type=None, bytes_read=0, error=f"fetch failed: {exc}")
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("Location")
            if not location:
                return FetchedExcerpt(url=current_url, text="", content_type=None, bytes_read=0, error="redirect without location")
            next_url = requests.compat.urljoin(current_url, location)
            ok, reason = is_safe_external_url(next_url, resolver=resolver)
            if not ok:
                return FetchedExcerpt(url=next_url, text="", content_type=None, bytes_read=0, error=reason)
            current_url = next_url
            continue
        if response.status_code >= 400:
            return FetchedExcerpt(
                url=current_url,
                text="",
                content_type=response.headers.get("Content-Type"),
                bytes_read=0,
                error=f"HTTP {response.status_code}",
            )
        chunks: list[bytes] = []
        bytes_read = 0
        try:
            for chunk in response.iter_content(chunk_size=16_384):
                if not chunk:
                    continue
                bytes_read += len(chunk)
                if bytes_read > max_bytes:
                    return FetchedExcerpt(
                        url=current_url,
                        text="",
                        content_type=response.headers.get("Content-Type"),
                        bytes_read=bytes_read,
                        error="payload exceeds size cap",
                    )
                chunks.append(chunk)
        except requests.RequestException as exc:
            return FetchedExcerpt(
                url=current_url,
                text="",
                content_type=response.headers.get("Content-Type"),
                bytes_read=bytes_read,
                error=f"fetch failed: {exc}",
            )
        data = b"".join(chunks)
        content_type = response.headers.get("Content-Type", "").lower()
        try:
            if "pdf" in content_type or current_url.lower().split("?")[0].endswith(".pdf"):
                text = _text_from_pdf(data, max_chars=max_chars)
            elif "html" in content_type or "xml" in content_type or not content_type:
                text = _text_from_html(data, max_chars=max_chars)
            elif "text/" in content_type:
                text = compact_text(data.decode(response.encoding or "utf-8", errors="ignore"), max_chars)
            else:
                return FetchedExcerpt(
                    url=current_url,
                    text="",
                    content_type=content_type,
                    bytes_read=bytes_read,
                    error=f"unsupported content type: {content_type}",
                )
        except Exception as exc:  # noqa: BLE001 - excerpt extraction should be best-effort.
            return FetchedExcerpt(
                url=current_url,
                text="",
                content_type=content_type,
                bytes_read=bytes_read,
                error=f"excerpt extraction failed: {exc}",
            )
        return FetchedExcerpt(url=current_url, text=text, content_type=content_type, bytes_read=bytes_read)
    return FetchedExcerpt(url=current_url, text="", content_type=None, bytes_read=0, error="too many redirects")

