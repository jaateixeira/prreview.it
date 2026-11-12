"""Review rounds: configuring them, allocating reviewers and listing who reviews what."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime

from previewit.application.allocation import AllocationStrategy, StrategyRegistry
from previewit.application.ports import (
    CallRepository,
    DuplicateRound,
    DuplicateTask,
    RoundRepository,
    TenancyRepository,
    UserRepository,
)
from previewit.application.tenancy import Forbidden, NotFound, TenancyService
from previewit.domain.allocation import Problem, Slot, conflicts
from previewit.domain.calls import Call, CallId, Submission, SubmissionId
from previewit.domain.identity import UserId
from previewit.domain.party import GroupParty, Party, UserParty
from previewit.domain.rounds import (
    ANONYMITY_PRESETS,
    DEFAULT_ANONYMITY,
    InvalidRound,
    ReviewRound,
    ReviewTask,
    RoundId,
    RoundStatus,
    TaskId,
    anonymity_policy,
    clean_per_submission,
    validate_window,
)
from previewit.domain.tenancy import GroupId, Permission, SpaceId


@dataclass(frozen=True)
class TaskView:
    task: ReviewTask
    reviewer_label: str
    author_label: str  # organizers see everyone; M6 adds masking for the other viewers
    submission_title: str


@dataclass(frozen=True)
class Gap:
    """A submission that has fewer reviewers than the round asks for."""

    submission_title: str
    have: int


@dataclass(frozen=True)
class RoundView:
    round: ReviewRound
    status: RoundStatus
    strategy_label: str
    anonymity_label: str
    automatic: bool
    tasks: list[TaskView]
    gaps: list[Gap]
    submissions: int


@dataclass(frozen=True)
class AllocationReport:
    created: int
    gaps: list[Gap]


@dataclass(frozen=True)
class MyTask:
    task: ReviewTask
    call_id: CallId
    call_title: str
    submission_title: str
    round_number: int
    status: RoundStatus
    closes_at: datetime | None


@dataclass(frozen=True)
class ReviewerOption:
    party: Party
    label: str


def party_key(party: Party) -> str:
    return f"user:{party.user_id}" if isinstance(party, UserParty) else f"group:{party.group_id}"


class RoundsService:
    def __init__(
        self,
        repo: RoundRepository,
        calls_repo: CallRepository,
        tenancy: TenancyService,
        tenancy_repo: TenancyRepository,
        users: UserRepository,
        registry: StrategyRegistry,
        new_id: Callable[[], str],
        clock: Callable[[], datetime],
    ) -> None:
        self._repo = repo
        self._calls = calls_repo
        self._tenancy = tenancy
        self._tenancy_repo = tenancy_repo
        self._users = users
        self._registry = registry
        self._new_id = new_id
        self._now = clock

    # -- catalogue --------------------------------------------------------

    def strategies(self) -> list[AllocationStrategy]:
        return self._registry.all()

    @staticmethod
    def anonymity_options() -> list[tuple[str, str]]:
        return [(key, label) for key, (label, _) in ANONYMITY_PRESETS.items()]

    # -- rounds -----------------------------------------------------------

    def create_round(
        self,
        actor: UserId,
        call_id: CallId,
        *,
        per_submission: int,
        strategy_key: str,
        anonymity_key: str = DEFAULT_ANONYMITY,
        opens_at: datetime | None = None,
        closes_at: datetime | None = None,
    ) -> ReviewRound:
        call = self._managed_call(actor, call_id)
        self._registry.get(strategy_key)  # UnknownStrategy for a bad key
        anonymity_policy(anonymity_key)
        validate_window(opens_at, closes_at)
        per = clean_per_submission(per_submission)
        for _attempt in range(2):  # two organizers creating at once: take the next number
            number = max((r.number for r in self._repo.rounds_of_call(call.id)), default=0) + 1
            round_ = ReviewRound(
                RoundId(self._new_id()),
                call.org_id,
                call.space_id,
                call.id,
                number,
                per,
                strategy_key,
                anonymity_key,
                opens_at,
                closes_at,
            )
            try:
                self._repo.add_round(round_)
                return round_
            except DuplicateRound:
                continue
        raise InvalidRound("Another round was created at the same moment. Try again.")

    def update_round(
        self,
        actor: UserId,
        round_id: RoundId,
        *,
        per_submission: int,
        strategy_key: str,
        anonymity_key: str,
        opens_at: datetime | None,
        closes_at: datetime | None,
    ) -> ReviewRound:
        round_, _ = self._managed_round(actor, round_id)
        self._registry.get(strategy_key)
        anonymity_policy(anonymity_key)
        validate_window(opens_at, closes_at)
        updated = replace(
            round_,
            per_submission=clean_per_submission(per_submission),
            strategy_key=strategy_key,
            anonymity_key=anonymity_key,
            opens_at=opens_at,
            closes_at=closes_at,
        )
        self._repo.update_round(updated)
        return updated

    def delete_round(self, actor: UserId, round_id: RoundId) -> None:
        self._managed_round(actor, round_id)
        self._repo.delete_round(round_id)

    def rounds(self, actor: UserId, call_id: CallId) -> list[RoundView]:
        call = self._managed_call(actor, call_id)
        return [self._view(r, call) for r in self._repo.rounds_of_call(call.id)]

    def round_view(self, actor: UserId, round_id: RoundId) -> RoundView:
        round_, call = self._managed_round(actor, round_id)
        return self._view(round_, call)

    # -- allocation -------------------------------------------------------

    def allocate(
        self, actor: UserId, round_id: RoundId, seed: int | None = None
    ) -> AllocationReport:
        """Replace every task of the round with a fresh allocation by its strategy.

        Authors are the reviewers (a Party is both), so in a group assignment groups review
        groups and in an individual one people review people."""
        round_, call = self._managed_round(actor, round_id)
        strategy = self._registry.get(round_.strategy_key)
        if not strategy.automatic:
            raise InvalidRound("This round pairs reviewers by hand. Add tasks one by one.")
        if round_.status(self._now()) is RoundStatus.CLOSED:
            raise InvalidRound("This round has closed.")
        submissions = self._repo_submissions(call)
        if not submissions:
            raise InvalidRound("There are no submissions to allocate yet.")
        groups = self._groups(call.space_id)
        authors = {party_key(s.author): self._slot(s.author, groups) for s in submissions}
        problem = Problem(
            reviewers=list(authors.values()),
            submissions=[Slot(s.id, self._slot(s.author, groups).people) for s in submissions],
            per_submission=round_.per_submission,
        )
        chosen = strategy.allocate(problem, self._seed() if seed is None else seed)
        by_id = {s.id: s for s in submissions}
        reviewer_party = {party_key(s.author): s.author for s in submissions}
        tasks = [
            ReviewTask(
                TaskId(self._new_id()),
                round_.org_id,
                round_.space_id,
                round_.id,
                reviewer_party[reviewer_key],
                SubmissionId(sub_id),
                self._latest_revision(SubmissionId(sub_id)),
                False,
            )
            for reviewer_key, sub_id in chosen.pairs
        ]
        self._repo.replace_tasks(round_.id, tasks)
        gaps = [
            Gap(by_id[SubmissionId(k)].title, round_.per_submission - m)
            for k, m in chosen.shortfall.items()
        ]
        return AllocationReport(len(tasks), gaps)

    def reviewer_options(self, actor: UserId, round_id: RoundId) -> list[ReviewerOption]:
        """Everyone who could be added by hand: the space's people and groups."""
        _, call = self._managed_round(actor, round_id)
        members = self._tenancy.members(actor, call.space_id)
        options = [ReviewerOption(UserParty(m.user_id), m.display_name) for m in members]
        options += [
            ReviewerOption(GroupParty(g.id), f"{g.name} (group)")
            for g in self._tenancy_repo.groups_in_space(call.space_id)
        ]
        return options

    def add_task(
        self, actor: UserId, round_id: RoundId, submission_id: SubmissionId, reviewer: Party
    ) -> ReviewTask:
        round_, call = self._managed_round(actor, round_id)
        submission = self._calls.get_submission(submission_id)
        if submission is None or submission.call_id != call.id:
            raise NotFound
        groups = self._groups(call.space_id)
        if isinstance(reviewer, UserParty):
            if self._tenancy_repo.space_member(call.space_id, UserId(reviewer.user_id)) is None:
                raise NotFound
        elif GroupId(reviewer.group_id) not in groups:
            raise NotFound
        if conflicts(self._slot(reviewer, groups), self._slot(submission.author, groups)):
            raise InvalidRound("Reviewers cannot review their own work or their own group's.")
        task = ReviewTask(
            TaskId(self._new_id()),
            round_.org_id,
            round_.space_id,
            round_.id,
            reviewer,
            submission.id,
            self._latest_revision(submission.id),
            True,
        )
        try:
            self._repo.add_tasks([task])
        except DuplicateTask:
            raise InvalidRound("That reviewer already has this submission.") from None
        return task

    def remove_task(self, actor: UserId, task_id: TaskId) -> None:
        task = self._repo.get_task(task_id)
        if task is None:
            raise NotFound
        self._managed_round(actor, task.round_id)
        self._repo.delete_task(task_id)

    # -- the reviewer's side ----------------------------------------------

    def my_tasks(self, actor: UserId, space_id: SpaceId) -> list[MyTask]:
        """Tasks that are mine or my groups', in rounds that have opened. Authors are not
        named here: who may see them is the anonymity policy's business (M6)."""
        self._tenancy.space_view(actor, space_id)  # NotFound for outsiders
        parties: list[Party] = [UserParty(actor)]
        parties += [
            GroupParty(g.id)
            for g in self._tenancy_repo.groups_in_space(space_id)
            if actor in g.members
        ]
        now = self._now()
        result: list[MyTask] = []
        for task in self._repo.tasks_for_parties(space_id, parties):
            round_ = self._repo.get_round(task.round_id)
            call = self._calls.get_call(round_.call_id) if round_ else None
            submission = self._calls.get_submission(task.submission_id)
            if round_ is None or call is None or submission is None or not call.published:
                continue
            status = round_.status(now)
            if status is RoundStatus.SCHEDULED:
                continue
            result.append(
                MyTask(
                    task,
                    call.id,
                    call.title,
                    submission.title,
                    round_.number,
                    status,
                    round_.closes_at,
                )
            )
        far = datetime.max.replace(tzinfo=now.tzinfo)
        return sorted(result, key=lambda t: (t.closes_at or far, t.call_title, t.round_number))

    # -- helpers ----------------------------------------------------------

    def _managed_call(self, actor: UserId, call_id: CallId) -> Call:
        call = self._calls.get_call(call_id)
        if call is None:
            raise NotFound
        view = self._tenancy.space_view(actor, call.space_id)
        if Permission.ROUNDS_MANAGE not in view.permissions:
            raise Forbidden
        return call

    def _managed_round(self, actor: UserId, round_id: RoundId) -> tuple[ReviewRound, Call]:
        round_ = self._repo.get_round(round_id)
        if round_ is None:
            raise NotFound
        return round_, self._managed_call(actor, round_.call_id)

    def _repo_submissions(self, call: Call) -> list[Submission]:
        return self._calls.submissions_in_call(call.id)

    def _latest_revision(self, submission_id: SubmissionId) -> int:
        return max((r.number for r in self._calls.revision_infos(submission_id)), default=1)

    def _groups(self, space_id: SpaceId) -> dict[GroupId, frozenset[UserId]]:
        return {g.id: g.members for g in self._tenancy_repo.groups_in_space(space_id)}

    @staticmethod
    def _slot(party: Party, groups: dict[GroupId, frozenset[UserId]]) -> Slot:
        if isinstance(party, UserParty):
            return Slot(party_key(party), frozenset({party.user_id}))
        members = groups.get(GroupId(party.group_id), frozenset())
        return Slot(party_key(party), frozenset(str(m) for m in members))

    def _seed(self) -> int:
        return int.from_bytes(hashlib.sha256(self._new_id().encode()).digest()[:4], "big")

    def _label(self, party: Party, users: dict[UserId, str], groups: dict[GroupId, str]) -> str:
        if isinstance(party, UserParty):
            return users.get(UserId(party.user_id), "Unknown")
        return groups.get(GroupId(party.group_id), "Unknown group")

    def _view(self, round_: ReviewRound, call: Call) -> RoundView:
        strategy = self._registry.get(round_.strategy_key)
        submissions = {s.id: s for s in self._repo_submissions(call)}
        tasks = self._repo.tasks_of_round(round_.id)
        people = self._users.get_many(
            [
                UserId(p.user_id)
                for p in [t.reviewer for t in tasks] + [s.author for s in submissions.values()]
                if isinstance(p, UserParty)
            ]
        )
        names = {uid: u.display_name for uid, u in people.items()}
        group_names = {g.id: g.name for g in self._tenancy_repo.groups_in_space(call.space_id)}
        views = [
            TaskView(
                t,
                self._label(t.reviewer, names, group_names),
                self._label(submissions[t.submission_id].author, names, group_names),
                submissions[t.submission_id].title,
            )
            for t in tasks
            if t.submission_id in submissions
        ]
        views.sort(key=lambda v: (v.submission_title.lower(), v.reviewer_label.lower()))
        count: dict[SubmissionId, int] = {}
        for t in tasks:
            count[t.submission_id] = count.get(t.submission_id, 0) + 1
        gaps = [
            Gap(s.title, count.get(s.id, 0))
            for s in submissions.values()
            if count.get(s.id, 0) < round_.per_submission
        ]
        return RoundView(
            round_,
            round_.status(self._now()),
            strategy.label,
            ANONYMITY_PRESETS[round_.anonymity_key][0],
            strategy.automatic,
            views,
            gaps,
            len(submissions),
        )
