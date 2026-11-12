from datetime import timedelta
from itertools import count

import pytest

from previewit.adapters.persistence.memory_rubrics import InMemoryRubricRepository
from previewit.application.artifacts import ArtifactRegistry, Upload
from previewit.application.criteria import CriterionRegistry
from previewit.application.reviews import AnswerErrors, ReviewsService
from previewit.application.rubrics import RubricsService
from previewit.application.tenancy import Forbidden, NotFound
from previewit.domain.party import GroupParty, UserParty
from previewit.domain.reviews import InvalidReview, ReviewClosed, ReviewConflict
from previewit.plugins.criteria import (
    LevelsCriterion,
    NumericCriterion,
    TextCriterion,
    YesNoCriterion,
)
from previewit.plugins.pdf import PdfArtifact
from previewit.plugins.text import TextArtifact
from tests.unit.test_calls_service import PAT, SAM, SUE, TINA
from tests.unit.test_rounds_service import RoundsWorld
from tests.unit.test_tenancy_service import ALICE, AVA, BOB, ZED


class ReviewWorld(RoundsWorld):
    """The rounds world plus a rubric on the call and a reviews service."""

    def __init__(self, *args, rubrics_repo=None, **kw):
        super().__init__(*args, **kw)
        ids = count(1)
        criteria = CriterionRegistry(
            [NumericCriterion(), LevelsCriterion(), YesNoCriterion(), TextCriterion()]
        )
        rubric_repo = rubrics_repo or InMemoryRubricRepository()
        self.rub = RubricsService(
            rubric_repo, self.c._repo, self.t, criteria, lambda: f"r{next(ids)}"
        )
        rubric = self.rub.create_rubric(TINA, self.s.id, "Essay rubric")
        self.score = self.rub.add_criterion(
            TINA,
            rubric.id,
            type_key="numeric",
            title="Clarity",
            raw_config={"min": "1", "max": "5"},
        )
        self.note = self.rub.add_criterion(
            TINA, rubric.id, type_key="text", title="Comment", raw_config={}, required=False
        )
        self.rub.attach(TINA, self.call.id, rubric.id)
        self.rv = ReviewsService(
            self.review_repo,
            self.rr._repo,
            self.c._repo,
            rubric_repo,
            self.t,
            self.t._repo,
            self.users,
            criteria,
            ArtifactRegistry([TextArtifact(), PdfArtifact()]),
            lambda: f"v{next(ids)}",
            self.clock,
        )
        self.subs = self.work(SAM, SUE, PAT)

    def task_for(self, reviewer, author):
        """A manual task: `reviewer` (a Party) reviews `author`'s essay."""
        if not hasattr(self, "_round"):
            self._round = self.round(strategy_key="manual")
        return self.rr.add_task(TINA, self._round.id, self.subs[author].id, reviewer)

    def answers(self, clarity="4", note="Clear") -> dict[str, str]:
        return {self.score.id: clarity, self.note.id: note}


@pytest.fixture
def w() -> ReviewWorld:
    return ReviewWorld()


# --- the review form ---------------------------------------------------------------------------


def test_a_reviewer_saves_drafts_and_submits(w: ReviewWorld):
    task = w.task_for(UserParty(SUE), SAM)
    ws = w.rv.workspace(SUE, task.id)
    assert (
        ws.version == 0
        and ws.can_edit
        and [q.criterion.title for q in ws.questions]
        == [
            "Clarity",
            "Comment",
        ]
    )
    r1 = w.rv.save(SUE, task.id, w.answers("3", ""), 0)
    assert (r1.version, r1.submitted, r1.answers) == (1, False, {w.score.id: "3"})
    r2 = w.rv.save(SUE, task.id, w.answers("4", "Nice"), 1)
    assert r2.version == 2 and r2.answers[w.note.id] == "Nice"
    r3 = w.rv.save(SUE, task.id, w.answers("4", "Nice"), 2, submit=True)
    saved = w.rv.workspace(SUE, task.id).review
    assert r3.submitted and saved and saved.submitted


def test_a_draft_may_be_incomplete_but_a_submission_may_not(w: ReviewWorld):
    task = w.task_for(UserParty(SUE), SAM)
    w.rv.save(SUE, task.id, {}, 0)  # empty draft is fine
    with pytest.raises(InvalidReview, match="Clarity"):
        w.rv.save(SUE, task.id, {w.note.id: "only a note"}, 1, submit=True)
    w.rv.save(SUE, task.id, w.answers(), 1, submit=True)
    with pytest.raises(InvalidReview):  # once submitted, required stays required
        w.rv.save(SUE, task.id, {w.note.id: "x"}, 2)


def test_bad_answers_are_reported_per_question_and_nothing_is_saved(w: ReviewWorld):
    task = w.task_for(UserParty(SUE), SAM)
    with pytest.raises(AnswerErrors) as e:
        w.rv.save(SUE, task.id, {w.score.id: "9"}, 0)
    assert set(e.value.problems) == {w.score.id}
    assert w.rv.workspace(SUE, task.id).review is None


def test_your_own_earlier_save_is_not_a_conflict(w: ReviewWorld):
    task = w.task_for(UserParty(SUE), SAM)
    w.rv.save(SUE, task.id, w.answers("2"), 0)
    w.rv.save(SUE, task.id, w.answers("3"), 1)  # an autosave finished in between
    r = w.rv.save(SUE, task.id, w.answers("5"), 1)  # the page still had version 1
    assert r.version == 3 and r.answers[w.score.id] == "5"


def test_unsaved_answers_are_shown_again_after_an_error(w: ReviewWorld):
    task = w.task_for(UserParty(SUE), SAM)
    ws = w.rv.workspace(SUE, task.id, draft={w.score.id: "9"}, errors={w.score.id: "No"})
    q = ws.questions[0]
    assert 'value="9"' in q.input_html and q.error == "No"


# --- who may open a review ---------------------------------------------------------------------


def test_only_the_reviewer_and_staff_can_open_a_task(w: ReviewWorld):
    task = w.task_for(UserParty(SUE), SAM)
    assert w.rv.workspace(SUE, task.id).can_edit
    for author_of_work in (SAM, PAT):
        with pytest.raises(NotFound):  # the author and other students: it does not exist
            w.rv.workspace(author_of_work, task.id)
    for outsider in (BOB, ZED):
        with pytest.raises(NotFound):
            w.rv.workspace(outsider, task.id)
    with pytest.raises(NotFound):
        w.rv.workspace(AVA, task.id)  # assistants do not manage rounds


def test_staff_read_a_review_but_cannot_write_it(w: ReviewWorld):
    task = w.task_for(UserParty(SUE), SAM)
    w.rv.save(SUE, task.id, w.answers(), 0)
    for staff in (TINA, ALICE):
        ws = w.rv.workspace(staff, task.id)
        assert not ws.can_edit and ws.review and ws.review.answers[w.score.id] == "4"
        with pytest.raises(Forbidden):
            w.rv.save(staff, task.id, w.answers("1"), 1)
        with pytest.raises(Forbidden):
            w.rv.add_annotation(staff, task.id, {}, "x")


def test_a_teacher_who_is_the_reviewer_can_write(w: ReviewWorld):
    task = w.task_for(UserParty(TINA), SAM)
    assert w.rv.save(TINA, task.id, w.answers(), 0).updated_by == TINA


def test_scheduled_closed_and_draft_rounds(w: ReviewWorld):
    now = w.clock()
    scheduled = w.round(strategy_key="manual", opens_at=now + timedelta(hours=1))
    task = w.rr.add_task(TINA, scheduled.id, w.subs[SAM].id, UserParty(SUE))
    with pytest.raises(NotFound):
        w.rv.workspace(SUE, task.id)
    w.clock.now += timedelta(hours=2)
    w.rv.save(SUE, task.id, w.answers(), 0)
    closed = w.rr.update_round(
        TINA, scheduled.id, per_submission=1, strategy_key="manual",
        anonymity_key="reviewers_hidden", opens_at=None, closes_at=w.clock() + timedelta(hours=1),
    )  # fmt: skip
    w.clock.now += timedelta(hours=2)
    assert closed.id == scheduled.id
    ws = w.rv.workspace(SUE, task.id)
    assert ws.closed and not ws.can_edit  # still readable
    with pytest.raises(ReviewClosed):
        w.rv.save(SUE, task.id, w.answers("1"), 1)
    w.c.update_call(
        TINA, w.call.id, title="Essay 1", description="", closes_at=None, published=False
    )
    with pytest.raises(NotFound):
        w.rv.workspace(SUE, task.id)


def test_the_artifact_is_the_revision_the_task_points_at(w: ReviewWorld):
    w.c.revise(SAM, w.subs[SAM].id, Upload(text="Second draft"))
    task = w.task_for(UserParty(SUE), SAM)
    assert task.revision_number == 2
    ws = w.rv.workspace(SUE, task.id)
    assert "Second draft" in ws.artifact_html and ws.raw_url == f"/tasks/{task.id}/raw"
    w.c.revise(SAM, w.subs[SAM].id, Upload(text="Third draft"))
    assert "Second draft" in w.rv.workspace(SUE, task.id).artifact_html  # pinned
    assert w.rv.raw(SUE, task.id).number == 2


# --- group review ------------------------------------------------------------------------------


@pytest.fixture
def gw(w: ReviewWorld):
    group = w.t.create_group(TINA, w.s.id, "Reviewers", [SUE, PAT])
    task = w.task_for(GroupParty(group.id), SAM)
    return w, task


def test_any_group_member_edits_the_shared_review_and_the_trail_names_them(gw):
    w, task = gw
    w.rv.save(SUE, task.id, w.answers("2"), 0)
    w.rv.save(PAT, task.id, w.answers("5", "Pat's note"), 1)
    ws = w.rv.workspace(SUE, task.id)
    assert ws.shared and ws.reviewer_label == "Reviewers"
    assert ws.review.answers[w.score.id] == "5" and ws.review.updated_by == PAT
    assert [(e.version, e.user_label) for e in ws.trail] == [(1, "Sue"), (2, "Pat")]
    with pytest.raises(NotFound):
        w.rv.workspace(SAM, task.id)  # not in the group


def test_a_stale_version_from_another_member_is_a_conflict_and_changes_nothing(gw):
    w, task = gw
    w.rv.save(SUE, task.id, w.answers("2"), 0)
    w.rv.save(SUE, task.id, w.answers("3"), 1)
    with pytest.raises(ReviewConflict):
        w.rv.save(PAT, task.id, w.answers("5"), 1)  # Pat loaded version 1
    kept = w.rv.workspace(SUE, task.id).review
    assert kept and kept.version == 2 and kept.answers[w.score.id] == "3"
    w.rv.save(PAT, task.id, w.answers("5"), 2)


def test_two_members_starting_at_once_conflict_instead_of_duplicating(gw):
    w, task = gw
    w.rv.save(SUE, task.id, w.answers("2"), 0)
    with pytest.raises(ReviewConflict):
        w.rv.save(PAT, task.id, w.answers("5"), 0)


# --- annotations -------------------------------------------------------------------------------


def selector(text: str, quote: str) -> dict[str, str]:
    start = text.index(quote)
    return {"quote": quote, "start": str(start), "end": str(start + len(quote))}


def test_a_comment_is_pinned_to_the_text_and_starts_the_review(w: ReviewWorld):
    task = w.task_for(UserParty(SUE), SAM)
    a = w.rv.add_annotation(SUE, task.id, selector("Hello", "ell"), "Why this word?")
    assert a.kind == "text" and a.selector["quote"] == "ell" and a.revision_number == 1
    ws = w.rv.workspace(SUE, task.id)
    assert ws.review and ws.review.version == 1 and ws.annotatable
    assert [(v.annotation.body, v.author_label, v.can_delete) for v in ws.annotations] == [
        ("Why this word?", "Sue", True)
    ]
    assert w.rv.workspace(TINA, task.id).annotations[0].can_delete is False


def test_bad_selectors_and_comments_are_refused(w: ReviewWorld):
    task = w.task_for(UserParty(SUE), SAM)
    good = selector("Hello", "ell")
    for bad in (
        {},
        {**good, "quote": "xyz"},  # not what is at that place
        {**good, "start": "4", "end": "2"},
        {**good, "end": "99"},
        {**good, "start": "abc"},
        {"quote": " ", "start": "1", "end": "2"},
    ):
        with pytest.raises(InvalidReview):
            w.rv.add_annotation(SUE, task.id, bad, "Comment")
    for comment in ("", "  ", "x" * 2001):
        with pytest.raises(InvalidReview):
            w.rv.add_annotation(SUE, task.id, good, comment)
    assert w.rv.workspace(SUE, task.id).review is None  # nothing was started


def test_a_group_mate_can_delete_a_comment_but_nobody_else(gw):
    w, task = gw
    a = w.rv.add_annotation(SUE, task.id, selector("Hello", "ell"), "Mine")
    with pytest.raises(NotFound):
        w.rv.delete_annotation(SAM, task.id, a.id)
    w.rv.delete_annotation(PAT, task.id, a.id)
    assert w.rv.workspace(SUE, task.id).annotations == []
    with pytest.raises(NotFound):
        w.rv.delete_annotation(SUE, task.id, a.id)


def test_pdf_work_cannot_be_annotated_yet(w: ReviewWorld):
    pdf_call = w.c.create_call(TINA, w.s.id, title="Paper", artifact_type="pdf", published=True)
    sub = w.c.submit(SAM, pdf_call.id, title="P", upload=Upload(content=b"%PDF-1.7\n%%EOF\n"))
    rnd = w.rr.create_round(TINA, pdf_call.id, per_submission=1, strategy_key="manual")
    task = w.rr.add_task(TINA, rnd.id, sub.id, UserParty(SUE))
    ws = w.rv.workspace(SUE, task.id)
    assert not ws.annotatable and "application/pdf" in ws.artifact_html
    with pytest.raises(InvalidReview):
        w.rv.add_annotation(SUE, task.id, {"quote": "a", "start": "0", "end": "1"}, "x")


def test_a_review_needs_no_rubric_to_carry_comments(w: ReviewWorld):
    w.rub.attach(TINA, w.call.id, None)
    task = w.task_for(UserParty(SUE), SAM)
    assert w.rv.workspace(SUE, task.id).questions == []
    assert w.rv.save(SUE, task.id, {}, 0, submit=True).submitted


# --- the round guards from M4 ------------------------------------------------------------------


def test_a_round_with_reviews_cannot_be_reallocated_or_deleted(w: ReviewWorld):
    task = w.task_for(UserParty(SUE), SAM)
    rnd = w._round
    w.rv.save(SUE, task.id, w.answers(), 0)
    from previewit.domain.rounds import InvalidRound

    with pytest.raises(InvalidRound):
        w.rr.delete_round(TINA, rnd.id)
    with pytest.raises(InvalidRound):
        w.rr.remove_task(TINA, task.id)
    auto = w.round(strategy_key="random")
    w.rr.allocate(TINA, auto.id, seed=1)  # other rounds are unaffected
    other = w.task_for(UserParty(PAT), SAM)  # still a manual-round task
    w.rr.remove_task(TINA, other.id)


def test_review_state_shows_in_the_round_and_my_tasks(w: ReviewWorld):
    task = w.task_for(UserParty(SUE), SAM)
    state = lambda: next(t.state for t in w.rr.round_view(TINA, w._round.id).tasks)  # noqa: E731
    assert state() == "not started"
    w.rv.save(SUE, task.id, w.answers(), 0)
    assert state() == "draft" and w.rr.my_tasks(SUE, w.s.id)[0].state == "draft"
    w.rv.save(SUE, task.id, w.answers(), 1, submit=True)
    assert state() == "submitted"
