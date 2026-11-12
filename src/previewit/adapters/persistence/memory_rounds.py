"""In-memory round repository: a fast fake that follows the same contract as the SQL one."""

from __future__ import annotations

from collections.abc import Sequence

from previewit.application.ports import DuplicateRound, DuplicateTask
from previewit.domain.calls import CallId
from previewit.domain.party import Party
from previewit.domain.rounds import ReviewRound, ReviewTask, RoundId, TaskId
from previewit.domain.tenancy import SpaceId


class InMemoryRoundRepository:
    def __init__(self) -> None:
        self._rounds: dict[RoundId, ReviewRound] = {}
        self._tasks: dict[TaskId, ReviewTask] = {}

    def add_round(self, round_: ReviewRound) -> None:
        if any(
            r.call_id == round_.call_id and r.number == round_.number for r in self._rounds.values()
        ):
            raise DuplicateRound
        self._rounds[round_.id] = round_

    def get_round(self, round_id: RoundId) -> ReviewRound | None:
        return self._rounds.get(round_id)

    def update_round(self, round_: ReviewRound) -> None:
        if round_.id in self._rounds:
            self._rounds[round_.id] = round_

    def delete_round(self, round_id: RoundId) -> None:
        self._rounds.pop(round_id, None)
        for tid in [t.id for t in self._tasks.values() if t.round_id == round_id]:
            del self._tasks[tid]

    def rounds_of_call(self, call_id: CallId) -> list[ReviewRound]:
        return sorted((r for r in self._rounds.values() if r.call_id == call_id), key=_number)

    def add_tasks(self, tasks: Sequence[ReviewTask]) -> None:
        for task in tasks:
            if any(
                t.round_id == task.round_id
                and t.reviewer == task.reviewer
                and t.submission_id == task.submission_id
                for t in self._tasks.values()
            ):
                raise DuplicateTask
            self._tasks[task.id] = task

    def replace_tasks(self, round_id: RoundId, tasks: Sequence[ReviewTask]) -> None:
        for tid in [t.id for t in self._tasks.values() if t.round_id == round_id]:
            del self._tasks[tid]
        self.add_tasks(tasks)

    def get_task(self, task_id: TaskId) -> ReviewTask | None:
        return self._tasks.get(task_id)

    def delete_task(self, task_id: TaskId) -> None:
        self._tasks.pop(task_id, None)

    def tasks_of_round(self, round_id: RoundId) -> list[ReviewTask]:
        return [t for t in self._tasks.values() if t.round_id == round_id]

    def tasks_for_parties(self, space_id: SpaceId, parties: Sequence[Party]) -> list[ReviewTask]:
        wanted = set(parties)
        return [t for t in self._tasks.values() if t.space_id == space_id and t.reviewer in wanted]


def _number(round_: ReviewRound) -> int:
    return round_.number
