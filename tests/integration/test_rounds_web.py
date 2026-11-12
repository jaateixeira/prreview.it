import re

from tests.integration.test_calls_web import create_call, submit_text
from tests.integration.test_tenancy_web import Course, post, signup


def page_of(c: Course, call: str) -> str:
    return f"{call}/rounds"


def new_round(c: Course, call: str, **extra):
    data = {"per_submission": "1", "strategy": "round_robin", "anonymity": "reviewers_hidden"}
    data.update(extra)
    return post(c.teacher, f"{call}/rounds", data, page=page_of(c, call))


def course_with_work(n=3):
    c = Course()
    students = [c.join_student(f"s{i}@x.fi", f"Student{i}") for i in range(n)]
    call = create_call(c, "Essay")
    for i, s in enumerate(students):
        submit_text(s, call, f"Essay by {i}", f"text {i}")
    return c, call, students


def find(pattern: str, text: str) -> str:
    found = re.search(pattern, text)
    assert found, pattern
    return found.group(1)


def round_id(c: Course, call: str) -> str:
    return find(r"/rounds/(\w+)/edit", c.teacher.get(page_of(c, call)).text)


def test_a_teacher_creates_a_round_allocates_and_students_see_their_reviews():
    c, call, students = course_with_work(3)
    r = new_round(c, call, per_submission="2", strategy="random")
    assert r.status_code == 303
    page = c.teacher.get(page_of(c, call)).text
    assert "Round 1" in page and "2 reviews per submission" in page
    rid = round_id(c, call)
    r = post(c.teacher, f"/rounds/{rid}/allocate", {}, page=page_of(c, call))
    assert r.status_code == 200 and "Allocated 6 reviews." in r.text
    mine = students[0].get(f"{c.space}/reviews").text
    assert mine.count('<li class="card">') == 2 and "Essay by 0" not in mine
    assert "round 1" in mine


def test_a_second_round_is_numbered_and_kept_separate():
    c, call, _ = course_with_work(2)
    new_round(c, call)
    new_round(c, call)
    page = c.teacher.get(page_of(c, call)).text
    assert "Round 1" in page and "Round 2" in page


def test_bad_settings_show_an_error_and_create_nothing():
    c, call, _ = course_with_work(2)
    for data, expected in (
        ({"per_submission": "0"}, "between 1 and 20"),
        ({"per_submission": "many"}, "whole number"),
        ({"strategy": "astrology"}, "Choose an allocation method"),
        ({"opens_at": "tomorrow"}, "date and time"),
        ({"opens_at": "2030-01-02T10:00", "closes_at": "2030-01-01T10:00"}, "close after"),
    ):
        r = new_round(c, call, **data)
        assert r.status_code == 400 and expected in r.text, data
    assert "No rounds yet" in c.teacher.get(page_of(c, call)).text


def test_allocation_without_submissions_explains_why():
    c = Course()
    call = create_call(c, "Empty")
    new_round(c, call)
    r = post(c.teacher, f"/rounds/{round_id(c, call)}/allocate", {}, page=page_of(c, call))
    assert r.status_code == 400 and "no submissions" in r.text


def test_manual_pairing_and_removal():
    c, call, students = course_with_work(2)
    new_round(c, call, strategy="manual")
    rid = round_id(c, call)
    page = c.teacher.get(page_of(c, call)).text
    sub = find(r'<option value="(\w+)">Essay by 0', page)
    reviewer = find(r'<option value="(user:\w+)">Student1', page)
    r = post(
        c.teacher,
        f"/rounds/{rid}/tasks",
        {"submission_id": sub, "reviewer": reviewer},
        page=page_of(c, call),
    )
    assert r.status_code == 303
    assert "Student1" in c.teacher.get(page_of(c, call)).text
    assert students[1].get(f"{c.space}/reviews").text.count('<li class="card">') == 1
    again = post(
        c.teacher,
        f"/rounds/{rid}/tasks",
        {"submission_id": sub, "reviewer": reviewer},
        page=page_of(c, call),
    )
    assert again.status_code == 400 and "already" in again.text
    task = find(r"/tasks/(\w+)/delete", c.teacher.get(page_of(c, call)).text)
    post(c.teacher, f"/rounds/{rid}/tasks/{task}/delete", {}, page=page_of(c, call))
    assert students[1].get(f"{c.space}/reviews").text.count('<li class="card">') == 0


def test_a_manual_round_cannot_be_auto_allocated():
    c, call, _ = course_with_work(2)
    new_round(c, call, strategy="manual")
    r = post(c.teacher, f"/rounds/{round_id(c, call)}/allocate", {}, page=page_of(c, call))
    assert r.status_code == 400 and "by hand" in r.text


def test_students_and_outsiders_cannot_manage_rounds():
    c, call, students = course_with_work(2)
    new_round(c, call)
    rid = round_id(c, call)
    sam = students[0]
    assert sam.get(page_of(c, call)).status_code == 403
    for path in (f"/rounds/{rid}/allocate", f"/rounds/{rid}/delete"):
        assert post(sam, path, {}, page="/spaces").status_code in (403, 404)
    assert post(sam, f"{call}/rounds", {"per_submission": "1", "strategy": "random"},
                page="/spaces").status_code == 403  # fmt: skip


def test_edit_and_delete_a_round():
    c, call, _ = course_with_work(2)
    new_round(c, call)
    rid = round_id(c, call)
    r = post(
        c.teacher,
        f"/rounds/{rid}/edit",
        {"per_submission": "3", "strategy": "random", "anonymity": "double_anonymous"},
        page=page_of(c, call),
    )
    assert r.status_code == 303
    page = c.teacher.get(page_of(c, call)).text
    assert "3 reviews per submission" in page and "Neither side sees the other" in page
    post(c.teacher, f"/rounds/{rid}/delete", {}, page=page_of(c, call))
    assert "No rounds yet" in c.teacher.get(page_of(c, call)).text


def test_outsiders_get_404_for_rounds_and_reviews():
    c, call, _ = course_with_work(2)
    new_round(c, call)
    rid = round_id(c, call)
    stranger = c.h.new_client()
    signup(stranger, "zed@x.fi", "Zed")
    assert stranger.get(page_of(c, call)).status_code == 404
    assert stranger.get(f"{c.space}/reviews").status_code == 404
    assert post(stranger, f"/rounds/{rid}/allocate", {}, page="/spaces").status_code == 404
