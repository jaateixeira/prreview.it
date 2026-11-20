"""Checks a web page before it goes to reviewers (ADR 0022).

Fetching an address someone typed is how servers get tricked into reading their own
network, so the checker:

- applies the address rules (`normalise_address`) to what was typed;
- resolves every host itself and connects only to the address it checked, so a name that
  points inside a private network is refused at connect time, also after a redirect and also
  when the name changes its answer between two lookups;
- uses the usual web ports only, follows at most five redirects, ignores proxy settings in the
  environment, and gives up after a few seconds;
- reads at most the first 256 kB of an HTML page, for the title, and never the body of
  anything else.

For an AI review (ADR 0025) it reads the words of a page, with the same rules: at most 2 MB
of HTML or plain text, within 20 seconds.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from html.parser import HTMLParser
from typing import Any
from urllib.parse import unquote, urlsplit

import httpcore
import httpx

from previewit.application.web_pages import (
    NOT_PUBLIC,
    PORTS,
    PageCheck,
    PageChecker,
    PageReader,
    PageUnreachable,
    host_of,
    is_public,
    normalise_address,
)

MAX_REDIRECTS = 5
MAX_HEAD_BYTES = 256_000
TIMEOUT_SECONDS = 6.0
DEADLINE_SECONDS = 10.0  # for the whole check, however slowly the bytes drip in
HTML_TYPES = {"text/html", "application/xhtml+xml"}
MAX_PAGE_BYTES = 2_000_000  # read for an AI review
READ_DEADLINE_SECONDS = 20.0
MAX_TEXT_CHARS = 400_000

Resolve = Callable[[str, int], list[tuple[str, int]]]
Allowed = Callable[[ipaddress.IPv4Address | ipaddress.IPv6Address], bool]


class _NotPublic(Exception):
    pass


class _OddPort(Exception):
    pass


class _HostNotFound(Exception):
    pass


def resolve(host: str, port: int) -> list[tuple[str, int]]:
    """Every address the name has, in the order the system prefers."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as problem:
        raise _HostNotFound(host) from problem
    found: list[tuple[str, int]] = []
    for info in infos:
        pair = (str(info[4][0]), port)
        if pair not in found:
            found.append(pair)
    return found


class _PublicOnly(httpcore.SyncBackend):
    """Connects to a host only after checking every address its name resolves to."""

    def __init__(self, resolve: Resolve, allowed: Allowed) -> None:
        self._resolve = resolve
        self._allowed = allowed

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.NetworkStream:
        if port not in PORTS.values():
            raise _OddPort(port)
        addresses = self._resolve(host, port)
        if not addresses:
            raise _HostNotFound(host)
        for ip, _ in addresses:
            if not self._allowed(ipaddress.ip_address(ip.split("%")[0])):
                raise _NotPublic(ip)  # any private answer: refuse the name altogether
        problem: Exception | None = None
        for ip, real_port in addresses:  # TLS still checks the certificate against `host`
            try:
                return super().connect_tcp(ip, real_port, timeout, local_address, socket_options)
            except httpcore.ConnectError as error:
                problem = error
        assert problem is not None
        raise problem


class _PinnedTransport(httpx.HTTPTransport):
    def __init__(self, backend: httpcore.NetworkBackend) -> None:
        super().__init__(trust_env=False)
        self._pool = httpcore.ConnectionPool(
            ssl_context=httpx.create_ssl_context(trust_env=False),
            max_connections=2,
            max_keepalive_connections=0,
            network_backend=backend,
        )


class HttpPageChecker:
    def __init__(
        self,
        *,
        user_agent: str,
        resolve: Resolve = resolve,
        allowed: Allowed = is_public,
        timeout: float = TIMEOUT_SECONDS,
        deadline: float = DEADLINE_SECONDS,
    ) -> None:
        self._user_agent = user_agent
        self._resolve = resolve
        self._allowed = allowed
        self._timeout = timeout
        self._deadline = deadline

    def check(self, address: str) -> PageCheck:
        url = normalise_address(address)
        started = time.monotonic()
        accept = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"
        with self._fetching(), self._client(accept) as client, client.stream("GET", url) as got:
            return self._read(url, got, started)

    def read_text(self, address: str) -> str:
        """The words of a page, for an AI review (ADR 0025)."""
        url = normalise_address(address)
        started = time.monotonic()
        accept = "text/html,application/xhtml+xml,text/plain;q=0.9"
        with self._fetching(), self._client(accept) as client, client.stream("GET", url) as got:
            status = got.status_code
            if status == 401:
                raise PageUnreachable("The page now asks for a login, so it cannot be read.")
            if status in (404, 410):
                raise PageUnreachable(f"The page is gone (answer {status}).")
            if not 200 <= status < 300:
                raise PageUnreachable(f"The site did not show the page (answer {status}).")
            media_type = got.headers.get("content-type", "").split(";")[0].strip().lower()
            if media_type not in HTML_TYPES and media_type != "text/plain":
                raise PageUnreachable(
                    "AI models can read web pages and plain text; this address gives a file "
                    f"({media_type or 'of unknown type'})."
                )
            body = bytearray()
            for chunk in got.iter_bytes():
                body += chunk
                if len(body) >= MAX_PAGE_BYTES:
                    break
                if time.monotonic() - started > READ_DEADLINE_SECONDS:
                    raise PageUnreachable("The site took too long to send the page.")
            data = bytes(body[:MAX_PAGE_BYTES])
            if media_type == "text/plain":
                return data.decode(got.charset_encoding or "utf-8", errors="replace")[
                    :MAX_TEXT_CHARS
                ]
            return page_text(data, got.charset_encoding)

    def _client(self, accept: str) -> httpx.Client:
        return httpx.Client(
            transport=_PinnedTransport(_PublicOnly(self._resolve, self._allowed)),
            follow_redirects=True,
            max_redirects=MAX_REDIRECTS,
            timeout=httpx.Timeout(self._timeout),
            trust_env=False,
            headers={"User-Agent": self._user_agent, "Accept": accept},
        )

    @contextmanager
    def _fetching(self) -> Iterator[None]:
        """Turns what can go wrong on the way to a page into a reason for the person."""
        try:
            yield
        except _NotPublic:
            raise PageUnreachable(NOT_PUBLIC) from None
        except _OddPort:
            raise PageUnreachable(
                "The page sends visitors to an unusual port, which Previewit does not open."
            ) from None
        except _HostNotFound:
            raise PageUnreachable(
                "Previewit could not find that site. Check the address."
            ) from None
        except httpx.TooManyRedirects:
            raise PageUnreachable("The page redirects too many times.") from None
        except httpx.TimeoutException:
            raise PageUnreachable("The site took too long to answer. Try again later.") from None
        except httpx.ConnectError as error:
            if "CERTIFICATE" in str(error).upper():
                raise PageUnreachable(
                    "The site's security certificate is not valid, so browsers would warn "
                    "reviewers away from it."
                ) from None
            raise PageUnreachable("Previewit could not connect to that site.") from None
        except httpx.HTTPError:
            raise PageUnreachable("Previewit could not read that page.") from None

    def _read(self, url: str, response: httpx.Response, started: float) -> PageCheck:
        status = response.status_code
        final = str(response.url)
        media_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if status == 401:
            raise PageUnreachable(
                "The page asks for a login. Reviewers need a page anyone can open: use a public "
                "address."
            )
        if status in (404, 410):
            raise PageUnreachable(f"That page was not found (answer {status}). Check the address.")
        if status in (403, 429):  # often a guard against robots; a person may still get in
            return PageCheck(
                url, final, "", "", host_of(final), media_type,
                note="The site did not let Previewit look at the page. Open it yourself to be "
                "sure reviewers can.",
            )  # fmt: skip
        if status >= 500:
            raise PageUnreachable(
                f"The site has a problem right now (answer {status}). Try again later."
            )
        if not 200 <= status < 300:
            raise PageUnreachable(f"The site did not show the page (answer {status}).")
        if media_type not in HTML_TYPES:
            name = unquote(urlsplit(final).path.rstrip("/").rsplit("/", 1)[-1])
            return PageCheck(url, final, _clip(name, 200), "", host_of(final), media_type)
        head = bytearray()
        for chunk in response.iter_bytes():
            head += chunk
            if len(head) >= MAX_HEAD_BYTES or b"</head>" in head[-len(chunk) - 7 :].lower():
                break
            if time.monotonic() - started > self._deadline:
                break
        title, description, site = read_preview(
            bytes(head[:MAX_HEAD_BYTES]), response.charset_encoding
        )
        return PageCheck(url, final, title, description, site or host_of(final), media_type)


class RecentChecks:
    """Remembers successful checks for a few minutes, so the live check while typing and the
    check on submit fetch the page once."""

    def __init__(
        self,
        inner: PageChecker,
        *,
        seconds: float = 300.0,
        size: int = 256,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        self._seconds = seconds
        self._size = size
        self._clock = clock
        self._seen: OrderedDict[str, tuple[float, PageCheck]] = OrderedDict()
        self._lock = threading.Lock()  # requests run in several threads

    def check(self, address: str) -> PageCheck:
        key = normalise_address(address)
        now = self._clock()
        with self._lock:
            hit = self._seen.get(key)
        if hit is not None and now - hit[0] < self._seconds:
            return hit[1]
        found = self._inner.check(key)  # outside the lock: a slow site must not hold up others
        with self._lock:
            self._seen[key] = (now, found)
            self._seen.move_to_end(key)
            while len(self._seen) > self._size:
                self._seen.popitem(last=False)
        return found

    def read_text(self, address: str) -> str:
        """Not remembered: an AI review reads the page as it is when the review is written."""
        if not isinstance(self._inner, PageReader):
            raise PageUnreachable("This Previewit cannot read web pages.")
        return self._inner.read_text(address)


# -- the preview: title, description and site name from the head of an HTML page ---------------

_META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?([A-Za-z0-9_\-]+)""", re.I)


def read_preview(head: bytes, charset: str | None = None) -> tuple[str, str, str]:
    """(title, description, site name) from the start of an HTML page. Empty when absent."""
    encoding = charset
    if encoding is None:
        found = _META_CHARSET.search(head[:4096])
        encoding = found.group(1).decode("ascii") if found else "utf-8"
    try:
        text = head.decode(encoding, errors="replace")
    except LookupError:
        text = head.decode("utf-8", errors="replace")
    parser = _HeadParser()
    try:
        parser.feed(text)
        parser.close()
    except AssertionError:  # html.parser gives up on some broken markup; keep what it found
        pass
    title = parser.meta.get("og:title") or parser.title
    description = parser.meta.get("og:description") or parser.meta.get("description", "")
    return (
        _clip(title, 200),
        _clip(description, 300),
        _clip(parser.meta.get("og:site_name", ""), 80),
    )


def _clip(text: str, limit: int) -> str:
    clean = " ".join(text.split())
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


class _HeadParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta: dict[str, str] = {}
        self._in_title = False
        self._done = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._done:
            return
        if tag == "title" and not self.title:
            self._in_title = True
        elif tag == "meta":
            values = {k.lower(): (v or "") for k, v in attrs}
            name = (values.get("property") or values.get("name") or "").lower()
            if name in ("og:title", "og:description", "og:site_name", "description"):
                self.meta.setdefault(name, values.get("content", ""))
        elif tag == "body":
            self._done = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "head":
            self._done = True

    def handle_data(self, data: str) -> None:
        if self._in_title and not self._done:
            self.title += data


# -- the words of a page, for an AI review (ADR 0025) ------------------------------------------

_SKIPPED = {"script", "style", "noscript", "template", "svg", "head", "iframe", "canvas"}
_BLOCKS = {
    "p", "div", "br", "li", "ul", "ol", "tr", "td", "th", "table", "section", "article", "main",
    "header", "footer", "aside", "nav", "blockquote", "pre", "figure", "figcaption", "dt", "dd",
    "h1", "h2", "h3", "h4", "h5", "h6", "hr", "form",
}  # fmt: skip


def page_text(html: bytes, charset: str | None = None) -> str:
    """The visible words of an HTML page, one block a line. Scripts and styles are left out."""
    encoding = charset
    if encoding is None:
        found = _META_CHARSET.search(html[:4096])
        encoding = found.group(1).decode("ascii") if found else "utf-8"
    try:
        markup = html.decode(encoding, errors="replace")
    except LookupError:
        markup = html.decode("utf-8", errors="replace")
    parser = _TextParser()
    try:
        parser.feed(markup)
        parser.close()
    except AssertionError:  # html.parser gives up on some broken markup; keep what it found
        pass
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    text = "\n".join(line for line in lines if line)
    return text[:MAX_TEXT_CHARS]


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skipping = 0
        self._pre = 0  # inside <pre>, line breaks are the author's

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED:
            self._skipping += 1
        elif tag in _BLOCKS:
            self.parts.append("\n")
            self._pre += tag == "pre"

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED:
            self._skipping = max(self._skipping - 1, 0)
        elif tag in _BLOCKS:
            self.parts.append("\n")
            self._pre = max(self._pre - (tag == "pre"), 0)

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.parts.append(data if self._pre else re.sub(r"\s+", " ", data))
