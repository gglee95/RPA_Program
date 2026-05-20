"""Helper to extract Google session cookies from the live nodriver browser
and turn them into a Cookie header string usable with urllib.

We never persist credentials anywhere — cookies stay in memory just long
enough to fetch the sheet CSV and to download Drive files.
"""

from __future__ import annotations

from typing import Iterable

import nodriver as uc


GOOGLE_DOMAINS = (
    "google.com",
    ".google.com",
    "drive.google.com",
    ".drive.google.com",
    "docs.google.com",
    ".docs.google.com",
    "drive.usercontent.google.com",
    ".drive.usercontent.google.com",
)


def _matches(cookie_domain: str, target_domain: str) -> bool:
    """Mimic browser-style cookie domain matching."""
    cd = cookie_domain.lstrip(".")
    td = target_domain.lstrip(".")
    return td == cd or td.endswith("." + cd)


async def cookie_header_for(browser: uc.Browser, target_url: str) -> str:
    """Build a `Cookie:` header value containing every cookie that the browser
    would send to `target_url`.
    """
    from urllib.parse import urlparse

    host = urlparse(target_url).hostname or ""
    cookies = await browser.cookies.get_all()
    parts = []
    seen: set[str] = set()
    for c in cookies:
        domain = (getattr(c, "domain", None) or "").lower()
        if not domain:
            continue
        if not _matches(domain, host):
            continue
        name = getattr(c, "name", None)
        value = getattr(c, "value", None)
        if name is None or value is None:
            continue
        # Last-write-wins on duplicate names
        if name in seen:
            parts = [p for p in parts if not p.startswith(name + "=")]
        parts.append(f"{name}={value}")
        seen.add(name)
    return "; ".join(parts)
