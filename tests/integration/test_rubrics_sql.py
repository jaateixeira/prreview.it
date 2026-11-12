"""The rubric service suite again, on SQL storage (SQLite, and PostgreSQL if available),
plus the guarantees only a database can give."""

import pytest
from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError

from previewit.adapters.persistence.sql import SqlTenancyRepository, SqlUserRepository
from previewit.adapters.persistence.sql_calls import SqlCallRepository
from previewit.adapters.persistence.sql_rubrics import SqlRubricRepository
from previewit.adapters.persistence.tables import calls, criteria, organizations, rubrics
from tests.integration.test_tenancy_sql import engine as engine  # fixture
from tests.unit import test_rubrics_service as base
from tests.unit.test_rubrics_service import TINA, RWorld


@pytest.fixture
def w(engine) -> RWorld:
    return RWorld(
        users=SqlUserRepository(engine),
        repo=SqlTenancyRepository(engine),
        calls_repo=SqlCallRepository(engine),
        rubrics_repo=SqlRubricRepository(engine),
    )


for _name in dir(base):
    if _name.startswith("test_"):
        globals()[_name] = getattr(base, _name)


# --- guarantees from the schema itself --------------------------------------------------------


def test_a_criterion_cannot_name_a_different_tenant_than_its_rubric(w: RWorld, engine):
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            insert(criteria).values(
                id="x", org_id=w.org_b.id, rubric_id=w.rubric.id, position=0, title="t",
                guidance="", type_key="yes_no", config="{}", weight=1, required=True,
            )
        )  # fmt: skip


def test_a_call_cannot_use_a_rubric_of_another_tenant(w: RWorld, engine):
    other_org_rubric = None
    from previewit.domain.rubrics import Rubric, RubricId

    other_org_rubric = Rubric(RubricId("foreign"), w.org_b.id, w.other.id, "B's", "", TINA)
    SqlRubricRepository(engine).add_rubric(other_org_rubric)
    from sqlalchemy import update

    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(update(calls).where(calls.c.id == w.call.id).values(rubric_id="foreign"))


def test_the_database_refuses_to_delete_a_rubric_that_a_call_uses(w: RWorld, engine):
    w.r.attach(TINA, w.call.id, w.rubric.id)
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(delete(rubrics).where(rubrics.c.id == w.rubric.id))


def test_criteria_config_survives_a_round_trip(w: RWorld):
    w.add("levels", "Argument", raw_config={"levels": "Ä | ö\nB | ü ✓"})
    got = w.r.rubric_view(TINA, w.rubric.id).criteria[0].criterion.config
    assert got == {
        "levels": [{"label": "Ä", "descriptor": "ö"}, {"label": "B", "descriptor": "ü ✓"}]
    }


def test_deleting_an_organization_removes_rubrics_and_criteria(w: RWorld, engine):
    w.add("yes_no", "Q")
    with engine.begin() as conn:
        conn.execute(delete(organizations).where(organizations.c.id == w.org_a.id))
    with engine.connect() as conn:
        for table in (rubrics, criteria):
            left = conn.execute(
                select(func.count()).select_from(table).where(table.c.org_id == w.org_a.id)
            ).scalar_one()
            assert left == 0, table.name
