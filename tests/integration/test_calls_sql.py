"""The calls service suite again, on SQL storage (SQLite, and PostgreSQL if available),
plus the guarantees only a database can give."""

from datetime import timedelta

import pytest
from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError

from previewit.adapters.persistence.sql import SqlTenancyRepository, SqlUserRepository
from previewit.adapters.persistence.sql_calls import SqlCallRepository
from previewit.adapters.persistence.tables import (
    calls,
    organizations,
    revisions,
    share_grants,
    share_links,
    submissions,
)
from previewit.application.artifacts import Upload
from previewit.domain.calls import ShareTarget
from tests.integration.test_tenancy_sql import engine as engine  # fixture
from tests.unit import test_calls_service as base
from tests.unit.test_calls_service import SAM, SUE, TINA, ZED, CWorld


@pytest.fixture
def w(engine) -> CWorld:
    return CWorld(
        users=SqlUserRepository(engine),
        repo=SqlTenancyRepository(engine),
        calls_repo=SqlCallRepository(engine),
    )


# Re-run every calls test against the SQL repository.
for _name in dir(base):
    if _name.startswith("test_"):
        globals()[_name] = getattr(base, _name)


# --- guarantees from the schema itself ----------------------------------------------------------


def test_a_submission_cannot_name_a_different_tenant_than_its_call(w: CWorld, engine):
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            insert(submissions).values(
                id="x",
                org_id=w.org_b.id,
                space_id=w.s.id,
                call_id=w.call.id,
                author_kind="user",
                author_id="sam",
                title="t",
                created_at=w.clock.now,
            )
        )


def test_the_database_refuses_a_second_submission_by_the_same_party(w: CWorld, engine):
    w.essay(SAM)
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            insert(submissions).values(
                id="dup",
                org_id=w.call.org_id,
                space_id=w.s.id,
                call_id=w.call.id,
                author_kind="user",
                author_id="sam",
                title="t",
                created_at=w.clock.now,
            )
        )


def test_revision_numbers_are_unique_per_submission(w: CWorld, engine):
    sub = w.essay(SAM)
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            insert(revisions).values(
                submission_id=sub.id,
                number=1,
                org_id=sub.org_id,
                type_key="text",
                media_type="text/plain",
                size=1,
                digest="d",
                content=b"x",
                created_by="sam",
                created_at=w.clock.now,
            )
        )


def test_deleting_a_call_removes_its_work_links_and_grants(w: CWorld, engine):
    other = w.c.create_call(TINA, w.s.id, title="Temp", artifact_type="text", published=True)
    sub = w.c.submit(SUE, other.id, title="S", upload=Upload(text="x"))
    w.c.create_share(TINA, ShareTarget.CALL, other.id)
    _, token = w.c.create_share(SUE, ShareTarget.SUBMISSION, sub.id)
    w.c.accept_share(ZED, token)
    # delete_call refuses when there is work; the repository itself cascades
    SqlCallRepository(engine).delete_call(other.id)
    with engine.connect() as conn:
        for table, column in (
            (submissions, submissions.c.call_id),
            (revisions, revisions.c.submission_id),
            (share_links, share_links.c.target_id),
            (share_grants, share_grants.c.target_id),
        ):
            n = conn.execute(
                select(func.count()).select_from(table).where(column.in_([other.id, sub.id]))
            ).scalar_one()
            assert n == 0, table.name


def test_deleting_an_organization_removes_calls_and_revisions(w: CWorld, engine):
    w.essay(SAM)
    w.c.create_share(TINA, ShareTarget.CALL, w.call.id)
    with engine.begin() as conn:
        conn.execute(delete(organizations).where(organizations.c.id == w.org_a.id))
    with engine.connect() as conn:
        for table in (calls, submissions, revisions, share_links, share_grants):
            left = conn.execute(
                select(func.count()).select_from(table).where(table.c.org_id == w.org_a.id)
            ).scalar_one()
            assert left == 0, table.name


def test_pdf_bytes_survive_a_round_trip_exactly(w: CWorld):
    pdf = b"%PDF-1.7\n\x00\xff\xfe binary \x00\n%%EOF\n"
    call = w.c.create_call(TINA, w.s.id, title="P", artifact_type="pdf", published=True)
    sub = w.c.submit(SAM, call.id, title="P", upload=Upload(content=pdf, filename="p.pdf"))
    got = w.c.revision(SAM, sub.id, 1).artifact
    assert got.content == pdf and got.filename == "p.pdf"
    assert got.digest == w.c.submission_view(SAM, sub.id).revisions[0].digest


def test_deadlines_keep_their_timezone(w: CWorld):
    closing = w.c.create_call(
        TINA,
        w.s.id,
        title="D",
        artifact_type="text",
        published=True,
        closes_at=w.clock.now + timedelta(days=1),
    )
    stored = w.c.call_view(SAM, closing.id).call.closes_at
    assert stored == w.clock.now + timedelta(days=1)
