"""The rounds service suite again, on SQL storage (SQLite, and PostgreSQL if available),
plus the guarantees only a database can give."""

import pytest
from sqlalchemy import delete, insert
from sqlalchemy.exc import IntegrityError

from previewit.adapters.persistence.sql import SqlTenancyRepository, SqlUserRepository
from previewit.adapters.persistence.sql_calls import SqlCallRepository
from previewit.adapters.persistence.sql_rounds import SqlRoundRepository
from previewit.adapters.persistence.tables import calls, review_rounds, review_tasks
from previewit.domain.party import UserParty
from tests.integration.test_tenancy_sql import engine as engine  # fixture
from tests.unit import test_rounds_service as base
from tests.unit.test_rounds_service import SAM, SUE, TINA, RoundsWorld


@pytest.fixture
def w(engine) -> RoundsWorld:
    return RoundsWorld(
        users=SqlUserRepository(engine),
        repo=SqlTenancyRepository(engine),
        calls_repo=SqlCallRepository(engine),
        rounds_repo=SqlRoundRepository(engine),
    )


for _name in dir(base):
    if _name.startswith("test_"):
        globals()[_name] = getattr(base, _name)


# --- guarantees from the schema itself --------------------------------------------------------


def task_row(w: RoundsWorld, **over) -> dict:
    row = dict(
        id="t-x", org_id=w.org_a.id, space_id=w.s.id, round_id="", reviewer_kind="user",
        reviewer_id=SUE, submission_id="", revision_number=1, manual=False,
    )  # fmt: skip
    row.update(over)
    return row


def prepared(w: RoundsWorld):
    subs = w.work(SAM, SUE)
    r = w.round(strategy_key="manual")
    return r, subs


def test_a_task_cannot_name_a_different_tenant_than_its_round(w: RoundsWorld, engine):
    r, subs = prepared(w)
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            insert(review_tasks).values(
                **task_row(w, round_id=r.id, submission_id=subs[SAM].id, org_id=w.org_b.id)
            )
        )


def test_the_same_pair_cannot_be_stored_twice(w: RoundsWorld, engine):
    r, subs = prepared(w)
    w.rr.add_task(TINA, r.id, subs[SAM].id, UserParty(SUE))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            insert(review_tasks).values(**task_row(w, round_id=r.id, submission_id=subs[SAM].id))
        )


def test_round_numbers_are_unique_per_call(w: RoundsWorld, engine):
    r = w.round()
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            insert(review_rounds).values(
                id="dup", org_id=r.org_id, space_id=r.space_id, call_id=r.call_id, number=r.number,
                per_submission=1, strategy_key="random", anonymity_key="open",
            )
        )  # fmt: skip


def test_deleting_a_call_removes_its_rounds_and_tasks(w: RoundsWorld, engine):
    r, subs = prepared(w)
    w.rr.add_task(TINA, r.id, subs[SAM].id, UserParty(SUE))
    with engine.begin() as conn:
        conn.execute(delete(calls).where(calls.c.id == w.call.id))
    repo = SqlRoundRepository(engine)
    assert repo.get_round(r.id) is None and repo.tasks_of_round(r.id) == []
