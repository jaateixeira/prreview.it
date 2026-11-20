"""Test doubles and helpers for the login web tests."""

from __future__ import annotations

import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import count

from fastapi import FastAPI
from fastapi.responses import RedirectResponse, Response
from fastapi.testclient import TestClient
from starlette.requests import Request

from previewit.adapters.auth.base import AuthFailed, ExternalProvider
from previewit.adapters.auth.passwords import Argon2Hasher
from previewit.adapters.entitlements import UnlimitedEntitlements
from previewit.adapters.persistence.memory import (
    InMemoryEmailTokenRepository,
    InMemoryTenancyRepository,
    InMemoryUserRepository,
)
from previewit.adapters.persistence.memory_ai_reviews import InMemoryAiReviewRepository
from previewit.adapters.persistence.memory_calls import InMemoryCallRepository
from previewit.adapters.persistence.memory_credits import InMemoryCreditRepository
from previewit.adapters.persistence.memory_prepared import InMemoryPreparedRequestRepository
from previewit.adapters.persistence.memory_reviews import InMemoryReviewRepository
from previewit.adapters.persistence.memory_rounds import InMemoryRoundRepository
from previewit.adapters.persistence.memory_rubrics import InMemoryRubricRepository
from previewit.adapters.settings import Settings
from previewit.adapters.web.app import build_app
from previewit.application.ai_reviews import AiReviewsService
from previewit.application.allocation import StrategyRegistry
from previewit.application.artifacts import ArtifactRegistry, PluginServices
from previewit.application.auth import AuthService
from previewit.application.calls import CallsService
from previewit.application.credits import CreditsService
from previewit.application.criteria import CriterionRegistry
from previewit.application.invitations import InvitationsService
from previewit.application.ports import MailError
from previewit.application.prepared_requests import PreparedRequestsService
from previewit.application.quick_review import QuickReviewService
from previewit.application.reviews import ReviewsService
from previewit.application.rounds import RoundsService
from previewit.application.rubrics import RubricsService
from previewit.application.tenancy import TenancyService
from previewit.application.verification import VerificationService
from previewit.domain.credits import CreditPack
from previewit.domain.identity import Email, ExternalClaims, Provider
from previewit.domain.policy import DEFAULT_POLICY, VerificationPolicy
from previewit.plugins.allocation import ManualStrategy, RandomStrategy, RoundRobinStrategy
from previewit.plugins.criteria import (
    LevelsCriterion,
    NumericCriterion,
    TextCriterion,
    YesNoCriterion,
)
from previewit.plugins.pdf import PdfArtifact
from previewit.plugins.text import TextArtifact
from previewit.plugins.webpage import WebPageArtifact
from tests.unit.test_ai_models import CHEAP, LOCAL
from tests.unit.test_ai_reviews_service import (
    HOUSE,
    PRICING,
    SONNET,
    TINY,
    FakeCatalog,
    FakeWriter,
    Jobs,
)
from tests.unit.test_webpage_plugin import ESSAY, FakePageChecker

PADDLE_SECRET = "pdl_ntfset_test_secret"
SELLER = {
    "seller_legal_name": "Sam Seller",
    "seller_address": "Testikatu 1, 40100 Jyväskylä, Finland",
    "seller_email": "hello@example.org",
    "seller_phone": "+358 40 123 4567",
    "seller_processors": ("Mail Co SAS, France: sends our emails",),
}


class FakeProvider:
    """Behaves like an OIDC provider: round trip through the flow session, then claims."""

    def __init__(self, provider: Provider = Provider.GOOGLE) -> None:
        self.provider = provider
        self.claims = ExternalClaims(provider, "sub-1", Email("ann@x.fi"), True, "Ann")

    async def begin(self, request: Request, redirect_uri: str) -> Response:
        state = secrets.token_urlsafe(8)
        request.session["fake_state"] = state
        return RedirectResponse(f"{redirect_uri}?state={state}", status_code=303)

    async def complete(self, request: Request) -> ExternalClaims:
        expected = request.session.pop("fake_state", None)
        if expected is None or request.query_params.get("state") != expected:
            raise AuthFailed("state mismatch")
        return self.claims


class Outbox:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.failing = False  # a test sets this to make the mail server "go down"

    def send(self, to: str, subject: str, body: str) -> None:
        if self.failing:
            raise MailError("smtp is down")
        self.sent.append((to, subject, body))

    def last_link(self) -> str:
        match = re.search(r"https?://\S+/verify\?token=\S+", self.sent[-1][2])
        assert match
        return match.group(0)


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@dataclass
class Harness:
    client: TestClient
    auth: AuthService
    outbox: Outbox
    clock: Clock
    app: FastAPI
    base_url: str
    pages: FakePageChecker
    prepared_repo: InMemoryPreparedRequestRepository
    ai_writer: FakeWriter
    ai_jobs: Jobs
    ai_repo: InMemoryAiReviewRepository
    credits: CreditsService

    def new_client(self) -> TestClient:
        """Another browser: same app, its own cookies."""
        return TestClient(self.app, base_url=self.base_url, follow_redirects=False)


def make_harness(
    providers: Mapping[Provider, ExternalProvider] | None = None,
    *,
    base_url: str = "http://testserver",
    policy: VerificationPolicy = DEFAULT_POLICY,
    aliases: tuple[str, ...] = (),
    with_ai: bool = True,
) -> Harness:
    ids = count(1)
    prepared_repo = InMemoryPreparedRequestRepository()
    pages = FakePageChecker({ESSAY.address: ESSAY}, texts={ESSAY.address: "On testing and trust."})
    web = WebPageArtifact()
    web.connect(PluginServices(pages=pages, reader=pages))
    users = InMemoryUserRepository()
    auth = AuthService(
        users,
        Argon2Hasher(time_cost=1, memory_cost=8, parallelism=1),
        lambda: f"u{next(ids)}",
    )
    outbox, clock = Outbox(), Clock()
    verification = VerificationService(
        users, InMemoryEmailTokenRepository(), outbox, base_url, clock
    )
    tenancy_repo = InMemoryTenancyRepository()
    tenancy = TenancyService(tenancy_repo, users, lambda: f"t{next(ids)}", clock, policy=policy)
    call_repo = InMemoryCallRepository()
    calls = CallsService(
        call_repo,
        tenancy,
        tenancy_repo,
        users,
        ArtifactRegistry([TextArtifact(), PdfArtifact(), web]),
        UnlimitedEntitlements(),
        lambda: f"c{next(ids)}",
        clock,
        policy=policy,
    )
    rubric_repo = InMemoryRubricRepository()
    criteria = CriterionRegistry(
        [NumericCriterion(), LevelsCriterion(), YesNoCriterion(), TextCriterion()]
    )
    artifacts = ArtifactRegistry([TextArtifact(), PdfArtifact(), web])
    rubrics = RubricsService(
        rubric_repo,
        call_repo,
        tenancy,
        criteria,
        lambda: f"r{next(ids)}",
    )
    round_repo, review_repo = InMemoryRoundRepository(), InMemoryReviewRepository()
    rounds = RoundsService(
        round_repo,
        review_repo,
        call_repo,
        tenancy,
        tenancy_repo,
        users,
        StrategyRegistry([RandomStrategy(), RoundRobinStrategy(), ManualStrategy()]),
        lambda: f"q{next(ids)}",
        clock,
    )
    invitations = InvitationsService(
        round_repo,
        call_repo,
        tenancy,
        tenancy_repo,
        users,
        UnlimitedEntitlements(),
        lambda: f"i{next(ids)}",
        clock,
        mailer=outbox,
        base_url=base_url,
        policy=policy,
    )
    reviews = ReviewsService(
        review_repo,
        round_repo,
        call_repo,
        rubric_repo,
        tenancy,
        tenancy_repo,
        users,
        criteria,
        artifacts,
        lambda: f"v{next(ids)}",
        clock,
    )
    quick = QuickReviewService(tenancy, calls, rounds, invitations, artifacts, users, clock)
    ai_repo, ai_writer, ai_jobs = InMemoryAiReviewRepository(), FakeWriter(), Jobs()
    credits = CreditsService(
        InMemoryCreditRepository(), users, [CreditPack("pri_5", 5), CreditPack("pri_10", 10)],
        ids=lambda: f"cr{next(ids)}", now=clock,
    )  # fmt: skip
    ai = AiReviewsService(
        ai_repo, FakeCatalog([LOCAL, SONNET, CHEAP, TINY]), ai_writer, ai_jobs, calls, artifacts,
        users, UnlimitedEntitlements(), outbox, base_url=base_url, ids=lambda: f"a{next(ids)}",
        now=clock, pricing=PRICING, credits=credits, house_keys={"anthropic": HOUSE},
    )  # fmt: skip
    ai_jobs.service = ai
    settings = Settings(
        secret_key="test-secret", base_url=base_url, verification_policy=policy, aliases=aliases,
        paddle_client_token="test_client_token", paddle_webhook_secret=PADDLE_SECRET,
        paddle_packs=(("pri_5", 5), ("pri_10", 10)), **SELLER,  # type: ignore[arg-type]
    )  # fmt: skip
    app = build_app(
        settings, auth, verification, tenancy, calls, rubrics, rounds, reviews, invitations, quick,
        dict(providers or {}), pages=pages,
        prepared=PreparedRequestsService(
            prepared_repo, lambda: secrets.token_urlsafe(32), clock
        ),
        ai=ai if with_ai else None,
        credits=credits,
    )  # fmt: skip
    client = TestClient(app, base_url=base_url, follow_redirects=False)
    return Harness(
        client, auth, outbox, clock, app, base_url, pages, prepared_repo, ai_writer, ai_jobs,
        ai_repo, credits,
    )  # fmt: skip


def make_client(
    providers: Mapping[Provider, ExternalProvider] | None = None,
    *,
    base_url: str = "http://testserver",
) -> tuple[TestClient, AuthService]:
    harness = make_harness(providers, base_url=base_url)
    return harness.client, harness.auth


def csrf_token(client: TestClient, path: str) -> str:
    html = client.get(path).text
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match, f"no csrf field on {path}"
    return match.group(1)
