"""The invitations suite again on SQL storage (SQLite, and PostgreSQL if available), plus the
guarantees only a database can give."""

import pytest
from sqlalchemy import delete, insert, select
from sqlalchemy.exc import IntegrityError

from previewit.adapters.persistence.sql import SqlTenancyRepository, SqlUserRepository
from previewit.adapters.persistence.sql_calls import SqlCallRepository
from previewit.adapters.persistence.sql_reviews import SqlReviewRepository
from previewit.adapters.persistence.sql_rounds import SqlRoundRepository
from previewit.adapters.persistence.tables import invitation_submissions, invitations, review_rounds
from tests.integration.test_tenancy_sql import engine as engine  # fixture
from tests.unit import test_invitations_service as base
from tests.unit.test_invitations_service import SAM, SUE, TINA, InviteWorld


@pytest.fixture
def w(engine) -> InviteWorld:
    return InviteWorld(
        users=SqlUserRepository(engine),
        repo=SqlTenancyRepository(engine),
        calls_repo=SqlCallRepository(engine),
        rounds_repo=SqlRoundRepository(engine),
        reviews_repo=SqlReviewRepository(engine),
    )


for _name in dir(base):
    if _name.startswith("test_"):
        globals()[_name] = getattr(base, _name)


# --- guarantees from the schema itself --------------------------------------------------------


def test_an_invitation_cannot_name_a_different_tenant_than_its_round(w: InviteWorld, engine):
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            insert(invitations).values(
                id="x", org_id=w.org_b.id, space_id=w.s.id, round_id=w.r.id, email="a@x.fi",
                created_by=TINA, expires_at=w.clock.now, revoked=False,
            )
        )  # fmt: skip


def test_the_work_of_an_invitation_keeps_its_order_and_goes_with_it(w: InviteWorld, engine):
    first, second = w.work_by[SUE].id, w.work_by[SAM].id
    inv, _ = w.iv.invite(TINA, w.r.id, "rita@x.fi", [first, second])
    assert SqlRoundRepository(engine).get_invitation(inv.id).submission_ids == (first, second)  # type: ignore[union-attr]
    with engine.begin() as conn:
        conn.execute(delete(review_rounds).where(review_rounds.c.id == w.r.id))
    with engine.connect() as conn:
        assert conn.execute(select(invitations)).all() == []
        assert conn.execute(select(invitation_submissions)).all() == []


def test_the_same_work_cannot_be_listed_twice_on_one_invitation(w: InviteWorld, engine):
    inv, _ = w.iv.invite(TINA, w.r.id, "rita@x.fi", [w.work_by[SAM].id])
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            insert(invitation_submissions).values(
                invitation_id=inv.id, submission_id=w.work_by[SAM].id, org_id=inv.org_id,
                position=1,
            )
        )  # fmt: skip
