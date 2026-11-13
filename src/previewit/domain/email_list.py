"""Reading reviewers' email addresses from typed text or an uploaded file (ADR 0018).

A person types or pastes addresses, or uploads a .txt, .csv, .json or .xml file. We pull the
addresses out, check each one, list each once, and report the entries that are not addresses
so nothing is silently dropped. Pure Python: it works on text and bytes, not on files.
"""

from __future__ import annotations

import csv
import io
import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import cast

from previewit.domain.identity import Email, InvalidEmail

MAX_EMAILS = 100
MAX_FILE_BYTES = 200_000

# Names that mark a column, key or element as holding addresses.
EMAIL_KEYS = frozenset(
    {"email", "e-mail", "mail", "emails", "email address", "e-mail address", "emailaddress"}
    | {"email_address", "reviewer_email"}
)
# Plain addresses: no brackets, quotes, commas or spaces; a dot-separated domain, no empty labels.
_ADDRESS = re.compile(r"^[\w.!#$%&'*+/=?^`{|}~-]+@(?:[\w-]+\.)+[\w-]{2,}$")
_ANGLE = re.compile(r"<([^<>]*)>")
_SEPARATORS = re.compile(r"[\s,;]+")
_COMMENT = re.compile(r"(?:^|\s)#.*$")
_EDGE = "\"'()[]<>"


class EmailListError(ValueError):
    """The file cannot be read as a list of addresses. The message is for the person."""


@dataclass(frozen=True)
class EmailList:
    emails: tuple[Email, ...] = ()  # valid, each once, in the order they appeared
    invalid: tuple[str, ...] = ()  # entries that look like an attempt but are not addresses
    duplicates: int = 0  # repeats that were left out
    over_limit: int = 0  # valid addresses beyond MAX_EMAILS that were left out

    @property
    def ok(self) -> bool:
        return bool(self.emails) and not self.invalid and not self.over_limit


@dataclass
class _Collector:
    emails: dict[str, Email] = field(default_factory=dict[str, Email])
    invalid: dict[str, None] = field(default_factory=dict[str, None])
    duplicates: int = 0
    over_limit: int = 0

    def add(self, entry: str) -> None:
        token = entry.strip().strip(_EDGE).strip()
        if not token:
            return
        if not _ADDRESS.match(token):
            self.invalid.setdefault(token[:120], None)
            return
        try:
            email = Email(token)
        except InvalidEmail:
            self.invalid.setdefault(token[:120], None)
            return
        if email.value in self.emails:
            self.duplicates += 1
        elif len(self.emails) >= MAX_EMAILS:
            self.over_limit += 1
        else:
            self.emails[email.value] = email

    def add_loose(self, text: str) -> None:
        """Text around other words (a name, a note): only the pieces with an at sign count."""
        for piece in _SEPARATORS.split(text):
            if "@" in piece:
                self.add(piece)

    def result(self) -> EmailList:
        return EmailList(
            tuple(self.emails.values()), tuple(self.invalid), self.duplicates, self.over_limit
        )


# --- typed text -----------------------------------------------------------------------------------


def parse_typed(text: str) -> EmailList:
    """Addresses typed or pasted: one per line, or separated by commas, semicolons or spaces.
    `Name <address>` is understood. Anything else that is not an address is reported."""
    found = _Collector()
    _read_text(found, text)
    return found.result()


def _read_text(found: _Collector, text: str) -> None:
    for line in text.splitlines():
        line = _COMMENT.sub("", line)
        if "<" in line and ">" in line:
            for inside in _ANGLE.findall(line):
                found.add(inside)
            continue
        for piece in _SEPARATORS.split(line):
            found.add(piece)


# --- files ----------------------------------------------------------------------------------------


def parse_file(filename: str | None, content: bytes) -> EmailList:
    """Addresses from a .txt, .csv, .json or .xml file, told apart by name and then content."""
    if len(content) > MAX_FILE_BYTES:
        raise EmailListError(f"That file is too large (limit: {MAX_FILE_BYTES // 1000} kB).")
    kind = _kind(filename, content)
    found = _Collector()
    if kind == "xml":
        _read_xml(found, content)
    else:
        text = _decode(content)
        if kind == "json":
            _read_json(found, text)
        elif kind == "csv":
            _read_csv(found, text)
        else:
            _read_text(found, text)
    return found.result()


def _kind(filename: str | None, content: bytes) -> str:
    extension = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    named = {"json": "json", "xml": "xml", "csv": "csv", "tsv": "csv"}.get(extension)
    if named:
        return named
    start = content.lstrip(b"\xef\xbb\xbf \t\r\n")[:1]
    if start in (b"{", b"["):
        return "json"
    if start == b"<":
        return "xml"
    return "text"


def _decode(content: bytes) -> str:
    if b"\x00" in content:
        raise EmailListError("That file is not a text file. Use .txt, .csv, .json or .xml.")
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise EmailListError("Save the file as UTF-8 text and try again.") from None


def _read_csv(found: _Collector, text: str) -> None:
    try:
        delimiter = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|").delimiter
    except csv.Error:
        delimiter = ","
    try:
        rows = [row for row in csv.reader(io.StringIO(text), delimiter=delimiter) if row]
    except csv.Error:
        raise EmailListError("That file is not a valid CSV file.") from None
    column = next(
        (i for row in rows[:5] for i, cell in enumerate(row) if cell.strip().lower() in EMAIL_KEYS),
        None,
    )
    if column is None:  # no header: every cell with an at sign counts, names are ignored
        for row in rows:
            for cell in row:
                found.add_loose(cell)
        return
    header_at = next(
        i for i, row in enumerate(rows) if column < len(row) and _is_header(row[column])
    )
    for row in rows[header_at + 1 :]:
        if column < len(row):
            found.add(row[column])


def _is_header(cell: str) -> bool:
    return cell.strip().lower() in EMAIL_KEYS


def _read_json(found: _Collector, text: str) -> None:
    try:
        document = json.loads(text)
    except (ValueError, RecursionError):
        raise EmailListError("That file is not valid JSON.") from None
    # (value, strict): inside an email key every entry must be an address; elsewhere only
    # strings with an at sign count and names are ignored. Iterative: no deep recursion.
    stack: list[tuple[object, bool]] = [(document, False)]
    while stack:
        value, strict = stack.pop()
        if isinstance(value, str):
            if strict:
                found.add(value)
            else:
                found.add_loose(value)
        elif isinstance(value, list):
            stack.extend((item, strict) for item in reversed(cast("list[object]", value)))
        elif isinstance(value, dict):
            items = list(cast("dict[object, object]", value).items())
            keyed: list[tuple[object, bool]] = [
                (v, True) for k, v in items if str(k).strip().lower() in EMAIL_KEYS
            ]
            rest: list[tuple[object, bool]] = keyed or [(v, strict) for _, v in items]
            stack.extend(reversed(rest))


def _read_xml(found: _Collector, content: bytes) -> None:
    lowered = content.lower()
    if b"\x00" in content:
        raise EmailListError("Save the XML file as UTF-8 and try again.")
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise EmailListError("XML with a DOCTYPE or entities is not accepted.")
    try:
        root = ET.fromstring(content)
    except (ET.ParseError, ValueError, RecursionError):
        raise EmailListError("That file is not valid XML.") from None
    for element in root.iter():
        keyed = _local(element.tag) in EMAIL_KEYS
        for text in _texts(element, keyed):
            if keyed:
                found.add(text)
            else:
                found.add_loose(text)
        for name, value in element.attrib.items():
            if _local(name) in EMAIL_KEYS:
                found.add(value)
            else:
                found.add_loose(value)


def _texts(element: ET.Element, keyed: bool) -> Iterable[str]:
    if element.text and (keyed or "@" in element.text):
        yield element.text
    # The text after a child element belongs to this element too.
    for child in element:
        if child.tail and "@" in child.tail:
            yield child.tail


def _local(name: object) -> str:
    return str(name).rsplit("}", 1)[-1].strip().lower()


# --- both ----------------------------------------------------------------------------------------


def merge(*lists: EmailList) -> EmailList:
    """Typed and uploaded addresses together, each once, up to the limit."""
    emails: dict[str, Email] = {}
    invalid: dict[str, None] = {}
    duplicates = sum(item.duplicates for item in lists)
    over_limit = sum(item.over_limit for item in lists)
    for item in lists:
        invalid.update(dict.fromkeys(item.invalid))
        for email in item.emails:
            if email.value in emails:
                duplicates += 1
            elif len(emails) >= MAX_EMAILS:
                over_limit += 1
            else:
                emails[email.value] = email
    return EmailList(tuple(emails.values()), tuple(invalid), duplicates, over_limit)


# --- samples to show and download ---------------------------------------------------------------


@dataclass(frozen=True)
class Sample:
    content_type: str
    content: str


SAMPLES: dict[str, Sample] = {
    "reviewers.txt": Sample(
        "text/plain; charset=utf-8",
        "# One address per line. Commas and semicolons work too.\n"
        "ana.author@example.org\nbo.reviewer@example.org\ncy@example.org\n",
    ),
    "reviewers.csv": Sample(
        "text/csv; charset=utf-8",
        "name,email\nAna Author,ana.author@example.org\n"
        "Bo Reviewer,bo.reviewer@example.org\nCy,cy@example.org\n",
    ),
    "reviewers.json": Sample(
        "application/json",
        json.dumps(
            {
                "emails": [
                    "ana.author@example.org",
                    "bo.reviewer@example.org",
                    "cy@example.org",
                ]
            },
            indent=2,
        )
        + "\n",
    ),
    "reviewers.xml": Sample(
        "application/xml",
        '<?xml version="1.0" encoding="UTF-8"?>\n<reviewers>\n'
        "  <reviewer><email>ana.author@example.org</email></reviewer>\n"
        "  <reviewer><email>bo.reviewer@example.org</email></reviewer>\n"
        "  <reviewer><email>cy@example.org</email></reviewer>\n</reviewers>\n",
    ),
}
