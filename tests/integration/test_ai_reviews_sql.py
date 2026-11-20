"""The AI reviews suite again on SQL storage (ADR 0025), plus what only a database can show:
no column anywhere holds the person's key."""

import pytest
from sqlalchemy import select

from previewit.adapters.persistence.sql import SqlTenancyRepository, SqlUserRepository
from previewit.adapters.persistence.sql_ai_reviews import SqlAiReviewRepository
from previewit.adapters.persistence.sql_calls import SqlCallRepository
from previewit.adapters.persistence.sql_credits import SqlCreditRepository
from previewit.adapters.persistence.tables import ai_reviews
from tests.integration.test_tenancy_sql import engine as engine  # fixture
from tests.unit import test_ai_reviews_service as base


class SqlWorld(base.AiWorld):
    def __init__(self, engine) -> None:
        self.engine = engine
        super().__init__(
            users=SqlUserRepository(engine),
            repo=SqlTenancyRepository(engine),
            calls_repo=SqlCallRepository(engine),
            ai_repo=SqlAiReviewRepository(engine),
            credit_repo=SqlCreditRepository(engine),
        )

    def everything_kept(self) -> str:
        with self.engine.connect() as conn:
            return repr([tuple(row) for row in conn.execute(select(ai_reviews))])


@pytest.fixture
def w(engine) -> base.AiWorld:
    return SqlWorld(engine)


for _name in dir(base):
    if _name.startswith("test_"):
        globals()[_name] = getattr(base, _name)
