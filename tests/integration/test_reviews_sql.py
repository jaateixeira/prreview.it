"""The reviews service suite again, on SQL storage (SQLite, and PostgreSQL if available),
plus the guarantees only a database can give."""

import pytest
from sqlalchemy import delete, insert
from sqlalchemy.exc import IntegrityError

from previewit.adapters.persistence.sql import SqlTenancyRepository, SqlUserRepository
from previewit.adapters.persistence.sql_calls import SqlCallRepository
from previewit.adapters.persistence.sql_reviews import SqlReviewRepository
from previewit.adapters.persistence.sql_rounds import SqlRoundRepository
from previewit.adapters.persistence.sql_rubrics import SqlRubricRepository
from previewit.adapters.persistence.tables import calls, review_edits, reviews
from previewit.domain.party import UserParty
from tests.integration.test_tenancy_sql import engine as engine  # fixture
from tests.unit import test_reviews_service as base
from tests.unit.test_calls_service import SAM, SUE
from tests.unit.test_reviews_service import ReviewWorld


@pytest.fixture
def w(engine) -> ReviewWorld:
    return ReviewWorld(
        users=SqlUserRepository(engine),
        repo=SqlTenancyRepository(engine),
        calls_repo=SqlCallRepository(engine),
        rounds_repo=SqlRoundRepository(engine),
        reviews_repo=SqlReviewRepository(engine),
        rubrics_repo=SqlRubricRepository(engine),
    )


for _name in dir(base):
    if _name.startswith("test_"):
        globals()[_name] = getattr(base, _name)


@pytest.fixture
def gw(w: ReviewWorld):  # the group fixture of the shared suite, on this storage
    from previewit.domain.party import GroupParty
    from tests.unit.test_calls_service import PAT, TINA

    group = w.t.create_group(TINA, w.s.id, "Reviewers", [SUE, PAT])
    return w, w.task_for(GroupParty(group.id), SAM)


# --- guarantees from the schema itself --------------------------------------------------------


def test_one_review_per_task_even_if_the_service_were_bypassed(w: ReviewWorld, engine):
    task = w.task_for(UserParty(SUE), SAM)
    w.rv.save(SUE, task.id, w.answers(), 0)
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            insert(reviews).values(
                id="dup", org_id=task.org_id, space_id=task.space_id, round_id=task.round_id,
                task_id=task.id, answers="{}", version=1, submitted=False,
            )
        )  # fmt: skip


def test_a_review_cannot_name_a_different_tenant_than_its_task(w: ReviewWorld, engine):
    task = w.task_for(UserParty(SUE), SAM)
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            insert(reviews).values(
                id="x", org_id=w.org_b.id, space_id=task.space_id, round_id=task.round_id,
                task_id=task.id, answers="{}", version=1, submitted=False,
            )
        )  # fmt: skip


def test_the_edit_trail_has_one_line_per_version(w: ReviewWorld, engine):
    task = w.task_for(UserParty(SUE), SAM)
    review = w.rv.save(SUE, task.id, w.answers(), 0)
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            insert(review_edits).values(
                review_id=review.id,
                version=1,
                org_id=review.org_id,
                user_id=SUE,
                at=review.updated_at,
            )
        )


def test_deleting_a_call_removes_reviews_and_annotations(w: ReviewWorld, engine):
    task = w.task_for(UserParty(SUE), SAM)
    w.rv.add_annotation(SUE, task.id, {"quote": "ell", "start": "1", "end": "4"}, "Hm")
    repo = SqlReviewRepository(engine)
    review = repo.review_of_task(task.id)
    assert review and repo.annotations_of(review.id)
    with engine.begin() as conn:
        conn.execute(delete(calls).where(calls.c.id == w.call.id))
    assert repo.review_of_task(task.id) is None and repo.annotations_of(review.id) == []
