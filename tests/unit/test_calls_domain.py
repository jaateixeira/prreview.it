from datetime import UTC, datetime, timedelta

import pytest

from previewit.domain.calls import (
    Artifact,
    Call,
    CallId,
    InvalidCall,
    ShareLink,
    ShareTarget,
    clean_description,
    clean_title,
)
from previewit.domain.identity import UserId
from previewit.domain.tenancy import OrgId, SpaceId

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


def call(**kw) -> Call:
    base = dict(
        id=CallId("c"), org_id=OrgId("o"), space_id=SpaceId("s"), title="Essay", description="",
        artifact_type="text", group_work=False, closes_at=None, published=True,
        created_by=UserId("u"),
    )  # fmt: skip
    return Call(**{**base, **kw})


def test_titles_and_descriptions_are_cleaned_and_bounded():
    assert clean_title("  Essay   one ") == "Essay one"
    for bad in ("", "   ", "x" * 201):
        with pytest.raises(InvalidCall):
            clean_title(bad)
    assert clean_description("  a\r\nb  ") == "a\nb"
    with pytest.raises(InvalidCall):
        clean_description("x" * 5001)


def test_a_call_accepts_work_only_when_published_and_before_the_deadline():
    assert call().accepting(NOW)
    assert not call(published=False).accepting(NOW)
    assert call(closes_at=NOW + timedelta(seconds=1)).accepting(NOW)
    assert not call(closes_at=NOW).accepting(NOW)  # the deadline itself is closed


def test_artifact_size_and_digest():
    a = Artifact("text", "text/plain", b"abc")
    assert a.size == 3
    assert a.digest == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_share_link_usable_until_expiry_unless_revoked():
    link = ShareLink("h", OrgId("o"), SpaceId("s"), ShareTarget.CALL, "c", UserId("u"),
                     NOW + timedelta(days=1), False)  # fmt: skip
    assert link.usable(NOW)
    assert not link.usable(NOW + timedelta(days=1))
    assert not ShareLink(**{**link.__dict__, "revoked": True}).usable(NOW)
