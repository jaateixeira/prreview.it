"""Calls, submissions, revisions and share links (review by link)."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from previewit.application.artifacts import ArtifactRegistry, ArtifactType, Upload
from previewit.application.ports import (
    CallRepository,
    DuplicateSubmission,
    Entitlements,
    TenancyRepository,
    UserRepository,
)
from previewit.application.tenancy import Forbidden, NotFound, TenancyService, VerificationRequired
from previewit.application.verification import hash_token
from previewit.domain.calls import (
    Call,
    CallAccess,
    CallId,
    Revision,
    RevisionInfo,
    ShareGrant,
    ShareLink,
    ShareTarget,
    Submission,
    SubmissionId,
    clean_description,
    clean_title,
)
from previewit.domain.identity import UserId
from previewit.domain.party import GroupParty, Party, UserParty
from previewit.domain.policy import DEFAULT_POLICY, Action, VerificationPolicy
from previewit.domain.tenancy import GroupId, Permission, Preset, Role, Space, SpaceId

DEFAULT_SHARE_TTL = timedelta(days=30)


class CallClosed(Exception):
    """The call is unpublished or past its deadline."""


class CallHasSubmissions(Exception):
    pass


class AlreadySubmitted(Exception):
    """This party already has a submission for the call: add a revision instead."""


class ShareLimitReached(Exception):
    """The plan does not allow more share links."""


class InvalidShare(Exception):
    pass


@dataclass(frozen=True)
class SubmissionSummary:
    submission: Submission
    author_name: str
    revisions: int


@dataclass(frozen=True)
class SpaceCalls:
    space: Space
    preset: Preset
    can_manage: bool
    calls: list[Call]


@dataclass(frozen=True)
class SubmitOption:
    party: Party
    label: str
    existing: Submission | None


@dataclass(frozen=True)
class CallView:
    call: Call
    space: Space | None  # None for a guest who came by a share link
    preset: Preset | None
    permissions: frozenset[Permission]
    guest: bool
    artifact_type: ArtifactType
    can_submit: bool
    options: list[SubmitOption]
    mine: list[SubmissionSummary]
    everyone: list[SubmissionSummary] | None  # only for people who may see all work


@dataclass(frozen=True)
class SubmissionView:
    submission: Submission
    call: Call
    author_name: str
    revisions: list[RevisionInfo]
    latest: Revision
    artifact_type: ArtifactType
    can_revise: bool
    can_share: bool
    guest: bool


@dataclass(frozen=True)
class SharePreview:
    target: ShareTarget
    title: str
    shared_by: str


@dataclass(frozen=True)
class CallPreview:
    """What a visitor sees before signing in, at a public call's address."""

    title: str
    description: str
    space_name: str
    organization_name: str
    closes_at: datetime | None
    accepting: bool


@dataclass(frozen=True)
class SharedItem:
    target: ShareTarget
    target_id: str
    title: str


@dataclass(frozen=True)
class _Access:
    call: Call
    perms: frozenset[Permission]
    guest: bool
    space: Space | None
    preset: Preset | None


class CallsService:
    def __init__(
        self,
        repo: CallRepository,
        tenancy: TenancyService,
        tenancy_repo: TenancyRepository,
        users: UserRepository,
        artifacts: ArtifactRegistry,
        entitlements: Entitlements,
        new_id: Callable[[], str],
        now: Callable[[], datetime],
        *,
        policy: VerificationPolicy = DEFAULT_POLICY,
    ) -> None:
        self._repo = repo
        self._tenancy = tenancy
        self._tenancy_repo = tenancy_repo
        self._users = users
        self._artifacts = artifacts
        self._entitlements = entitlements
        self._new_id = new_id
        self._now = now
        self._policy = policy

    # -- calls ----------------------------------------------------------------------------

    def artifact_types(self) -> list[ArtifactType]:
        return self._artifacts.all()

    def create_call(
        self,
        actor: UserId,
        space_id: SpaceId,
        *,
        title: str,
        description: str = "",
        artifact_type: str,
        group_work: bool = False,
        closes_at: datetime | None = None,
        published: bool = False,
        access: CallAccess = CallAccess.PROTECTED,
    ) -> Call:
        view = self._tenancy.space_view(actor, space_id)
        if Permission.CALLS_MANAGE not in view.permissions:
            raise Forbidden
        self._artifacts.get(artifact_type)  # UnknownArtifactType for anything not installed
        call = Call(
            CallId(self._new_id()),
            view.space.org_id,
            space_id,
            clean_title(title),
            clean_description(description),
            artifact_type,
            group_work,
            closes_at,
            published,
            actor,
            access=access,
        )
        self._repo.add_call(call)
        return call

    def update_call(
        self,
        actor: UserId,
        call_id: CallId,
        *,
        title: str,
        description: str,
        closes_at: datetime | None,
        published: bool,
        access: CallAccess | None = None,
    ) -> Call:
        call = self._managed(actor, call_id)
        updated = replace(
            call,
            title=clean_title(title),
            description=clean_description(description),
            closes_at=closes_at,
            published=published,
            access=access or call.access,
        )
        self._repo.update_call(updated)
        return updated

    def delete_call(self, actor: UserId, call_id: CallId) -> None:
        call = self._managed(actor, call_id)
        if self._repo.submissions_in_call(call.id):
            raise CallHasSubmissions
        self._repo.delete_call(call.id)

    def space_calls(self, actor: UserId, space_id: SpaceId) -> SpaceCalls:
        view = self._tenancy.space_view(actor, space_id)
        found = self._repo.calls_in_space(space_id)
        manage = Permission.CALLS_MANAGE in view.permissions
        visible = found if manage else [c for c in found if c.published]
        return SpaceCalls(view.space, view.preset, manage, visible)

    def calls(self, actor: UserId, space_id: SpaceId) -> list[Call]:
        return self.space_calls(actor, space_id).calls

    def call_view(self, actor: UserId, call_id: CallId) -> CallView:
        access = self._call_access(actor, call_id)
        call = access.call
        artifact_type = self._artifacts.get(call.artifact_type)
        options: list[SubmitOption] = []
        mine: list[SubmissionSummary] = []
        everyone: list[SubmissionSummary] | None = None
        if not access.guest:
            parties = self._my_parties(actor, call)
            existing = {s.author: s for s in self._repo.submissions_of_parties(call.id, parties)}
            options = [SubmitOption(p, self._party_label(p), existing.get(p)) for p in parties]
            mine = self._summaries(list(existing.values()))
            if Permission.SUBMISSIONS_VIEW_ALL in access.perms:
                everyone = self._summaries(self._repo.submissions_in_call(call.id))
        can_submit = (
            not access.guest and Permission.SUBMIT in access.perms and call.accepting(self._now())
        )
        return CallView(
            call, access.space, access.preset, access.perms, access.guest, artifact_type,
            can_submit, options, mine, everyone,
        )  # fmt: skip

    # -- submissions and revisions --------------------------------------------------------

    def submit(
        self,
        actor: UserId,
        call_id: CallId,
        *,
        title: str,
        upload: Upload,
        group_id: GroupId | None = None,
    ) -> Submission:
        access = self._call_access(actor, call_id)
        call = access.call
        if access.guest or Permission.SUBMIT not in access.perms:
            raise Forbidden
        if not call.accepting(self._now()):
            raise CallClosed
        self._need_verified(actor, Action.SUBMIT)
        party = self._party_for(actor, call, group_id)
        cleaned = clean_title(title)
        artifact = self._artifacts.get(call.artifact_type).ingest(upload)
        submission = Submission(
            SubmissionId(self._new_id()), call.org_id, call.space_id, call.id, party, cleaned,
            self._now(),
        )  # fmt: skip
        try:
            self._repo.add_submission(submission, artifact, actor, self._now())
        except DuplicateSubmission:
            raise AlreadySubmitted from None
        return submission

    def revise(self, actor: UserId, submission_id: SubmissionId, upload: Upload) -> Revision:
        submission, access = self._submission_access(actor, submission_id)
        if not self._is_author(actor, submission) or access.guest:
            raise Forbidden
        if Permission.SUBMIT not in access.perms:
            raise Forbidden
        if not access.call.accepting(self._now()):
            raise CallClosed
        self._need_verified(actor, Action.SUBMIT)
        artifact = self._artifacts.get(access.call.artifact_type).ingest(upload)
        return self._repo.add_revision(submission.id, artifact, actor, self._now())

    def submission_view(self, actor: UserId, submission_id: SubmissionId) -> SubmissionView:
        submission, access = self._submission_access(actor, submission_id)
        infos = self._repo.revision_infos(submission.id)
        latest = self._repo.get_revision(submission.id, infos[-1].number)
        if latest is None:  # a submission always has a revision
            raise NotFound
        author = self._party_label(submission.author)
        is_author = self._is_author(actor, submission)
        open_ = access.call.accepting(self._now())
        return SubmissionView(
            submission, access.call, author, infos, latest,
            self._artifacts.get(access.call.artifact_type),
            can_revise=is_author and open_ and Permission.SUBMIT in access.perms,
            can_share=is_author or Permission.CALLS_MANAGE in access.perms,
            guest=access.guest,
        )  # fmt: skip

    def revision(self, actor: UserId, submission_id: SubmissionId, number: int) -> Revision:
        submission, _ = self._submission_access(actor, submission_id)
        revision = self._repo.get_revision(submission.id, number)
        if revision is None:
            raise NotFound
        return revision

    # -- review by link ------------------------------------------------------------------------

    def create_share(
        self,
        actor: UserId,
        target: ShareTarget,
        target_id: str,
        *,
        ttl: timedelta = DEFAULT_SHARE_TTL,
    ) -> tuple[ShareLink, str]:
        org_id, space_id = self._shareable(actor, target, target_id)
        self._need_verified(actor, Action.INVITE)
        if not self._entitlements.may_create_share(actor, self._repo.count_share_links(actor)):
            raise ShareLimitReached
        token = secrets.token_urlsafe(32)
        link = ShareLink(
            hash_token(token), org_id, space_id, target, target_id, actor, self._now() + ttl, False
        )
        self._repo.add_share_link(link)
        return link, token

    def shares(self, actor: UserId, target: ShareTarget, target_id: str) -> list[ShareLink]:
        self._shareable(actor, target, target_id)
        return self._repo.share_links_for(target, target_id)

    def revoke_share(
        self, actor: UserId, target: ShareTarget, target_id: str, link_id: str
    ) -> None:
        self._shareable(actor, target, target_id)
        link = self._repo.get_share_link(link_id)
        if link is None or link.target is not target or link.target_id != target_id:
            raise NotFound
        self._repo.revoke_share_link(link_id)

    def preview_share(self, token: str) -> SharePreview | None:
        found = self._live_share(token)
        if found is None:
            return None
        link, title = found
        creator = self._users.get(link.created_by)
        return SharePreview(link.target, title, creator.display_name if creator else "Someone")

    def accept_share(self, actor: UserId, token: str) -> SharedItem:
        found = self._live_share(token)
        if found is None:
            raise InvalidShare
        link, title = found
        if link.target is ShareTarget.CALL:  # a call link is a call for authors (ADR 0017)
            call = self._repo.get_call(CallId(link.target_id))
            if call is None:
                raise InvalidShare
            self._tenancy.admit(actor, call.space_id, {Role.AUTHOR})
        self._repo.add_share_grant(
            ShareGrant(link.org_id, link.space_id, actor, link.target, link.target_id)
        )
        return SharedItem(link.target, link.target_id, title)

    def public_preview(self, call_id: CallId) -> CallPreview | None:
        """What anyone may see at a public call's plain address; None for anything else."""
        call = self._repo.get_call(call_id)
        if call is None or not call.published or call.access is not CallAccess.PUBLIC:
            return None
        space = self._tenancy_repo.get_space(call.space_id)
        org = self._tenancy_repo.get_org(call.org_id)
        if space is None or org is None:
            return None
        return CallPreview(
            call.title, call.description, space.name, org.name, call.closes_at,
            call.accepting(self._now()),
        )  # fmt: skip

    def open_public(self, actor: UserId, call_id: CallId) -> SharedItem:
        """Become an author through a public call's plain address."""
        call = self._repo.get_call(call_id)
        if self.public_preview(call_id) is None or call is None:
            raise NotFound
        self._tenancy.admit(actor, call.space_id, {Role.AUTHOR})
        return SharedItem(ShareTarget.CALL, call.id, call.title)

    def shared_with_me(self, actor: UserId) -> list[SharedItem]:
        items: list[SharedItem] = []
        for grant in self._repo.share_grants_for(actor):
            title = self._target_title(grant.target, grant.target_id)
            if title is not None:
                items.append(SharedItem(grant.target, grant.target_id, title))
        return sorted(items, key=lambda i: i.title.lower())

    # -- helpers ---------------------------------------------------------------------

    def _need_verified(self, actor: UserId, action: Action) -> None:
        if action not in self._policy.required_for:
            return
        user = self._users.get(actor)
        if user is None or not self._policy.allows(user, action):
            raise VerificationRequired(action)

    def _managed(self, actor: UserId, call_id: CallId) -> Call:
        call = self._repo.get_call(call_id)
        if call is None:
            raise NotFound
        view = self._tenancy.space_view(actor, call.space_id)
        if Permission.CALLS_MANAGE not in view.permissions:
            raise Forbidden
        return call

    def _call_access(self, actor: UserId, call_id: CallId) -> _Access:
        call = self._repo.get_call(call_id)
        if call is None:
            raise NotFound
        try:
            view = self._tenancy.space_view(actor, call.space_id)
        except NotFound:
            if self._repo.has_share_grant(actor, ShareTarget.CALL, call.id):
                return _Access(call, frozenset(), True, None, None)
            raise
        if not call.published and Permission.CALLS_MANAGE not in view.permissions:
            raise NotFound
        return _Access(call, view.permissions, False, view.space, view.preset)

    def _submission_access(
        self, actor: UserId, submission_id: SubmissionId
    ) -> tuple[Submission, _Access]:
        submission = self._repo.get_submission(submission_id)
        call = self._repo.get_call(submission.call_id) if submission else None
        if submission is None or call is None:
            raise NotFound
        granted = self._repo.has_share_grant(actor, ShareTarget.SUBMISSION, submission.id)
        try:
            view = self._tenancy.space_view(actor, call.space_id)
        except NotFound:
            if granted:
                return submission, _Access(call, frozenset(), True, None, None)
            raise
        allowed = (
            self._is_author(actor, submission)
            or Permission.SUBMISSIONS_VIEW_ALL in view.permissions
            or granted
        )
        if not allowed:
            raise NotFound  # a peer's work is invisible, not merely forbidden
        return submission, _Access(call, view.permissions, False, view.space, view.preset)

    def _is_author(self, actor: UserId, submission: Submission) -> bool:
        author = submission.author
        if isinstance(author, UserParty):
            return author.user_id == actor
        group = self._tenancy_repo.get_group(GroupId(author.group_id))
        return group is not None and actor in group.members

    def _my_parties(self, actor: UserId, call: Call) -> list[Party]:
        if not call.group_work:
            return [UserParty(actor)]
        return [
            GroupParty(g.id)
            for g in self._tenancy_repo.groups_in_space(call.space_id)
            if actor in g.members
        ]

    def _party_for(self, actor: UserId, call: Call, group_id: GroupId | None) -> Party:
        if not call.group_work:
            return UserParty(actor)
        mine = {p for p in self._my_parties(actor, call) if isinstance(p, GroupParty)}
        if group_id is None and len(mine) == 1:
            return next(iter(mine))
        if group_id is None or GroupParty(group_id) not in mine:
            raise Forbidden  # you can only submit for a group you belong to
        return GroupParty(group_id)

    def _party_label(self, party: Party) -> str:
        if isinstance(party, UserParty):
            user = self._users.get(UserId(party.user_id))
            return user.display_name if user else "Unknown"
        group = self._tenancy_repo.get_group(GroupId(party.group_id))
        return group.name if group else "Unknown group"

    def _summaries(self, submissions: list[Submission]) -> list[SubmissionSummary]:
        return [
            SubmissionSummary(s, self._party_label(s.author), len(self._repo.revision_infos(s.id)))
            for s in submissions
        ]

    def _shareable(self, actor: UserId, target: ShareTarget, target_id: str):
        if target is ShareTarget.CALL:
            call = self._managed(actor, CallId(target_id))
            return call.org_id, call.space_id
        submission, access = self._submission_access(actor, SubmissionId(target_id))
        if access.guest or not (
            self._is_author(actor, submission) or Permission.CALLS_MANAGE in access.perms
        ):
            raise Forbidden
        return submission.org_id, submission.space_id

    def _target_title(self, target: ShareTarget, target_id: str) -> str | None:
        if target is ShareTarget.CALL:
            call = self._repo.get_call(CallId(target_id))
            return call.title if call else None
        submission = self._repo.get_submission(SubmissionId(target_id))
        return submission.title if submission else None

    def _live_share(self, token: str) -> tuple[ShareLink, str] | None:
        if not token:
            return None
        link = self._repo.get_share_link(hash_token(token))
        if link is None or not link.usable(self._now()):
            return None
        title = self._target_title(link.target, link.target_id)
        if link.target is ShareTarget.CALL:
            call = self._repo.get_call(CallId(link.target_id))
            if call is None or not call.published:
                return None  # a draft call admits nobody
        return None if title is None else (link, title)
