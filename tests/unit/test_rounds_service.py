from datetime import timedelta
from itertools import count

import pytest

from previewit.adapters.persistence.memory_reviews import InMemoryReviewRepository
from previewit.adapters.persistence.memory_rounds import InMemoryRoundRepository
from previewit.application.allocation import StrategyRegistry, UnknownStrategy
from previewit.application.artifacts import Upload
from previewit.application.rounds import RoundsService
from previewit.application.tenancy import Forbidden, NotFound
from previewit.domain.party import GroupParty, UserParty
from previewit.domain.rounds import InvalidRound, RoundStatus
from previewit.plugins.allocation import ManualStrategy, RandomStrategy, RoundRobinStrategy
from tests.unit.test_calls_service import PAT, SAM, SUE, TINA, CWorld
from tests.unit.test_tenancy_service import ALICE, AVA, BOB, ZED


class RoundsWorld(CWorld):
    """The calls world plus a rounds service."""

    def __init__(self, *args, rounds_repo=None, reviews_repo=None, **kw):
        super().__init__(*args, **kw)
        ids = count(1)
        self.review_repo = reviews_repo or InMemoryReviewRepository()
        self.rr = RoundsService(
            rounds_repo or InMemoryRoundRepository(),
            self.review_repo,
            self.c._repo,
            self.t,
            self.t._repo,
            self.users,
            StrategyRegistry([RandomStrategy(), RoundRobinStrategy(), ManualStrategy()]),
            lambda: f"q{next(ids)}",
            self.clock,
        )

    def work(self, *users):
        """Each of these students submits an essay; returns {user: submission}."""
        return {u: self.essay(u, title=f"{u} essay") for u in users}

    def round(self, **kw):
        kw.setdefault("per_submission", 1)
        kw.setdefault("strategy_key", "round_robin")
        return self.rr.create_round(TINA, self.call.id, **kw)

    def pairs(self, round_id):
        view = self.rr.round_view(TINA, round_id)
        return {(t.reviewer_label, t.submission_title) for t in view.tasks}


@pytest.fixture
def w() -> RoundsWorld:
    return RoundsWorld()


# --- who may manage rounds ---------------------------------------------------------------------


def test_only_teachers_and_owners_manage_rounds(w: RoundsWorld):
    for user in (SAM, AVA):  # student, assistant
        with pytest.raises(Forbidden):
            w.rr.create_round(user, w.call.id, per_submission=1, strategy_key="random")
        with pytest.raises(Forbidden):
            w.rr.rounds(user, w.call.id)
    with pytest.raises(NotFound):
        w.rr.create_round(BOB, w.call.id, per_submission=1, strategy_key="random")
    with pytest.raises(NotFound):
        w.rr.rounds(ZED, w.call.id)
    assert w.rr.create_round(ALICE, w.call.id, per_submission=1, strategy_key="random").number == 1


def test_a_student_cannot_touch_a_round_by_id(w: RoundsWorld):
    r = w.round()
    with pytest.raises(Forbidden):
        w.rr.allocate(SAM, r.id)
    with pytest.raises(Forbidden):
        w.rr.delete_round(SAM, r.id)
    with pytest.raises(NotFound):
        w.rr.round_view(BOB, r.id)


# --- configuring rounds ------------------------------------------------------------------------


def test_rounds_are_numbered_and_validated(w: RoundsWorld):
    assert [w.round().number for _ in range(3)] == [1, 2, 3]
    with pytest.raises(InvalidRound):
        w.round(per_submission=0)
    with pytest.raises(InvalidRound):
        w.round(per_submission=999)
    with pytest.raises(UnknownStrategy):
        w.round(strategy_key="astrology")
    with pytest.raises(InvalidRound):
        w.round(anonymity_key="nonsense")
    with pytest.raises(InvalidRound):
        w.round(opens_at=w.clock() + timedelta(days=2), closes_at=w.clock() + timedelta(days=1))
    assert [r.round.number for r in w.rr.rounds(TINA, w.call.id)] == [1, 2, 3]


def test_a_round_can_be_edited_and_deleted(w: RoundsWorld):
    r = w.round()
    r2 = w.rr.update_round(
        TINA,
        r.id,
        per_submission=3,
        strategy_key="random",
        anonymity_key="double_anonymous",
        opens_at=None,
        closes_at=None,
    )
    assert (r2.per_submission, r2.strategy_key, r2.anonymity_key) == (
        3,
        "random",
        "double_anonymous",
    )
    w.rr.delete_round(TINA, r.id)
    assert w.rr.rounds(TINA, w.call.id) == []


def test_the_status_follows_the_clock(w: RoundsWorld):
    now = w.clock()
    r = w.round(opens_at=now + timedelta(hours=1), closes_at=now + timedelta(hours=2))
    assert r.status(now) is RoundStatus.SCHEDULED
    assert r.status(now + timedelta(minutes=90)) is RoundStatus.OPEN
    assert r.status(now + timedelta(hours=3)) is RoundStatus.CLOSED


# --- allocation --------------------------------------------------------------------------------


def test_allocation_pairs_authors_with_each_other_never_with_themselves(w: RoundsWorld):
    w.work(SAM, SUE, PAT)
    r = w.round(per_submission=1)
    report = w.rr.allocate(TINA, r.id, seed=1)
    assert report.created == 3 and not report.gaps
    pairs = w.pairs(r.id)
    assert len(pairs) == 3
    for reviewer, title in pairs:
        assert title != f"{reviewer.lower()} essay"


def test_everybody_reviews_and_is_reviewed_k_times(w: RoundsWorld):
    w.work(SAM, SUE, PAT, ALICE)
    r = w.round(per_submission=2, strategy_key="random")
    w.rr.allocate(TINA, r.id, seed=7)
    view = w.rr.round_view(TINA, r.id)
    assert len(view.tasks) == 8 and not view.gaps
    done, got = {}, {}
    for t in view.tasks:
        done[t.reviewer_label] = done.get(t.reviewer_label, 0) + 1
        got[t.submission_title] = got.get(t.submission_title, 0) + 1
    assert set(done.values()) == {2} and set(got.values()) == {2}


def test_the_tasks_point_at_the_latest_revision(w: RoundsWorld):
    subs = w.work(SAM, SUE)
    w.c.revise(SAM, subs[SAM].id, Upload(text="Second draft"))
    r = w.round()
    w.rr.allocate(TINA, r.id, seed=0)
    revisions = {
        t.submission_title: t.task.revision_number for t in w.rr.round_view(TINA, r.id).tasks
    }
    assert revisions == {"sam essay": 2, "sue essay": 1}


def test_a_gap_is_reported_when_there_are_too_few_reviewers(w: RoundsWorld):
    w.work(SAM, SUE)
    r = w.round(per_submission=3)
    report = w.rr.allocate(TINA, r.id, seed=0)
    assert report.created == 2
    assert sorted((g.submission_title, g.have) for g in report.gaps) == [
        ("sam essay", 1),
        ("sue essay", 1),
    ]
    assert len(w.rr.round_view(TINA, r.id).gaps) == 2


def test_allocating_again_replaces_the_tasks(w: RoundsWorld):
    w.work(SAM, SUE, PAT)
    r = w.round()
    w.rr.allocate(TINA, r.id, seed=1)
    w.rr.allocate(TINA, r.id, seed=2)
    assert len(w.rr.round_view(TINA, r.id).tasks) == 3


def test_allocation_needs_submissions_and_an_automatic_strategy_and_an_unclosed_round(
    w: RoundsWorld,
):
    r = w.round()
    with pytest.raises(InvalidRound):
        w.rr.allocate(TINA, r.id)  # nothing submitted
    w.work(SAM, SUE)
    manual = w.round(strategy_key="manual")
    with pytest.raises(InvalidRound):
        w.rr.allocate(TINA, manual.id)
    closed = w.round(closes_at=w.clock() + timedelta(hours=1))
    w.clock.now += timedelta(hours=2)
    with pytest.raises(InvalidRound):
        w.rr.allocate(TINA, closed.id)


def test_group_work_never_pairs_a_group_with_itself(w: RoundsWorld):
    call, group1 = w.group_call()
    group2 = w.t.create_group(TINA, w.s.id, "Group 2")
    for member in (PAT, ALICE):
        w.t.add_to_group(TINA, w.s.id, group2.id, member)
    w.c.submit(SAM, call.id, title="One", upload=Upload(text="a"), group_id=group1.id)
    w.c.submit(PAT, call.id, title="Two", upload=Upload(text="b"), group_id=group2.id)
    r = w.rr.create_round(TINA, call.id, per_submission=1, strategy_key="random")
    w.rr.allocate(TINA, r.id, seed=3)
    assert {(t.reviewer_label, t.submission_title) for t in w.rr.round_view(TINA, r.id).tasks} == {
        ("Group 1", "Two"),
        ("Group 2", "One"),
    }


# --- manual pairing ----------------------------------------------------------------------------


def test_a_teacher_pairs_people_by_hand_with_the_same_safeguards(w: RoundsWorld):
    subs = w.work(SAM, SUE)
    r = w.round(strategy_key="manual")
    w.rr.add_task(TINA, r.id, subs[SAM].id, UserParty(SUE))
    w.rr.add_task(TINA, r.id, subs[SAM].id, UserParty(TINA))  # a teacher may review too
    assert len(w.rr.round_view(TINA, r.id).tasks) == 2
    with pytest.raises(InvalidRound):
        w.rr.add_task(TINA, r.id, subs[SAM].id, UserParty(SAM))  # own work
    with pytest.raises(InvalidRound):
        w.rr.add_task(TINA, r.id, subs[SAM].id, UserParty(SUE))  # twice
    with pytest.raises(NotFound):
        w.rr.add_task(TINA, r.id, subs[SAM].id, UserParty(BOB))  # not in the space
    with pytest.raises(NotFound):
        w.rr.add_task(TINA, r.id, subs[SAM].id, GroupParty("no-such-group"))
    task = w.rr.round_view(TINA, r.id).tasks[0].task
    w.rr.remove_task(TINA, task.id)
    assert len(w.rr.round_view(TINA, r.id).tasks) == 1


def test_a_group_member_cannot_be_paired_with_their_groups_work(w: RoundsWorld):
    call, group = w.group_call()
    sub = w.c.submit(SAM, call.id, title="One", upload=Upload(text="a"), group_id=group.id)
    r = w.rr.create_round(TINA, call.id, per_submission=1, strategy_key="manual")
    with pytest.raises(InvalidRound):
        w.rr.add_task(TINA, r.id, sub.id, UserParty(SUE))  # Sue is in Group 1
    w.rr.add_task(TINA, r.id, sub.id, UserParty(PAT))


def test_a_task_of_another_call_is_not_found(w: RoundsWorld):
    other = w.c.create_call(TINA, w.s.id, title="Other", artifact_type="text", published=True)
    foreign = w.c.submit(SAM, other.id, title="x", upload=Upload(text="a"))
    r = w.round(strategy_key="manual")
    with pytest.raises(NotFound):
        w.rr.add_task(TINA, r.id, foreign.id, UserParty(SUE))


def test_students_cannot_remove_tasks(w: RoundsWorld):
    subs = w.work(SAM, SUE)
    r = w.round(strategy_key="manual")
    task = w.rr.add_task(TINA, r.id, subs[SAM].id, UserParty(SUE))
    with pytest.raises(Forbidden):
        w.rr.remove_task(SUE, task.id)
    with pytest.raises(NotFound):
        w.rr.remove_task(BOB, task.id)


# --- what reviewers see ------------------------------------------------------------------------


def test_my_tasks_lists_my_work_and_my_groups_work_once_the_round_is_open(w: RoundsWorld):
    w.work(SAM, SUE, PAT)
    r = w.round(opens_at=w.clock() + timedelta(hours=1))
    w.rr.allocate(TINA, r.id, seed=1)
    assert w.rr.my_tasks(SAM, w.s.id) == []  # scheduled: not yet visible
    w.clock.now += timedelta(hours=2)
    mine = w.rr.my_tasks(SAM, w.s.id)
    assert len(mine) == 1 and mine[0].round_number == 1 and mine[0].call_title == "Essay 1"
    assert mine[0].submission_title != "sam essay"
    assert w.rr.my_tasks(AVA, w.s.id) == []  # staff who review nothing
    with pytest.raises(NotFound):
        w.rr.my_tasks(BOB, w.s.id)


def test_a_groups_tasks_show_for_each_member(w: RoundsWorld):
    call, group = w.group_call()
    group2 = w.t.create_group(TINA, w.s.id, "Group 2")
    w.t.add_to_group(TINA, w.s.id, group2.id, PAT)
    w.c.submit(SAM, call.id, title="One", upload=Upload(text="a"), group_id=group.id)
    w.c.submit(PAT, call.id, title="Two", upload=Upload(text="b"), group_id=group2.id)
    r = w.rr.create_round(TINA, call.id, per_submission=1, strategy_key="random")
    w.rr.allocate(TINA, r.id, seed=3)
    assert [t.submission_title for t in w.rr.my_tasks(SAM, w.s.id)] == ["Two"]
    assert [t.submission_title for t in w.rr.my_tasks(SUE, w.s.id)] == ["Two"]
    assert [t.submission_title for t in w.rr.my_tasks(PAT, w.s.id)] == ["One"]


def test_drafts_hide_their_tasks_from_reviewers(w: RoundsWorld):
    w.work(SAM, SUE)
    r = w.round()
    w.rr.allocate(TINA, r.id, seed=0)
    assert w.rr.my_tasks(SAM, w.s.id)
    w.c.update_call(
        TINA, w.call.id, title="Essay 1", description="", closes_at=None, published=False
    )
    assert w.rr.my_tasks(SAM, w.s.id) == []
