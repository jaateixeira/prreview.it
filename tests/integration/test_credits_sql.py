"""The credit suite again on SQL storage (ADR 0026)."""

import pytest

from previewit.adapters.persistence.sql import SqlUserRepository
from previewit.adapters.persistence.sql_credits import SqlCreditRepository
from tests.integration.test_tenancy_sql import engine as engine  # fixture
from tests.unit import test_credits as base


@pytest.fixture
def w(engine) -> base.World:
    users = SqlUserRepository(engine)
    users.add_user(base.ADA_USER, None)  # the buyer has an account
    return base.World(repo=SqlCreditRepository(engine))


for _name in dir(base):
    if _name.startswith("test_"):
        globals()[_name] = getattr(base, _name)
