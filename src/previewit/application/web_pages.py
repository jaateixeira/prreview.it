"""Web pages under review (ADR 0022): the rules for an address and the port that checks a page.

An author can give the address of a public web page instead of a file. Before the page goes
to reviewers, Previewit checks it can reach it and reads its title for a preview. The rules
here need no network; an adapter does the fetching, with the same rules applied again to the
address it really connects to.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from urllib.parse import urlsplit, urlunsplit

MAX_ADDRESS_LENGTH = 2000
PORTS = {"http": 80, "https": 443}  # only the usual web ports: nothing else is a web page
PRIVATE_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa", ".intranet")

NOT_PUBLIC = (
    "That address is not on the public internet, so reviewers could not open it. Use the "
    "address of a page anyone can open."
)


class PageUnreachable(ValueError):
    """The page cannot go to reviewers. The message says why, in words for the person."""


@dataclass(frozen=True)
class PageCheck:
    """What Previewit found at an address when it checked it."""

    address: str  # tidied: what reviewers open
    final_address: str  # where redirects led
    title: str  # "" when the page has none
    description: str
    site_name: str  # the site's own name, else its host
    media_type: str  # e.g. "text/html"
    note: str = ""  # a warning for the person; the check still passed


class PageChecker(Protocol):
    def check(self, address: str) -> PageCheck:
        """Reach the page and read its preview. Raise PageUnreachable with the reason."""
        ...


@runtime_checkable
class PageReader(Protocol):
    """Reads the words of a public page, for an AI review (ADR 0025)."""

    def read_text(self, address: str) -> str:
        """The page's visible text. Raise PageUnreachable with the reason."""
        ...


def is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for an address on the public internet. IPv4 addresses inside IPv6 forms (mapped,
    6to4, Teredo, NAT64) are judged by the IPv4 address they carry."""
    if isinstance(ip, ipaddress.IPv6Address):
        inner = ip.ipv4_mapped or ip.sixtofour or (ip.teredo[1] if ip.teredo else None)
        if inner is None and ip in ipaddress.IPv6Network("64:ff9b::/96"):
            inner = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
        if inner is not None:
            return is_public(inner)
    return ip.is_global and not ip.is_multicast and not ip.is_reserved


def normalise_address(typed: str) -> str:
    """The address tidied (scheme and host in lower case, IDNA host, default port dropped), or
    PageUnreachable when it cannot be a public web page."""
    text = typed.strip()
    if not text:
        raise PageUnreachable("Paste the address of the web page.")
    if len(text) > MAX_ADDRESS_LENGTH:
        raise PageUnreachable("That address is too long.")
    if "://" not in text and not text.lower().startswith(("javascript:", "data:", "mailto:")):
        text = "https://" + text  # people paste "example.org/page"
    cannot_read = PageUnreachable("Previewit cannot read that address. Check it and try again.")
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        raise cannot_read from None
    scheme = parts.scheme.lower()
    if scheme not in PORTS:
        raise PageUnreachable("Use the address of a web page: one that starts with https://.")
    if "@" in parts.netloc:
        raise PageUnreachable("Leave the user name and password out of the address.")
    host = (parts.hostname or "").rstrip(".")
    if not host or any(c.isspace() for c in parts.netloc):
        raise cannot_read
    if port is not None and port != PORTS[scheme]:
        raise PageUnreachable(
            "Previewit opens web pages on the usual ports only (80 and 443). Use the page's "
            "usual address."
        )
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if not is_public(ip):
            raise PageUnreachable(NOT_PUBLIC)
        netloc = f"[{ip.compressed}]" if ip.version == 6 else ip.compressed
    else:
        try:
            netloc = host.encode("idna").decode("ascii").lower()
        except UnicodeError:
            raise cannot_read from None
        if "." not in netloc or netloc == "localhost" or netloc.endswith(PRIVATE_SUFFIXES):
            raise PageUnreachable(NOT_PUBLIC)
    path = parts.path or "/"
    return urlunsplit((scheme, netloc, path, parts.query, parts.fragment))


def host_of(address: str) -> str:
    """The host part, for showing ("example.org")."""
    return (urlsplit(address).hostname or "").removeprefix("www.")
