"""Reading reviewers' email addresses from typed text or an uploaded file (ADR 0018)."""

import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from previewit.domain.email_list import (
    MAX_EMAILS,
    MAX_FILE_BYTES,
    SAMPLES,
    EmailList,
    EmailListError,
    merge,
    parse_file,
    parse_typed,
)


def addresses(found: EmailList) -> list[str]:
    return [e.value for e in found.emails]


# --- typed text ----------------------------------------------------------------------------------


def test_addresses_can_be_separated_by_lines_commas_semicolons_or_spaces():
    found = parse_typed("ana@x.fi, bo@x.fi;cy@x.fi\ndi@x.fi   ed@x.fi\n\n")
    assert addresses(found) == ["ana@x.fi", "bo@x.fi", "cy@x.fi", "di@x.fi", "ed@x.fi"]
    assert found.invalid == () and found.duplicates == 0


def test_addresses_are_trimmed_lowercased_and_listed_once_in_order():
    found = parse_typed("Ana@X.fi\n ana@x.fi \nBO@x.fi\nANA@x.FI")
    assert addresses(found) == ["ana@x.fi", "bo@x.fi"]
    assert found.duplicates == 2


def test_names_with_angle_brackets_are_understood():
    found = parse_typed('Ana Author <ana@x.fi>, "Bo, the Reviewer" <bo@x.fi>\n<cy@x.fi>')
    assert addresses(found) == ["ana@x.fi", "bo@x.fi", "cy@x.fi"]
    assert found.invalid == ()


def test_comments_and_blank_lines_are_ignored():
    found = parse_typed("# my reviewers\n\nana@x.fi  # from the lab\n")
    assert addresses(found) == ["ana@x.fi"] and found.invalid == ()


@pytest.mark.parametrize(
    "bad",
    [
        "bob@",
        "hello",
        "a@b",
        "a@@b.fi",
        "@x.fi",
        "a@b..fi",
        "a@.fi",
        "a@b.fi.",
        "a(b)@x.fi",
        "a@b.c",
    ],
)
def test_entries_that_are_not_addresses_are_reported_not_dropped(bad: str):
    found = parse_typed(f"ana@x.fi\n{bad}\nbo@x.fi")
    assert addresses(found) == ["ana@x.fi", "bo@x.fi"]
    assert found.invalid == (bad,)


def test_international_addresses_are_accepted():
    assert addresses(parse_typed("jörg@exämple.de, 李@例え.jp")) == [
        "jörg@exämple.de",
        "李@例え.jp",
    ]


def test_nothing_typed_gives_an_empty_list():
    found = parse_typed("   \n ")
    assert found.emails == () and found.invalid == ()


def test_a_long_list_is_cut_at_the_limit_and_says_how_many_were_left_out():
    text = "\n".join(f"p{i}@x.fi" for i in range(MAX_EMAILS + 3))
    found = parse_typed(text)
    assert len(found.emails) == MAX_EMAILS and found.over_limit == 3


# --- files ----------------------------------------------------------------------


def test_a_text_file_reads_like_typed_text():
    assert addresses(parse_file("list.txt", b"ana@x.fi\nbo@x.fi\n")) == ["ana@x.fi", "bo@x.fi"]


def test_csv_uses_the_email_column_and_ignores_names():
    data = b'Name,Role,E-mail\nAna,lead,ana@x.fi\n"Bo, B.",student,bo@x.fi\n'
    found = parse_file("people.csv", data)
    assert addresses(found) == ["ana@x.fi", "bo@x.fi"] and found.invalid == ()


def test_csv_without_a_header_takes_every_cell_that_has_an_at_sign():
    found = parse_file("p.csv", "Ana;ana@x.fi\nBo;bo@x.fi\n".encode("utf-8-sig"))
    assert addresses(found) == ["ana@x.fi", "bo@x.fi"]


def test_csv_reports_a_bad_address_in_the_email_column():
    found = parse_file("p.csv", b"name,email\nAna,ana@x.fi\nBo,bo@\nCy,\n")
    assert addresses(found) == ["ana@x.fi"] and found.invalid == ("bo@",)


@pytest.mark.parametrize(
    "document",
    [
        ["ana@x.fi", "bo@x.fi"],
        {"emails": ["ana@x.fi", "bo@x.fi"]},
        {"reviewers": [{"name": "Ana", "email": "ana@x.fi"}, {"name": "Bo", "email": "bo@x.fi"}]},
        [{"Email": "ana@x.fi"}, {"mail": "bo@x.fi"}],
    ],
)
def test_json_in_common_shapes(document):
    assert addresses(parse_file("r.json", json.dumps(document).encode())) == [
        "ana@x.fi",
        "bo@x.fi",
    ]


def test_json_reports_bad_addresses_and_ignores_other_text():
    found = parse_file("r.json", b'{"title": "Reviewers", "emails": ["ana@x.fi", "nope@"]}')
    assert addresses(found) == ["ana@x.fi"] and found.invalid == ("nope@",)


def test_xml_elements_and_attributes():
    xml = (
        b'<?xml version="1.0"?><reviewers><reviewer name="Ana"><email>ana@x.fi</email></reviewer>'
        b'<reviewer email="bo@x.fi"/><note>Thanks!</note></reviewers>'
    )
    assert addresses(parse_file("r.xml", xml)) == ["ana@x.fi", "bo@x.fi"]


def test_xml_with_a_doctype_is_refused_because_of_entity_tricks():
    bomb = b'<!DOCTYPE r [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><r><e>&b;</e></r>'
    with pytest.raises(EmailListError):
        parse_file("r.xml", bomb)


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("r.json", b"{not json"),
        ("r.xml", b"<a><b></a>"),
        ("r.txt", b"\xff\xfe\x00\x01 binary"),
        ("r.csv", b"\x89PNG\r\n\x1a\n"),
    ],
)
def test_unreadable_files_get_a_clear_error(name: str, data: bytes):
    with pytest.raises(EmailListError):
        parse_file(name, data)


def test_a_huge_file_is_refused_without_reading_it():
    with pytest.raises(EmailListError):
        parse_file("r.txt", b"a@x.fi\n" * (MAX_FILE_BYTES // 7 + 10))


def test_a_file_with_no_known_extension_is_recognised_by_its_content():
    assert addresses(parse_file("list", b'["ana@x.fi"]')) == ["ana@x.fi"]
    assert addresses(parse_file(None, b"<l><e>ana@x.fi</e></l>")) == ["ana@x.fi"]
    assert addresses(parse_file("list", b"ana@x.fi")) == ["ana@x.fi"]


def test_a_file_without_any_address_is_not_an_error_but_an_empty_list():
    assert parse_file("r.txt", b"nothing here").emails == ()  # reported as invalid entries
    assert parse_file("r.json", b'{"name": "Ana"}').emails == ()


# --- samples and merging -------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_every_sample_file_reads_back_as_the_same_three_people(name: str):
    sample = SAMPLES[name]
    found = parse_file(name, sample.content.encode())
    assert addresses(found) == [
        "ana.author@example.org",
        "bo.reviewer@example.org",
        "cy@example.org",
    ]
    assert found.invalid == ()


def test_samples_cover_the_four_formats():
    assert {n.rsplit(".", 1)[1] for n in SAMPLES} == {"txt", "csv", "json", "xml"}


def test_typed_and_uploaded_addresses_are_merged_without_repeats():
    typed = parse_typed("ana@x.fi, nope@")
    uploaded = parse_file("l.txt", b"ana@x.fi\nbo@x.fi")
    both = merge(typed, uploaded)
    assert addresses(both) == ["ana@x.fi", "bo@x.fi"]
    assert both.invalid == ("nope@",) and both.duplicates == 1


# --- properties ----------------------------------------------------------------------------------

emails = st.from_regex(r"[a-z][a-z0-9]{0,8}@[a-z]{1,8}\.(fi|org|com)", fullmatch=True)
unique_emails = st.lists(emails, min_size=1, max_size=20, unique=True)


@given(unique_emails)
def test_any_list_survives_every_format(items: list[str]):
    assert addresses(parse_typed("\n".join(items))) == items
    assert (
        addresses(
            parse_file("a.csv", ("name,email\n" + "\n".join(f"x,{e}" for e in items)).encode())
        )
        == items
    )
    assert addresses(parse_file("a.json", json.dumps({"emails": items}).encode())) == items
    xml = "<r>" + "".join(f"<e>{e}</e>" for e in items) + "</r>"
    assert addresses(parse_file("a.xml", xml.encode())) == items


@given(st.binary(max_size=2000), st.sampled_from(["a.txt", "a.csv", "a.json", "a.xml", None]))
def test_arbitrary_bytes_never_crash_the_reader(data: bytes, name):
    try:
        found = parse_file(name, data)
    except EmailListError:
        return
    assert len(found.emails) <= MAX_EMAILS
