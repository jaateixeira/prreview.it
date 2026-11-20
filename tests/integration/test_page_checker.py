"""The web page checker against a real HTTP server on this machine (ADR 0022).

The pages live at made-up public names (pages.test) that the test resolver points at the local
server. Loopback is allowed only where a test says so: by default the checker must refuse it.
"""

from __future__ import annotations

import contextlib
import ipaddress
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from previewit.adapters.web_pages import HttpPageChecker, RecentChecks, page_text, read_preview
from previewit.application.web_pages import PageCheck, PageUnreachable

PAGES: dict[str, tuple[int, dict[str, str], bytes]] = {
    "/essay": (
        200,
        {"Content-Type": "text/html; charset=utf-8"},
        b"<html><head><title>Ignored  title</title>"
        b'<meta property="og:title" content="On testing &amp; trust">'
        b'<meta name="description" content="A short essay\n about tests.">'
        b'<meta property="og:site_name" content="Sam\'s notes"></head><body>Hi</body></html>',
    ),
    "/plain": (200, {"Content-Type": "text/html"}, b"<title>Just a title</title><p>x"),
    "/article": (
        200,
        {"Content-Type": "text/html; charset=utf-8"},
        b"<html><head><title>T</title><style>p{color:red}</style></head><body>"
        b"<nav>Home | About</nav><h1>On trust</h1><script>alert('no')</script>"
        b"<p>Tests build\n   trust.</p><p>Caf&eacute; <b>notes</b></p></body></html>",
    ),
    "/notes.txt": (
        200,
        {"Content-Type": "text/plain; charset=utf-8"},
        "Plain words, äiti".encode(),
    ),
    "/paper.pdf": (200, {"Content-Type": "application/pdf"}, b"%PDF-1.7 " + b"x" * 1000),
    "/moved": (301, {"Location": "/essay"}, b""),
    "/to-inside": (302, {"Location": "http://inside.test/secret"}, b""),
    "/to-odd-port": (302, {"Location": "http://pages.test:8080/"}, b""),
    "/loop": (302, {"Location": "/loop"}, b""),
    "/gone": (404, {}, b"no"),
    "/login": (401, {}, b"who are you"),
    "/robots-not-welcome": (403, {"Content-Type": "text/html"}, b"<title>Denied</title>"),
    "/broken": (500, {}, b"oops"),
    "/huge": (
        200,
        {"Content-Type": "text/html"},
        b"<html><head>" + b"<!--" + b"x" * 400_000 + b"--><title>Too late</title></head>",
    ),
}


SEEN_AGENTS: list[str] = []


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        SEEN_AGENTS.append(self.headers.get("User-Agent", ""))
        if self.path == "/slow":
            time.sleep(1.5)
        status, headers, body = PAGES.get(self.path, (404, {}, b""))
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(body)  # the checker may stop reading early, on purpose

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture(scope="module")
def port():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()


def checker(port: int, *, allow_loopback: bool = True, timeout: float = 3.0) -> HttpPageChecker:
    names = {"pages.test": "127.0.0.1", "inside.test": "10.0.0.5"}

    def resolve(host: str, _port: int) -> list[tuple[str, int]]:
        if host not in names:
            from previewit.adapters.web_pages import _HostNotFound

            raise _HostNotFound(host)
        return [(names[host], port)]

    def allowed(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        return allow_loopback and ip.is_loopback

    if allow_loopback:
        return HttpPageChecker(
            user_agent="PreviewitTest/1", resolve=resolve, allowed=allowed, timeout=timeout
        )
    return HttpPageChecker(user_agent="PreviewitTest/1", resolve=resolve, timeout=timeout)


def test_the_preview_reads_title_description_and_site(port):
    found = checker(port).check("http://pages.test/essay")
    assert found.address == "http://pages.test/essay"
    assert found.title == "On testing & trust"  # og:title wins over <title>
    assert found.description == "A short essay about tests."
    assert found.site_name == "Sam's notes"
    assert found.media_type == "text/html" and found.note == ""
    assert SEEN_AGENTS[-1] == "PreviewitTest/1"


def test_without_a_site_name_the_host_is_shown(port):
    found = checker(port).check("http://pages.test/plain")
    assert (found.title, found.site_name) == ("Just a title", "pages.test")


def test_a_file_is_named_after_its_address_and_not_downloaded(port):
    found = checker(port).check("http://pages.test/paper.pdf")
    assert (found.title, found.media_type) == ("paper.pdf", "application/pdf")


def test_redirects_are_followed(port):
    found = checker(port).check("http://pages.test/moved")
    assert found.address == "http://pages.test/moved"
    assert found.final_address == "http://pages.test/essay"
    assert found.title == "On testing & trust"


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ("/to-inside", "not on the public internet"),  # a redirect into a private network
        ("/to-odd-port", "unusual port"),
        ("/loop", "redirects too many times"),
        ("/gone", "not found (answer 404)"),
        ("/login", "asks for a login"),
        ("/broken", "problem right now (answer 500)"),
    ],
)
def test_pages_reviewers_could_not_open_are_refused(port, path, reason):
    with pytest.raises(PageUnreachable) as refused:
        checker(port).check(f"http://pages.test{path}")
    assert reason in str(refused.value)


def test_a_site_that_turns_robots_away_passes_with_a_note(port):
    found = checker(port).check("http://pages.test/robots-not-welcome")
    assert "did not let Previewit look" in found.note and found.title == ""


def test_a_public_looking_name_that_points_inside_is_refused(port):
    with pytest.raises(PageUnreachable) as refused:
        checker(port, allow_loopback=False).check("http://pages.test/essay")
    assert "not on the public internet" in str(refused.value)


def test_an_unknown_site_is_reported(port):
    with pytest.raises(PageUnreachable) as refused:
        checker(port).check("http://nowhere.test/")
    assert "could not find that site" in str(refused.value)


def test_a_slow_site_is_given_up_on(port):
    started = time.monotonic()
    with pytest.raises(PageUnreachable) as refused:
        checker(port, timeout=0.3).check("http://pages.test/slow")
    assert "took too long" in str(refused.value)
    assert time.monotonic() - started < 1.4


def test_only_the_head_of_a_huge_page_is_read(port):
    found = checker(port).check("http://pages.test/huge")
    assert found.title == ""  # the title came after the first 256 kB


def test_recent_checks_are_remembered_for_a_while(port):
    now = [0.0]
    calls: list[str] = []

    class Counting:
        def check(self, address: str) -> PageCheck:
            calls.append(address)
            return checker(port).check(address)

    recent = RecentChecks(Counting(), seconds=300, clock=lambda: now[0])
    first = recent.check("http://pages.test/essay")
    assert recent.check("HTTP://Pages.test/essay") == first  # the same address, tidied
    now[0] = 301
    recent.check("http://pages.test/essay")
    assert len(calls) == 2


@pytest.mark.parametrize(
    ("head", "charset", "expected"),
    [
        (b"<title> A\n  title </title>", None, ("A title", "", "")),
        (
            '<meta charset="iso-8859-1"><title>Café</title>'.encode("latin-1"),
            None,
            ("Café", "", ""),
        ),
        ("<title>Ä</title>".encode("utf-16"), "utf-16", ("Ä", "", "")),
        (
            b"<title>" + b"long " * 100 + b"</title>",
            None,
            (("long " * 40)[:199].rstrip() + "…", "", ""),
        ),
        (b"<body><title>not in the head</title>", None, ("", "", "")),
        (b'<meta name="description" content="Plain &lt;b&gt;">', None, ("", "Plain <b>", "")),
        (b"<title>x</title><meta charset=nonsense>", "nonsense-charset", ("x", "", "")),
    ],
)
def test_the_preview_is_read_from_the_head(head, charset, expected):
    assert read_preview(head, charset) == expected


# -- reading a page's words for an AI review (ADR 0025) ----------------------------------------


def test_the_words_of_a_page_are_read_without_scripts_or_styles(port):
    text = checker(port).read_text("http://pages.test/article")
    assert text == "Home | About\nOn trust\nTests build trust.\nCafé notes"


def test_plain_text_is_read_as_it_is(port):
    assert checker(port).read_text("http://pages.test/notes.txt") == "Plain words, äiti"


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ("/to-inside", "not on the public internet"),
        ("/gone", "gone (answer 404)"),
        ("/login", "asks for a login"),
        ("/paper.pdf", "gives a file"),
    ],
)
def test_pages_that_cannot_be_read_say_why(port, path, reason):
    with pytest.raises(PageUnreachable, match=re.escape(reason)):
        checker(port).read_text(f"http://pages.test{path}")


def test_reading_through_recent_checks_is_never_remembered(port):
    pages = RecentChecks(checker(port))
    assert pages.read_text("http://pages.test/article").startswith("Home")


def test_page_text_survives_broken_markup():
    assert page_text(b"<p>Hello <b>world</p><div>again", None) == "Hello world\nagain"
    assert page_text(b"<meta charset='latin-1'><p>Caf\xe9</p>") == "Caf\xe9"
