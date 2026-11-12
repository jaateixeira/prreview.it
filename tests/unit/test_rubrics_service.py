from itertools import count

import pytest

from previewit.adapters.persistence.memory_rubrics import InMemoryRubricRepository
from previewit.application.criteria import CriterionError, CriterionRegistry, UnknownCriterionType
from previewit.application.rubrics import RubricInUse, RubricsService
from previewit.application.tenancy import Forbidden, NotFound
from previewit.domain.rubrics import InvalidRubric, RubricId
from previewit.plugins.criteria import (
    LevelsCriterion,
    NumericCriterion,
    TextCriterion,
    YesNoCriterion,
)
from tests.unit.test_calls_service import SAM, TINA, ZED, CWorld
from tests.unit.test_tenancy_service import ALICE, AVA, BOB

LEVELS = "Weak | needs work\nStrong | great"


class RWorld(CWorld):
    """The calls world plus a rubrics service."""

    def __init__(self, *args, rubrics_repo=None, **kw):
        super().__init__(*args, **kw)
        ids = count(1)
        self.r = RubricsService(
            rubrics_repo or InMemoryRubricRepository(),
            self.c._repo,
            self.t,
            CriterionRegistry(
                [NumericCriterion(), LevelsCriterion(), YesNoCriterion(), TextCriterion()]
            ),
            lambda: f"r{next(ids)}",
        )
        self.rubric = self.r.create_rubric(TINA, self.s.id, "Essay rubric")

    def add(self, type_key="numeric", title="Clarity", **kw):
        raw = kw.pop("raw_config", {"min": "1", "max": "5"} if type_key == "numeric" else {})
        return self.r.add_criterion(
            TINA, self.rubric.id, type_key=type_key, title=title, raw_config=raw, **kw
        )

    def titles(self, actor=TINA):
        return [c.criterion.title for c in self.r.rubric_view(actor, self.rubric.id).criteria]


@pytest.fixture
def w() -> RWorld:
    return RWorld()


# --- who may build rubrics --------------------------------------------------------------------


def test_only_teachers_and_owners_manage_rubrics(w: RWorld):
    for user in (SAM, AVA):  # student, assistant
        with pytest.raises(Forbidden):
            w.r.create_rubric(user, w.s.id, "X")
        with pytest.raises(Forbidden):
            w.r.rubrics(user, w.s.id)
    with pytest.raises(NotFound):
        w.r.create_rubric(BOB, w.s.id, "X")  # another organization
    assert w.r.create_rubric(ALICE, w.s.id, "Owner's").name == "Owner's"
    assert [r.name for r in w.r.rubrics(TINA, w.s.id)] == ["Essay rubric", "Owner's"]


def test_rubric_names_are_validated_and_editable(w: RWorld):
    with pytest.raises(InvalidRubric):
        w.r.create_rubric(TINA, w.s.id, "  ")
    updated = w.r.update_rubric(TINA, w.rubric.id, "Renamed", "About it")
    assert (updated.name, updated.description) == ("Renamed", "About it")
    with pytest.raises(Forbidden):
        w.r.update_rubric(SAM, w.rubric.id, "x", "")


# --- criteria ---------------------------------------------------------------------------------


def test_criteria_keep_their_order_and_validate_through_their_type(w: RWorld):
    w.add("numeric", "Clarity")
    w.add("levels", "Argument", raw_config={"levels": LEVELS}, weight=2)
    w.add("yes_no", "On topic")
    w.add("text", "Comments", weight=0, required=False)
    view = w.r.rubric_view(TINA, w.rubric.id)
    assert [c.criterion.title for c in view.criteria] == [
        "Clarity", "Argument", "On topic", "Comments",
    ]  # fmt: skip
    assert [c.summary for c in view.criteria][:2] == ["1 to 5", "Weak / Strong"]
    assert [c.max_score for c in view.criteria] == [5, 2, 1, None]
    assert view.total_weight == 1 + 2 + 1 + 0 and view.can_manage
    assert all(c.input_html for c in view.criteria)
    with pytest.raises(CriterionError):
        w.add("numeric", "Bad", raw_config={"min": "5", "max": "1"})
    with pytest.raises(UnknownCriterionType):
        w.add("hologram", "?")
    with pytest.raises(InvalidRubric):
        w.add("yes_no", " ")
    with pytest.raises(InvalidRubric):
        w.add("yes_no", "Heavy", weight=101)
    assert len(w.titles()) == 4  # nothing half-added


def test_the_number_of_criteria_is_limited(w: RWorld):
    for i in range(30):
        w.add("yes_no", f"C{i}")
    with pytest.raises(InvalidRubric, match="at most 30"):
        w.add("yes_no", "one too many")


def test_updating_a_criterion_keeps_its_type_and_position(w: RWorld):
    w.add("yes_no", "First")
    c = w.add("numeric", "Second")
    updated = w.r.update_criterion(
        TINA, w.rubric.id, c.id, title="Renamed", guidance="Hint",
        raw_config={"min": "0", "max": "10"}, weight=3, required=False,
    )  # fmt: skip
    assert (updated.type_key, updated.position, updated.config) == (
        "numeric",
        1,
        {"min": 0, "max": 10},
    )
    assert (updated.title, updated.weight, updated.required) == ("Renamed", 3, False)
    with pytest.raises(CriterionError):
        w.r.update_criterion(
            TINA, w.rubric.id, c.id, title="x", guidance="", raw_config={"min": "x"},
            weight=1, required=True,
        )  # fmt: skip
    assert w.titles() == ["First", "Renamed"]


def test_moving_and_deleting_criteria_renumbers_cleanly(w: RWorld):
    a, b, c = (w.add("yes_no", t) for t in "ABC")
    w.r.move_criterion(TINA, w.rubric.id, c.id, -1)
    assert w.titles() == ["A", "C", "B"]
    w.r.move_criterion(TINA, w.rubric.id, a.id, -1)  # already first: stays
    w.r.move_criterion(TINA, w.rubric.id, b.id, +1)  # already last: stays
    assert w.titles() == ["A", "C", "B"]
    w.r.delete_criterion(TINA, w.rubric.id, c.id)
    assert w.titles() == ["A", "B"]
    positions = [x.criterion.position for x in w.r.rubric_view(TINA, w.rubric.id).criteria]
    assert positions == [0, 1]
    assert w.add("yes_no", "D").position == 2


def test_criteria_of_another_rubric_cannot_be_touched(w: RWorld):
    other = w.r.create_rubric(TINA, w.s.id, "Other")
    mine = w.add("yes_no", "Mine")
    with pytest.raises(NotFound):
        w.r.delete_criterion(TINA, other.id, mine.id)
    with pytest.raises(NotFound):
        w.r.move_criterion(TINA, other.id, mine.id, 1)
    assert w.titles() == ["Mine"]


# --- templates and reuse ----------------------------------------------------------------------


def test_a_rubric_can_start_from_a_template(w: RWorld):
    templates = w.r.templates(TINA, w.s.id)
    assert {t.key for t in templates} >= {"essay-feedback", "quick-check"}
    made = w.r.create_rubric(TINA, w.s.id, "From template", template_key="essay-feedback")
    view = w.r.rubric_view(TINA, made.id)
    assert [c.criterion.title for c in view.criteria][:2] == ["Clarity", "Argument"]
    assert view.total_weight == 1 + 2
    with pytest.raises(InvalidRubric):
        w.r.create_rubric(TINA, w.s.id, "x", template_key="nope")
    with pytest.raises(Forbidden):
        w.r.templates(SAM, w.s.id)


def test_duplicating_copies_criteria_independently(w: RWorld):
    w.add("numeric", "Clarity")
    copy = w.r.duplicate_rubric(TINA, w.rubric.id)
    assert copy.name == "Essay rubric (copy)" and copy.id != w.rubric.id
    w.r.add_criterion(TINA, copy.id, type_key="yes_no", title="Only in copy")
    assert w.titles() == ["Clarity"]
    assert [c.criterion.title for c in w.r.rubric_view(TINA, copy.id).criteria] == [
        "Clarity", "Only in copy",
    ]  # fmt: skip


def test_duplicating_into_another_space_of_the_same_organization(w: RWorld):
    w.add("numeric", "Clarity")
    second = w.t.create_space(ALICE, w.org_a.id, "Databases")
    with pytest.raises(NotFound):
        w.r.duplicate_rubric(TINA, w.rubric.id, into_space=second.id)  # tina is not in it
    copy = w.r.duplicate_rubric(ALICE, w.rubric.id, into_space=second.id, name="Reused")
    assert copy.space_id == second.id and copy.name == "Reused"
    assert [r.name for r in w.r.rubrics(ALICE, second.id)] == ["Reused"]


def test_duplicating_never_crosses_organizations(w: RWorld):
    with pytest.raises(NotFound):
        w.r.duplicate_rubric(BOB, w.rubric.id)  # bob cannot even see it
    with pytest.raises(NotFound):
        w.r.duplicate_rubric(ALICE, w.rubric.id, into_space=w.other.id)  # alice is not in org B


# --- attaching to calls -----------------------------------------------------------------------


def test_a_rubric_is_attached_to_a_call_and_shown_to_members(w: RWorld):
    w.add("numeric", "Clarity")
    assert w.r.rubric_for_call(SAM, w.call.id) is None
    w.r.attach(TINA, w.call.id, w.rubric.id)
    shown = w.r.rubric_for_call(SAM, w.call.id)
    assert shown is not None and not shown.can_manage and shown.used_by == 1
    assert [c.criterion.title for c in shown.criteria] == ["Clarity"]
    assert w.r.rubric_view(SAM, w.rubric.id).criteria  # students may read an attached rubric
    with pytest.raises(Forbidden):
        w.r.rubrics(SAM, w.s.id)  # but not browse the library
    with pytest.raises(Forbidden):
        w.r.attach(SAM, w.call.id, None)
    assert w.r.rubric_for_call(ZED, w.call.id) is None
    w.r.attach(TINA, w.call.id, None)
    assert w.r.rubric_for_call(SAM, w.call.id) is None


def test_a_rubric_on_an_unpublished_call_stays_private_to_managers(w: RWorld):
    w.add("numeric", "Clarity")
    draft = w.c.create_call(TINA, w.s.id, title="Draft", artifact_type="text")
    w.r.attach(TINA, draft.id, w.rubric.id)
    with pytest.raises(NotFound):
        w.r.rubric_view(SAM, w.rubric.id)
    assert w.r.rubric_view(TINA, w.rubric.id).used_by == 1


def test_only_rubrics_of_the_same_space_can_be_attached(w: RWorld):
    with pytest.raises(NotFound):
        w.r.attach(TINA, w.call.id, RubricId("no-such-rubric"))
    second = w.t.create_space(ALICE, w.org_a.id, "Databases")
    elsewhere = w.r.create_rubric(ALICE, second.id, "Elsewhere")
    with pytest.raises(NotFound):
        w.r.attach(TINA, w.call.id, elsewhere.id)  # duplicate it into the space instead


def test_a_rubric_in_use_cannot_be_deleted(w: RWorld):
    w.r.attach(TINA, w.call.id, w.rubric.id)
    with pytest.raises(RubricInUse):
        w.r.delete_rubric(TINA, w.rubric.id)
    w.r.attach(TINA, w.call.id, None)
    w.add("yes_no", "Q")
    w.r.delete_rubric(TINA, w.rubric.id)
    with pytest.raises(NotFound):
        w.r.rubric_view(TINA, w.rubric.id)


def test_editing_a_call_keeps_its_rubric(w: RWorld):
    w.r.attach(TINA, w.call.id, w.rubric.id)
    w.c.update_call(
        TINA, w.call.id, title="Renamed", description="", closes_at=None, published=True
    )
    assert w.r.rubric_for_call(SAM, w.call.id) is not None
