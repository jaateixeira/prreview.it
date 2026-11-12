"""The whole tenancy service suite again, on SQL storage (SQLite, and PostgreSQL if available),
plus the guarantees only a database can give."""

import os

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from previewit.adapters.persistence.engine import make_engine
from previewit.adapters.persistence.migrate import upgrade
from previewit.adapters.persistence.sql import SqlTenancyRepository, SqlUserRepository
from previewit.adapters.persistence.tables import (
    group_members,
    groups,
    invites,
    org_memberships,
    space_members,
    spaces,
)
from tests.integration.test_user_repository import _clean_postgres
from tests.unit import test_tenancy_service as base

POSTGRES_URL = os.environ.get("PREVIEWIT_TEST_POSTGRES_URL")


@pytest.fixture(params=["sqlite", "postgres"])
def engine(request: pytest.FixtureRequest, tmp_path):
    if request.param == "sqlite":
        url = f"sqlite:///{tmp_path / 'tenancy.db'}"
    else:
        if not POSTGRES_URL:
            pytest.skip("set PREVIEWIT_TEST_POSTGRES_URL to run against PostgreSQL")
        _clean_postgres(POSTGRES_URL)
        url = POSTGRES_URL
    upgrade(url)
    eng = make_engine(url)
    request.addfinalizer(eng.dispose)
    return eng


@pytest.fixture
def w(engine) -> base.World:
    return base.World(users=SqlUserRepository(engine), repo=SqlTenancyRepository(engine))


# Re-run every service test (matrix, isolation, invites, groups) against the SQL repository.
for _name in dir(base):
    if _name.startswith("test_"):
        globals()[_name] = getattr(base, _name)


# --- guarantees from the schema itself ----------------------------------------------------------


def test_a_child_row_cannot_name_a_different_tenant_than_its_parent(w: base.World, engine):
    wrong_org = w.org_b.id
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            insert(space_members).values(
                space_id=w.s.id, org_id=wrong_org, user_id="zed", role_key="student"
            )
        )
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(insert(groups).values(id="g", org_id=wrong_org, space_id=w.s.id, name="x"))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            insert(invites).values(
                id="i",
                org_id=wrong_org,
                space_id=w.s.id,
                role_key="student",
                created_by="alice",
                expires_at=w.clock.now,
                uses=0,
                revoked=False,
            )
        )


def test_group_members_must_carry_their_groups_org(w: base.World, engine):
    g = w.t.create_group(base.ALICE, w.s.id, "G")
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(insert(group_members).values(group_id=g.id, user_id="sam", org_id=w.org_b.id))


def test_deleting_an_organization_removes_everything_under_it(w: base.World, engine):
    from sqlalchemy import delete, func, select

    from previewit.adapters.persistence.tables import organizations

    w.t.create_group(base.ALICE, w.s.id, "G", members=[base.SAM])
    with engine.begin() as conn:
        conn.execute(delete(organizations).where(organizations.c.id == w.org_a.id))
    with engine.connect() as conn:
        for table in (spaces, space_members, groups, group_members, invites, org_memberships):
            org_col = table.c.org_id
            left = conn.execute(
                select(func.count()).select_from(table).where(org_col == w.org_a.id)
            ).scalar_one()
            assert left == 0, table.name


def test_concurrent_style_invite_use_never_exceeds_max_uses(w: base.World):
    invite, token = w.t.create_invite(base.TINA, w.s.id, max_uses=2)
    joined = 0
    for user in (base.ZED, base.BOB, base.ALICE):  # alice is already a member: uses no seat
        try:
            w.t.accept_invite(user, token)
            joined += 1
        except base.InvalidInvite:
            pass
    stored = next(i for i in w.t.invites(base.TINA, w.s.id) if i.id == invite.id)
    assert stored.uses == 2 and joined == 3  # zed, bob, and alice (already in)
