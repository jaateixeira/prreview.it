"""The review workspace: answering a rubric, pinning comments, group-shared editing."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime

from previewit.application.artifacts import ArtifactError, ArtifactRegistry, ArtifactType
from previewit.application.criteria import CriterionError, CriterionRegistry
from previewit.application.ports import (
    CallRepository,
    DuplicateReview,
    ReviewRepository,
    RoundRepository,
    RubricRepository,
    TenancyRepository,
    UserRepository,
)
from previewit.application.tenancy import Forbidden, NotFound, TenancyService
from previewit.domain.calls import Call, Revision, Submission
from previewit.domain.identity import UserId
from previewit.domain.party import GroupParty, Party, UserParty
from previewit.domain.reviews import (
    Annotation,
    AnnotationId,
    InvalidReview,
    Review,
    ReviewClosed,
    ReviewConflict,
    ReviewEdit,
    ReviewId,
    clean_comment,
)
from previewit.domain.rounds import ReviewRound, ReviewTask, RoundStatus, TaskId
from previewit.domain.rubrics import Criterion
from previewit.domain.tenancy import GroupId, Permission


@dataclass(frozen=True)
class QuestionView:
    criterion: Criterion
    input_html: str  # the plugin's input, filled with the saved answer
    answer: str
    error: str | None = None


@dataclass(frozen=True)
class AnnotationView:
    annotation: Annotation
    author_label: str
    can_delete: bool


@dataclass(frozen=True)
class EditView:
    version: int
    user_label: str
    at: datetime


@dataclass(frozen=True)
class Workspace:
    task: ReviewTask
    call: Call
    submission: Submission
    revision: Revision
    round: ReviewRound
    artifact_type: ArtifactType
    artifact_html: str
    raw_url: str
    questions: list[QuestionView]
    rubric_name: str | None
    review: Review | None
    version: int  # 0 until the first save
    can_edit: bool
    closed: bool
    reviewer_label: str
    shared: bool  # a group review: several people may edit
    annotations: list[AnnotationView]
    trail: list[EditView]
    annotatable: bool


@dataclass(frozen=True)
class Access:
    task: ReviewTask
    round: ReviewRound
    call: Call
    is_reviewer: bool  # you, or your group, were given the task
    can_edit: bool


class ReviewsService:
    def __init__(
        self,
        repo: ReviewRepository,
        rounds_repo: RoundRepository,
        calls_repo: CallRepository,
        rubrics_repo: RubricRepository,
        tenancy: TenancyService,
        tenancy_repo: TenancyRepository,
        users: UserRepository,
        criteria: CriterionRegistry,
        artifacts: ArtifactRegistry,
        new_id: Callable[[], str],
        clock: Callable[[], datetime],
    ) -> None:
        self._repo = repo
        self._rounds = rounds_repo
        self._calls = calls_repo
        self._rubrics = rubrics_repo
        self._tenancy = tenancy
        self._tenancy_repo = tenancy_repo
        self._users = users
        self._criteria = criteria
        self._artifacts = artifacts
        self._new_id = new_id
        self._now = clock

    # -- reading ----------------------------------------------------------

    def workspace(
        self,
        actor: UserId,
        task_id: TaskId,
        *,
        draft: Mapping[str, str] | None = None,
        errors: Mapping[str, str] | None = None,
    ) -> Workspace:
        """Everything the review page shows. `draft` and `errors` re-show unsaved answers."""
        access = self._access(actor, task_id)
        task, round_, call = access.task, access.round, access.call
        submission = self._calls.get_submission(task.submission_id)
        revision = self._calls.get_revision(task.submission_id, task.revision_number)
        if submission is None or revision is None:
            raise NotFound
        review = self._repo.review_of_task(task.id)
        saved = review.answers if review else {}
        shown = {**saved, **(draft or {})}
        artifact_type = self._artifacts.get(call.artifact_type)
        raw_url = f"/tasks/{task.id}/raw"
        questions: list[QuestionView] = []
        rubric_name = None
        if call.rubric_id is not None:
            rubric = self._rubrics.get_rubric(call.rubric_id)
            rubric_name = rubric.name if rubric else None
            for c in self._rubrics.criteria_of(call.rubric_id):
                kind = self._criteria.get(c.type_key)
                value = shown.get(c.id, "")
                html = kind.render_html(c.config, f"criterion-{c.id}", value)
                questions.append(QuestionView(c, html, value, (errors or {}).get(c.id)))
        annotatable = bool(artifact_type.annotation_kind)
        return Workspace(
            task,
            call,
            submission,
            revision,
            round_,
            artifact_type,
            artifact_type.render_html(revision.artifact, raw_url),
            raw_url,
            questions,
            rubric_name,
            review,
            review.version if review else 0,
            access.can_edit,
            round_.status(self._now()) is RoundStatus.CLOSED,
            self._party_label(task.reviewer),
            isinstance(task.reviewer, GroupParty),
            self._annotation_views(actor, review, access) if review else [],
            self._trail(review) if review else [],
            annotatable,
        )

    def raw(self, actor: UserId, task_id: TaskId) -> Revision:
        """The revision a task points at, for the artifact viewer (for example a PDF)."""
        access = self._access(actor, task_id)
        revision = self._calls.get_revision(access.task.submission_id, access.task.revision_number)
        if revision is None:
            raise NotFound
        return revision

    # -- the review form --------------------------------------------------

    def save(
        self,
        actor: UserId,
        task_id: TaskId,
        answers: Mapping[str, str],
        expected_version: int,
        *,
        submit: bool = False,
    ) -> Review:
        """Save a draft (or submit). Raises CriterionErrors for bad answers, InvalidReview for
        missing required ones on submit, ReviewConflict if someone saved since you loaded."""
        access = self._access(actor, task_id, write=True)
        existing = self._repo.review_of_task(task_id)
        clean, problems = self._check(access.call, answers)
        if problems:
            raise AnswerErrors(problems)
        final = submit or bool(existing and existing.submitted)
        if final:
            missing = self._missing_required(access.call, clean)
            if missing:
                raise InvalidReview("Answer the required questions: " + ", ".join(missing) + ".")
        return self._store(actor, access, existing, clean, expected_version, final)

    # -- annotations ------------------------------------------------------

    def add_annotation(
        self, actor: UserId, task_id: TaskId, selector: Mapping[str, str], body: str
    ) -> Annotation:
        access = self._access(actor, task_id, write=True)
        call = access.call
        artifact_type = self._artifacts.get(call.artifact_type)
        if not artifact_type.annotation_kind:
            raise InvalidReview("Comments cannot be pinned to this kind of work yet.")
        revision = self._calls.get_revision(access.task.submission_id, access.task.revision_number)
        if revision is None:
            raise NotFound
        try:
            normalised = artifact_type.check_selector(revision.artifact, selector)
        except ArtifactError as e:
            raise InvalidReview(str(e)) from None
        text = clean_comment(body)
        review = self._repo.review_of_task(task_id)
        if review is None:  # the first thing written is a pinned comment: start the review
            review = self._store(actor, access, None, {}, 0, False)
        annotation = Annotation(
            AnnotationId(self._new_id()),
            review.org_id,
            review.space_id,
            review.id,
            access.task.revision_number,
            artifact_type.annotation_kind,
            normalised,
            text,
            actor,
            self._now(),
        )
        self._repo.add_annotation(annotation)
        return annotation

    def delete_annotation(
        self, actor: UserId, task_id: TaskId, annotation_id: AnnotationId
    ) -> None:
        self._access(actor, task_id, write=True)
        review = self._repo.review_of_task(task_id)
        annotation = self._repo.get_annotation(annotation_id)
        if review is None or annotation is None or annotation.review_id != review.id:
            raise NotFound
        self._repo.delete_annotation(annotation_id)

    # -- helpers ----------------------------------------------------------

    def _access(self, actor: UserId, task_id: TaskId, *, write: bool = False) -> Access:
        task = self._rounds.get_task(task_id)
        round_ = self._rounds.get_round(task.round_id) if task else None
        call = self._calls.get_call(round_.call_id) if round_ else None
        if task is None or round_ is None or call is None:
            raise NotFound
        view = self._tenancy.space_view(actor, call.space_id)  # NotFound for outsiders
        manager = Permission.ROUNDS_MANAGE in view.permissions
        mine = self._is_reviewer(actor, task.reviewer)
        if not mine and not manager:
            raise NotFound  # other people's tasks do not exist for you
        status = round_.status(self._now())
        if mine and not manager and (not call.published or status is RoundStatus.SCHEDULED):
            raise NotFound
        can_edit = mine and status is not RoundStatus.CLOSED
        if write:
            if not mine:
                raise Forbidden  # staff can read a review, only the reviewer writes it
            if status is RoundStatus.CLOSED:
                raise ReviewClosed
        return Access(task, round_, call, mine, can_edit)

    def _is_reviewer(self, actor: UserId, party: Party) -> bool:
        if isinstance(party, UserParty):
            return party.user_id == actor
        group = self._tenancy_repo.get_group(GroupId(party.group_id))
        return group is not None and actor in group.members

    def _check(
        self, call: Call, answers: Mapping[str, str]
    ) -> tuple[dict[str, str], dict[str, str]]:
        clean: dict[str, str] = {}
        problems: dict[str, str] = {}
        if call.rubric_id is None:
            return clean, problems
        for c in self._rubrics.criteria_of(call.rubric_id):
            kind = self._criteria.get(c.type_key)
            try:
                value = kind.check_answer(c.config, answers.get(c.id, ""))
            except CriterionError as e:
                problems[c.id] = str(e)
                continue
            if value:
                clean[c.id] = value
        return clean, problems

    def _missing_required(self, call: Call, clean: Mapping[str, str]) -> list[str]:
        if call.rubric_id is None:
            return []
        return [
            c.title
            for c in self._rubrics.criteria_of(call.rubric_id)
            if c.required and c.id not in clean
        ]

    def _store(
        self,
        actor: UserId,
        access: Access,
        existing: Review | None,
        answers: dict[str, str],
        expected_version: int,
        submitted: bool,
    ) -> Review:
        now = self._now()
        task = access.task
        if existing is None:
            if expected_version != 0:
                raise ReviewConflict
            review = Review(
                ReviewId(self._new_id()), task.org_id, task.space_id, task.round_id, task.id,
                answers, 1, submitted, actor, now,
            )  # fmt: skip
            try:
                self._repo.add_review(review, ReviewEdit(review.id, 1, actor, now))
            except DuplicateReview:
                raise ReviewConflict from None  # a group mate saved first
            return review
        if existing.version != expected_version and existing.updated_by != actor:
            # Someone else saved after you loaded the page. Your own earlier saves (for example
            # an autosave that finished while you pressed Submit) are not a conflict.
            raise ReviewConflict
        expected_version = existing.version
        review = replace(
            existing,
            answers=answers,
            version=existing.version + 1,
            submitted=submitted,
            updated_by=actor,
            updated_at=now,
        )
        edit = ReviewEdit(review.id, review.version, actor, now)
        if not self._repo.update_review(review, expected_version, edit):
            raise ReviewConflict
        return review

    def _party_label(self, party: Party) -> str:
        if isinstance(party, UserParty):
            user = self._users.get(UserId(party.user_id))
            return user.display_name if user else "Unknown"
        group = self._tenancy_repo.get_group(GroupId(party.group_id))
        return group.name if group else "Unknown group"

    def _names(self, ids: list[UserId]) -> dict[UserId, str]:
        return {uid: u.display_name for uid, u in self._users.get_many(list(set(ids))).items()}

    def _annotation_views(
        self, actor: UserId, review: Review, access: Access
    ) -> list[AnnotationView]:
        found = self._repo.annotations_of(review.id)
        names = self._names([a.created_by for a in found])
        return [
            AnnotationView(a, names.get(a.created_by, "Unknown"), access.can_edit) for a in found
        ]

    def _trail(self, review: Review) -> list[EditView]:
        edits = self._repo.edits_of(review.id)
        names = self._names([e.user_id for e in edits])
        return [EditView(e.version, names.get(e.user_id, "Unknown"), e.at) for e in edits]


class AnswerErrors(Exception):
    """Some answers are not acceptable: criterion id -> message."""

    def __init__(self, problems: dict[str, str]) -> None:
        super().__init__("some answers are not acceptable")
        self.problems = problems
