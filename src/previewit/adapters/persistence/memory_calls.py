"""In-memory call repository: a fast fake that follows the same contract as the SQL one."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime

from previewit.application.ports import DuplicateSubmission
from previewit.domain.calls import (
    Artifact,
    Call,
    CallId,
    Revision,
    RevisionInfo,
    ShareGrant,
    ShareLink,
    ShareTarget,
    Submission,
    SubmissionId,
)
from previewit.domain.identity import UserId
from previewit.domain.party import Party
from previewit.domain.tenancy import SpaceId


class InMemoryCallRepository:
    def __init__(self) -> None:
        self._calls: dict[CallId, Call] = {}
        self._submissions: dict[SubmissionId, Submission] = {}
        self._revisions: dict[SubmissionId, list[Revision]] = {}
        self._links: dict[str, ShareLink] = {}
        self._grants: set[ShareGrant] = set()

    # -- calls ------------------------------------------------------------------------

    def add_call(self, call: Call) -> None:
        self._calls[call.id] = call

    def get_call(self, call_id: CallId) -> Call | None:
        return self._calls.get(call_id)

    def update_call(self, call: Call) -> None:
        if call.id in self._calls:
            self._calls[call.id] = call

    def delete_call(self, call_id: CallId) -> None:
        self._calls.pop(call_id, None)
        for sid in [s.id for s in self._submissions.values() if s.call_id == call_id]:
            del self._submissions[sid]
            self._revisions.pop(sid, None)
        for link_id in [
            link.id
            for link in self._links.values()
            if link.target is ShareTarget.CALL and link.target_id == call_id
        ]:
            del self._links[link_id]
        self._grants = {
            g for g in self._grants if not (g.target is ShareTarget.CALL and g.target_id == call_id)
        }

    def calls_in_space(self, space_id: SpaceId) -> list[Call]:
        return [c for c in self._calls.values() if c.space_id == space_id]

    # -- submissions and revisions ------------------------------------------------------

    def add_submission(
        self, submission: Submission, artifact: Artifact, created_by: UserId, now: datetime
    ) -> Revision:
        if any(
            s.call_id == submission.call_id and s.author == submission.author
            for s in self._submissions.values()
        ):
            raise DuplicateSubmission
        self._submissions[submission.id] = submission
        self._revisions[submission.id] = []
        return self.add_revision(submission.id, artifact, created_by, now)

    def get_submission(self, submission_id: SubmissionId) -> Submission | None:
        return self._submissions.get(submission_id)

    def submissions_in_call(self, call_id: CallId) -> list[Submission]:
        found = [s for s in self._submissions.values() if s.call_id == call_id]
        return sorted(found, key=lambda s: (s.created_at, s.id))

    def submissions_of_parties(self, call_id: CallId, parties: Sequence[Party]) -> list[Submission]:
        return [s for s in self.submissions_in_call(call_id) if s.author in parties]

    def add_revision(
        self, submission_id: SubmissionId, artifact: Artifact, created_by: UserId, now: datetime
    ) -> Revision:
        submission = self._submissions[submission_id]
        existing = self._revisions[submission_id]
        revision = Revision(
            submission_id, submission.org_id, len(existing) + 1, artifact, created_by, now
        )
        existing.append(revision)
        return revision

    def revision_infos(self, submission_id: SubmissionId) -> list[RevisionInfo]:
        return [
            RevisionInfo(
                r.number,
                r.artifact.media_type,
                r.artifact.size,
                r.artifact.digest,
                r.artifact.filename,
                r.created_by,
                r.created_at,
            )
            for r in self._revisions.get(submission_id, [])
        ]

    def get_revision(self, submission_id: SubmissionId, number: int) -> Revision | None:
        return next((r for r in self._revisions.get(submission_id, []) if r.number == number), None)

    # -- sharing ----------------------------------------------------------------------------

    def add_share_link(self, link: ShareLink) -> None:
        self._links[link.id] = link

    def get_share_link(self, link_id: str) -> ShareLink | None:
        return self._links.get(link_id)

    def share_links_for(self, target: ShareTarget, target_id: str) -> list[ShareLink]:
        return [
            link
            for link in self._links.values()
            if link.target is target and link.target_id == target_id
        ]

    def revoke_share_link(self, link_id: str) -> None:
        if link_id in self._links:
            self._links[link_id] = replace(self._links[link_id], revoked=True)

    def count_share_links(self, created_by: UserId) -> int:
        return sum(1 for link in self._links.values() if link.created_by == created_by)

    def add_share_grant(self, grant: ShareGrant) -> None:
        self._grants.add(grant)

    def has_share_grant(self, user_id: UserId, target: ShareTarget, target_id: str) -> bool:
        return any(
            g.user_id == user_id and g.target is target and g.target_id == target_id
            for g in self._grants
        )

    def share_grants_for(self, user_id: UserId) -> list[ShareGrant]:
        return [g for g in self._grants if g.user_id == user_id]
