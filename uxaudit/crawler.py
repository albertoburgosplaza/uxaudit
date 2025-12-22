from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urldefrag, urlparse


def normalize_url(url: str) -> str:
    cleaned, _ = urldefrag(url)
    parsed = urlparse(cleaned)
    if not parsed.scheme:
        return cleaned
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    normalized = parsed._replace(netloc=netloc, path=path)
    return normalized.geturl()


def filter_links(links: Iterable[str], base_url: str) -> list[str]:
    base = urlparse(base_url)
    base_netloc = base.netloc.lower()
    filtered: list[str] = []
    for link in links:
        if not link:
            continue
        parsed = urlparse(link)
        if parsed.scheme not in {"http", "https"}:
            continue
        if parsed.netloc.lower() != base_netloc:
            continue
        normalized = normalize_url(link)
        if normalized:
            filtered.append(normalized)
    return filtered
