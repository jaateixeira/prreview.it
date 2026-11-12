import re

from tests.integration.test_calls_web import create_call
from tests.integration.test_tenancy_web import Course, post


def make_rubric(c: Course, name="Essay rubric", template="") -> str:
    r = post(
        c.teacher,
        f"{c.space}/rubrics",
        {"name": name, "description": "", "template": template},
        page=f"{c.space}/rubrics",
    )
    assert r.status_code == 303, r.text
    return r.headers["location"]  # /rubrics/<id>


def add(c: Course, rubric: str, **data):
    return post(c.teacher, f"{rubric}/criteria", data, page=rubric)


def test_a_teacher_builds_a_rubric_and_sees_the_review_form():
    c = Course()
    rubric = make_rubric(c)
    assert "no criteria yet" in c.teacher.get(rubric).text
    r = add(c, rubric, type_key="numeric", title="Clarity", cfg_min="1", cfg_max="5", weight="2")
    assert r.status_code == 303
    add(c, rubric, type_key="levels", title="Argument", cfg_levels="Weak | Thin\nStrong | Solid")
    add(c, rubric, type_key="text", title="Comments", cfg_max_length="500", weight="0")
    page = c.teacher.get(rubric).text
    assert "Clarity" in page and 'type="number"' in page and "Strong" in page
    assert page.index("Clarity") < page.index("Argument") < page.index("Comments")


def test_a_template_creates_a_ready_rubric():
    c = Course()
    page = c.teacher.get(f"{c.space}/rubrics").text
    found = re.search(r'<option value="([a-z-]+)"', page)
    assert found
    key = found.group(1)
    rubric = make_rubric(c, "From template", key)
    assert "<fieldset" in c.teacher.get(rubric).text


def test_bad_input_shows_an_error_and_changes_nothing():
    c = Course()
    rubric = make_rubric(c)
    r = add(c, rubric, type_key="numeric", title="Bad", cfg_min="5", cfg_max="1")
    assert r.status_code == 400 and "highest value" in r.text
    r = add(c, rubric, type_key="nonsense", title="X")
    assert r.status_code == 400 and "Choose a kind" in r.text
    r = add(c, rubric, type_key="yes_no", title="Fine", weight="lots")
    assert r.status_code == 400 and "whole numbers" in r.text
    assert "no criteria yet" in c.teacher.get(rubric).text


def test_criteria_can_be_edited_moved_and_deleted():
    c = Course()
    rubric = make_rubric(c)
    add(c, rubric, type_key="yes_no", title="First")
    add(c, rubric, type_key="yes_no", title="Second")
    page = c.teacher.get(rubric).text
    found = re.search(r"/criteria/(\w+)/edit", page)
    assert found
    first = found.group(1)
    r = post(
        c.teacher,
        f"{rubric}/criteria/{first}/edit",
        {"type_key": "yes_no", "title": "Renamed", "weight": "3", "required": "on"},
        page=rubric,
    )
    assert r.status_code == 303 and "Renamed" in c.teacher.get(rubric).text
    post(c.teacher, f"{rubric}/criteria/{first}/move", {"direction": "down"}, page=rubric)
    page = c.teacher.get(rubric).text
    assert page.index("Second") < page.index("Renamed")
    post(c.teacher, f"{rubric}/criteria/{first}/delete", {}, page=rubric)
    assert "Renamed" not in c.teacher.get(rubric).text


def test_a_rubric_is_attached_to_a_call_and_students_see_it():
    c = Course()
    sam = c.join_student()
    rubric = make_rubric(c)
    add(c, rubric, type_key="yes_no", title="Has a thesis")
    call = create_call(c)
    assert "Has a thesis" not in sam.get(call).text
    rid = rubric.rsplit("/", 1)[1]
    r = post(c.teacher, f"{call}/rubric", {"rubric_id": rid}, page=call)
    assert r.status_code == 303
    assert "Has a thesis" in sam.get(call).text and "Has a thesis" in c.teacher.get(call).text
    r = post(c.teacher, f"{rubric}/delete", {}, page=rubric)
    assert r.status_code == 400 and "Calls use this rubric" in r.text
    post(c.teacher, f"{call}/rubric", {"rubric_id": ""}, page=call)
    assert "Has a thesis" not in sam.get(call).text
    assert post(c.teacher, f"{rubric}/delete", {}, page=rubric).status_code == 303


def test_a_draft_calls_rubric_is_hidden_from_students():
    c = Course()
    sam = c.join_student()
    rubric = make_rubric(c)
    add(c, rubric, type_key="yes_no", title="Secret criterion")
    call = create_call(c, published="")
    post(c.teacher, f"{call}/rubric", {"rubric_id": rubric.rsplit("/", 1)[1]}, page=call)
    assert "Secret criterion" not in sam.get(call).text


def test_students_cannot_build_or_open_the_builder_and_outsiders_see_nothing():
    c = Course()
    sam = c.join_student()
    rubric = make_rubric(c)
    assert sam.get(f"{c.space}/rubrics").status_code == 403
    assert sam.get(rubric).status_code in (403, 404)  # existence is not revealed
    r = post(sam, f"{c.space}/rubrics", {"name": "Mine"}, page="/spaces")
    assert r.status_code == 403
    r = post(sam, f"{rubric}/criteria", {"type_key": "yes_no", "title": "x"}, page="/spaces")
    assert r.status_code in (403, 404)
    assert "Rubrics" not in sam.get(c.space).text


def test_a_rubric_can_be_copied():
    c = Course()
    rubric = make_rubric(c, "Original")
    add(c, rubric, type_key="yes_no", title="Kept")
    r = post(c.teacher, f"{rubric}/duplicate", {}, page=rubric)
    assert r.status_code == 303 and r.headers["location"] != rubric
    copy = c.teacher.get(r.headers["location"]).text
    assert "Original (copy)" in copy and "Kept" in copy
