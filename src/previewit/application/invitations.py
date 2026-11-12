"""The call for reviewers: personal invitations to review (ADR 0017).

Process 2 (organizing peer review): the organizer invites each reviewer by email and may
attach the work they should review. Process 3 (review by invitation): the invited person
opens the link with that verified email, becomes a Reviewer in the Space and finds their
review tasks. A token is a secret: only its hash is stored, and it works for one email.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from previewit.application.calls import ShareLimitReached
from previewit.application.ports import (
    CallRepository,
    DuplicateTask,
    Entitlements,
    RoundRepository,
    TenancyRepository,
    UserRepository,
)
from previewit.application.rounds import slot_of
from previewit.application.tenancy import Forbidden, NotFound, TenancyService, VerificationRequired
from previewit.application.verification import hash_token
from previewit.domain.allocation import conflicts
from previewit.domain.calls import Call, SubmissionId
from previewit.domain.identity import UserId
from previewit.domain.invitations import (
    MAX_SUBMISSIONS_PER_INVITATION,
    InvalidInvitation,
    Invitation,
    clean_email,
    mask_email,
)
from previewit.domain.party import UserParty
from previewit.domain.policy import DEFAULT_POLICY, Action, VerificationPolicy
from previewit.domain.rounds import ReviewRound, ReviewTask, RoundId, RoundStatus, TaskId
from previewit.domain.tenancy import Permission, Role, SpaceId

DEFAULT_INVITATION_TTL = timedelta(days=30)


class InvalidInvitationLink(Exception):
    """The token is unknown, revoked, expired, used by someone else or for a closed round."""


class WrongEmail(Exception):
    """The signed-in person's email is not the one the invitation was sent to."""

    def __init__(self, hint: str) -> None:
        super().__init__("this invitation is for another email address")
        self.hint = hint  # the invited address with most of it hidden


@dataclass(frozen=True)
class InvitationView:
    id: str
    email: str
    status: str  # waiting | accepted | revoked | expired
    work: list[str]  # titles of the submissions the reviewer is asked to review
    expires_at: datetime
    accepted_by: str | None


@dataclass(frozen=True)
class InvitationPreview:
    call_title: str
    round_number: int
    space_name: str
    organization_name: str
    invited_by: str
    email_hint: str
    work_count: int


@dataclass(frozen=True)
class Accepted:
    space_id: SpaceId
    created: int  # review tasks made now
    skipped: int  # work the person could not be given, such as their own


class InvitationsService:
    def __init__(
        self,
        repo: RoundRepository,
        calls_repo: CallRepository,
        tenancy: TenancyService,
        tenancy_repo: TenancyRepository,
        users: UserRepository,
        entitlements: Entitlements,
        new_id: Callable[[], str],
        now: Callable[[], datetime],
        *,
        policy: VerificationPolicy = DEFAULT_POLICY,
    ) -> None:
        self._repo = repo
        self._calls = calls_repo
        self._tenancy = tenancy
        self._tenancy_repo = tenancy_repo
        self._users = users
        self._entitlements = entitlements
        self._new_id = new_id
        self._now = now
        self._policy = policy

    # -- the organizer's side ---------------------------------------------------------------

    def invite(
        self,
        actor: UserId,
        round_id: RoundId,
        email: str,
        submission_ids: Sequence[SubmissionId] = (),
        *,
        ttl: timedelta = DEFAULT_INVITATION_TTL,
    ) -> tuple[Invitation, str]:
        round_, call = self._managed(actor, round_id)
        self._need_verified(actor, Action.INVITE)
        address = clean_email(email)
        if round_.status(self._now()) is RoundStatus.CLOSED:
            raise InvalidInvitation("This round has closed.")
        work = tuple(dict.fromkeys(submission_ids))
        if len(work) > MAX_SUBMISSIONS_PER_INVITATION:
            raise InvalidInvitation(
                f"One invitation can carry up to {MAX_SUBMISSIONS_PER_INVITATION} submissions."
            )
        for submission_id in work:
            submission = self._calls.get_submission(submission_id)
            if submission is None or submission.call_id != call.id:
                raise NotFound
        now = self._now()
        if any(
            i.email == address and i.usable(now) and i.accepted_by is None
            for i in self._repo.invitations_of_round(round_id)
        ):
            raise InvalidInvitation(
                "This person already has an invitation to this round. Revoke it to send another."
            )
        shares = self._calls.count_share_links(actor) + self._repo.count_invitations(actor)
        if not self._entitlements.may_create_share(actor, shares):
            raise ShareLimitReached
        token = secrets.token_urlsafe(32)
        invitation = Invitation(
            hash_token(token),
            round_.org_id,
            round_.space_id,
            round_.id,
            address,
            work,
            actor,
            now + ttl,
            False,
            None,
        )
        self._repo.add_invitation(invitation)
        return invitation, token

    def invitations(self, actor: UserId, round_id: RoundId) -> list[InvitationView]:
        self._managed(actor, round_id)
        now = self._now()
        views: list[InvitationView] = []
        for inv in self._repo.invitations_of_round(round_id):
            titles = [
                s.title
                for sid in inv.submission_ids
                if (s := self._calls.get_submission(sid)) is not None
            ]
            who = self._users.get(inv.accepted_by) if inv.accepted_by else None
            views.append(
                InvitationView(
                    inv.id,
                    inv.email.value,
                    inv.status(now),
                    titles,
                    inv.expires_at,
                    who.display_name if who else None,
                )
            )
        return views

    def revoke(self, actor: UserId, round_id: RoundId, invitation_id: str) -> None:
        self._managed(actor, round_id)
        inv = self._repo.get_invitation(invitation_id)
        if inv is None or inv.round_id != round_id:
            raise NotFound
        self._repo.update_invitation(replace(inv, revoked=True))

    # -- the reviewer's side ----------------------------------------------------------------

    def preview(self, token: str) -> InvitationPreview | None:
        """What an anonymous visitor may know about a link: no names of authors, no work."""
        found = self._live(token)
        if found is None:
            return None
        inv, round_, call = found
        space = self._tenancy_repo.get_space(inv.space_id)
        org = self._tenancy_repo.get_org(inv.org_id)
        inviter = self._users.get(inv.created_by)
        if space is None or org is None:
            return None
        return InvitationPreview(
            call.title,
            round_.number,
            space.name,
            org.name,
            inviter.display_name if inviter else "Someone",
            mask_email(inv.email),
            len(inv.submission_ids),
        )

    def readiness(self, actor: UserId, token: str) -> str:
        """What the signed-in person must do before opening: `ready`, `confirm_email` (their
        address matches but is not verified yet) or `other_email` (a different account)."""
        found = self._live(token)
        if found is None:
            raise InvalidInvitationLink
        user = self._users.get(actor)
        if user is None or user.email != found[0].email:
            return "other_email"
        return "ready" if user.email_verified else "confirm_email"

    def accept(self, actor: UserId, token: str) -> Accepted:
        found = self._live(token)
        if found is None:
            raise InvalidInvitationLink
        inv, round_, _ = found
        if inv.accepted_by is not None and inv.accepted_by != actor:
            raise InvalidInvitationLink
        user = self._users.get(actor)
        if user is None or user.email != inv.email:
            raise WrongEmail(mask_email(inv.email))
        if not user.email_verified:
            raise VerificationRequired(Action.REVIEW)
        self._tenancy.admit(actor, inv.space_id, {Role.REVIEWER}, extend=True)
        groups = {g.id: g.members for g in self._tenancy_repo.groups_in_space(inv.space_id)}
        me = UserParty(actor)
        created = skipped = 0
        for submission_id in inv.submission_ids:
            submission = self._calls.get_submission(submission_id)
            if submission is None or conflicts(
                slot_of(me, groups), slot_of(submission.author, groups)
            ):
                skipped += 1
                continue
            latest = max((r.number for r in self._calls.revision_infos(submission.id)), default=1)
            task = ReviewTask(
                TaskId(self._new_id()),
                round_.org_id,
                round_.space_id,
                round_.id,
                me,
                submission.id,
                latest,
                True,
            )
            try:
                self._repo.add_tasks([task])
            except DuplicateTask:
                continue  # opened before: the task is already there
            created += 1
        if inv.accepted_by is None:
            self._repo.update_invitation(replace(inv, accepted_by=actor))
        return Accepted(inv.space_id, created, skipped)

    # -- helpers ----------------------------------------------------------------------------

    def _managed(self, actor: UserId, round_id: RoundId) -> tuple[ReviewRound, Call]:
        round_ = self._repo.get_round(round_id)
        call = self._calls.get_call(round_.call_id) if round_ else None
        if round_ is None or call is None:
            raise NotFound
        view = self._tenancy.space_view(actor, call.space_id)  # NotFound for outsiders
        if Permission.ROUNDS_MANAGE not in view.permissions:
            raise Forbidden
        return round_, call

    def _live(self, token: str) -> tuple[Invitation, ReviewRound, Call] | None:
        if not token:
            return None
        inv = self._repo.get_invitation(hash_token(token))
        if inv is None or not inv.usable(self._now()):
            return None
        round_ = self._repo.get_round(inv.round_id)
        call = self._calls.get_call(round_.call_id) if round_ else None
        if round_ is None or call is None or round_.status(self._now()) is RoundStatus.CLOSED:
            return None
        return inv, round_, call

    def _need_verified(self, actor: UserId, action: Action) -> None:
        if action not in self._policy.required_for:
            return
        user = self._users.get(actor)
        if user is None or not self._policy.allows(user, action):
            raise VerificationRequired(action)
