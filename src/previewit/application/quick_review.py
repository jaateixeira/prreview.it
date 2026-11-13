"""Request a review in one step (ADR 0018).

For someone who just wants feedback on a file: one request makes the review space, publishes a
call, submits the file, opens a round and creates one personal invitation per reviewer, and
Previewit can mail them. It composes the other services; it adds no rules of its own.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from previewit.application.artifacts import ArtifactError, ArtifactRegistry, Upload
from previewit.application.calls import CallsService, ShareLimitReached
from previewit.application.invitations import InvitationsService
from previewit.application.ports import MailError, UserRepository
from previewit.application.rounds import RoundsService
from previewit.application.tenancy import TenancyService, VerificationRequired
from previewit.domain.calls import CallAccess, CallId, InvalidCall, SubmissionId, clean_title
from previewit.domain.identity import Email, UserId
from previewit.domain.invitations import InvalidInvitation
from previewit.domain.policy import Action
from previewit.domain.rounds import RoundId
from previewit.domain.tenancy import MAX_NAME_LENGTH, OrgRole, Role, SpaceId

DEFAULT_DAYS = 14
MAX_DAYS = 365
GENERAL_PRESET = "general"


class InvalidReviewRequest(ValueError):
    """Something in the request cannot work. The message is for the person."""


@dataclass(frozen=True)
class ReviewRequest:
    title: str
    upload: Upload  # a PDF, a text file or pasted text
    reviewers: Sequence[Email]
    cover_letter: str = ""
    send_emails: bool = True
    due: datetime | None = None  # when the reviews are due; two weeks from now if empty


@dataclass(frozen=True)
class InviteResult:
    address: str
    token: str  # shown once, to copy
    sent: bool  # Previewit mailed it
    error: str | None = None  # why it was not mailed


@dataclass(frozen=True)
class ReviewRequested:
    space_id: SpaceId
    call_id: CallId
    submission_id: SubmissionId
    round_id: RoundId
    invites: tuple[InviteResult, ...]
    not_invited: tuple[str, ...]  # left out because the sharing limit was reached


class QuickReviewService:
    def __init__(
        self,
        tenancy: TenancyService,
        calls: CallsService,
        rounds: RoundsService,
        invitations: InvitationsService,
        artifacts: ArtifactRegistry,
        users: UserRepository,
        now: Callable[[], datetime],
    ) -> None:
        self._tenancy = tenancy
        self._calls = calls
        self._rounds = rounds
        self._invitations = invitations
        self._artifacts = artifacts
        self._users = users
        self._now = now

    def request_review(self, actor: UserId, request: ReviewRequest) -> ReviewRequested:
        # Check everything that can be checked first, so a refusal leaves nothing behind.
        user = self._users.get(actor)
        if user is None:
            raise InvalidReviewRequest("Log in first.")
        try:
            title = clean_title(request.title)
        except InvalidCall as error:
            raise InvalidReviewRequest(f"Give the review a title: {error}.") from None
        if not request.reviewers:
            raise InvalidReviewRequest("Add at least one reviewer's email address.")
        now = self._now()
        due = request.due or now + timedelta(days=DEFAULT_DAYS)
        if not now < due <= now + timedelta(days=MAX_DAYS):
            raise InvalidReviewRequest("Choose a due date within the next year.")
        upload, kind = self._recognise(request.upload)
        self._artifacts.get(kind).ingest(upload)  # ArtifactError now, not after the space exists
        if request.send_emails and not user.email_verified:
            raise VerificationRequired(Action.INVITE)  # the mail goes out in their name

        org = self._organization(actor, user.display_name or "My")
        space = self._tenancy.create_space(actor, org, title[:MAX_NAME_LENGTH])
        self._tenancy.change_roles(actor, space.id, actor, {Role.ORGANIZER, Role.AUTHOR})
        call = self._calls.create_call(
            actor, space.id, title=title, artifact_type=kind, published=True,
            access=CallAccess.PROTECTED,
        )  # fmt: skip
        submission = self._calls.submit(actor, call.id, title=title, upload=upload)
        round_ = self._rounds.create_round(
            actor, call.id, per_submission=min(len(request.reviewers), 5),
            strategy_key="manual", closes_at=due,
        )  # fmt: skip

        invites: list[InviteResult] = []
        left_out: list[str] = []
        for email in request.reviewers:
            try:
                _, token = self._invitations.invite(actor, round_.id, email.value, [submission.id])
            except ShareLimitReached:
                left_out.append(email.value)
                continue
            except InvalidInvitation as error:  # cannot happen for a fresh round; keep it honest
                left_out.append(f"{email.value} ({error})")
                continue
            invites.append(self._deliver(actor, round_.id, email, token, request))
        return ReviewRequested(
            space.id, call.id, submission.id, round_.id, tuple(invites), tuple(left_out)
        )

    # -- helpers ----------------------------------------------------------------------------

    def _deliver(
        self, actor: UserId, round_id: RoundId, email: Email, token: str, request: ReviewRequest
    ) -> InviteResult:
        if not request.send_emails:
            return InviteResult(email.value, token, False)
        try:
            self._invitations.send(actor, round_id, token, request.cover_letter)
        except (MailError, OSError) as error:
            return InviteResult(
                email.value, token, False, f"The email could not be sent ({error})."
            )
        return InviteResult(email.value, token, True)

    def _organization(self, actor: UserId, name: str):
        owned = [o for o, role in self._tenancy.my_organizations(actor) if role is OrgRole.OWNER]
        if owned:
            return owned[0].id
        return self._tenancy.create_organization(actor, f"{name}'s reviews", GENERAL_PRESET).id

    @staticmethod
    def _recognise(upload: Upload) -> tuple[Upload, str]:
        """A PDF file stays a PDF. Any other file must be plain UTF-8 text. Pasted text is text."""
        if upload.content is None:
            return upload, "text"
        if upload.content.startswith(b"%PDF-"):
            return upload, "pdf"
        refusal = ArtifactError(
            "Previewit reviews PDF files and plain text. Save your file as a PDF or paste the text."
        )
        try:
            text = upload.content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise refusal from None
        if any(
            c < " " and c not in "\t\n\r\f" for c in text
        ):  # a binary file that happens to decode
            raise refusal
        return Upload(text=text), "text"
