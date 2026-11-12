import re

from fastapi.testclient import TestClient

from previewit.domain.policy import Action, VerificationPolicy
from tests.integration.web_fakes import Harness, csrf_token, make_harness

PASSWORD = "correct horse battery"


def signup(client: TestClient, email: str, name: str, next_: str = "/spaces") -> None:
    token = csrf_token(client, "/signup")
    r = client.post(
        "/signup",
        data={"csrf": token, "email": email, "password": PASSWORD, "name": name, "next": next_},
    )
    assert r.status_code == 303, r.text


def post(client: TestClient, path: str, data: dict[str, str] | None = None, *, page="/spaces"):
    return client.post(path, data={"csrf": csrf_token(client, page), **(data or {})})


class Course:
    """A teacher with an organization and a course, plus a joined student."""

    def __init__(self) -> None:
        self.h: Harness = make_harness()
        self.teacher = self.h.client
        signup(self.teacher, "tina@x.fi", "Tina Teacher")
        r = post(self.teacher, "/orgs", {"name": "Jyväskylä School", "preset": "education"})
        assert r.status_code == 303
        self.org_path = r.headers["location"]
        r = post(
            self.teacher,
            f"{self.org_path}/spaces",
            {"name": "Software Engineering"},
            page=self.org_path,
        )
        assert r.status_code == 303
        self.space = r.headers["location"]  # /spaces/<id>

    def invite_link(self, role: str = "student") -> str:
        r = post(self.teacher, f"{self.space}/invites", {"role": role}, page=self.space)
        assert r.status_code == 200
        match = re.search(r"/join/[A-Za-z0-9_-]+", r.text)
        assert match, r.text
        return match.group(0)

    def join_student(self, email="sam@x.fi", name="Sam Student") -> TestClient:
        link = self.invite_link()
        student = self.h.new_client()
        signup(student, email, name, next_=link)
        r = post(student, link, page=link)
        assert r.status_code == 303 and r.headers["location"] == self.space
        return student


def test_spaces_requires_login():
    client = make_harness().client
    r = client.get("/spaces")
    assert r.status_code == 303 and r.headers["location"].startswith("/login")


def test_teacher_creates_an_organization_and_a_course_using_the_presets_words():
    c = Course()
    org = c.teacher.get(c.org_path).text
    assert "Jyväskylä School" in org and "Software Engineering" in org
    assert "course" in org.lower()  # Education vocabulary
    space = c.teacher.get(c.space).text
    assert "Software Engineering" in space and "Tina Teacher" in space and "Teacher" in space
    assert "Software Engineering" in c.teacher.get("/spaces").text


def test_names_are_escaped():
    h = make_harness()
    signup(h.client, "a@x.fi", "A")
    post(h.client, "/orgs", {"name": "<script>alert(1)</script>", "preset": "education"})
    page = h.client.get("/spaces").text
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page


def test_invalid_names_are_reported():
    c = Course()
    r = post(c.teacher, f"{c.org_path}/spaces", {"name": "  "}, page=c.org_path)
    assert r.status_code == 400 and "1-100" in r.text


def test_student_joins_by_link_and_sees_the_course_but_not_the_management_tools():
    c = Course()
    student = c.join_student()
    page = student.get(c.space).text
    assert "Software Engineering" in page and "Tina Teacher" in page
    assert "Create invite link" not in page and "Create group" not in page
    assert "tina@x.fi" not in page  # emails are for managers only
    assert "sam@x.fi" in c.teacher.get(c.space).text
    assert "Software Engineering" in student.get("/spaces").text


def test_the_link_page_shows_only_the_basics_to_anonymous_visitors():
    c = Course()
    link = c.invite_link()
    anon = c.h.new_client()
    page = anon.get(link)
    assert page.status_code == 200
    assert "Software Engineering" in page.text and "Student" in page.text
    assert f"/login?next={link}" in page.text and f"/signup?next={link}" in page.text
    assert "sam@" not in page.text and "tina@" not in page.text


def test_dead_links_are_404():
    c = Course()
    assert c.h.new_client().get("/join/not-a-real-token").status_code == 404
    link = c.invite_link()
    other = c.h.new_client()
    signup(other, "z@x.fi", "Zed", next_="/spaces")
    from datetime import timedelta

    c.h.clock.now += timedelta(days=8)
    assert other.get(link).status_code == 404
    assert post(other, link, page="/spaces").status_code == 404


def test_outsiders_get_404_for_everything_in_the_course():
    c = Course()
    stranger = c.h.new_client()
    signup(stranger, "bob@x.fi", "Bob")
    post(stranger, "/orgs", {"name": "Other School", "preset": "education"})
    assert stranger.get(c.space).status_code == 404
    assert stranger.get(c.org_path).status_code == 404
    for path in ("/invites", "/groups", "/members/x/remove", "/members/x/role"):
        assert (
            post(stranger, f"{c.space}{path}", {"name": "x", "role": "teacher"}).status_code == 404
        )


def test_students_are_forbidden_from_managing_things():
    c = Course()
    student = c.join_student()
    forbidden = [
        (f"{c.space}/invites", {"role": "student"}),
        (f"{c.space}/groups", {"name": "G"}),
        (f"{c.space}/members/anyone/remove", {}),
        (f"{c.space}/members/anyone/role", {"role": "teacher"}),
        (f"{c.org_path}/spaces", {"name": "Mine"}),
    ]
    for path, data in forbidden:
        assert post(student, path, data).status_code == 403, path


def test_forms_need_a_csrf_token():
    c = Course()
    assert c.teacher.post("/orgs", data={"name": "X", "preset": "education"}).status_code == 403
    assert c.teacher.post(f"{c.space}/groups", data={"name": "X"}).status_code == 403


def test_teacher_runs_groups():
    c = Course()
    student = c.join_student()
    r = post(c.teacher, f"{c.space}/groups", {"name": "Team Red"}, page=c.space)
    assert r.status_code == 303
    page = c.teacher.get(c.space).text
    gid = re.search(r"/groups/([A-Za-z0-9_-]+)/members", page)
    assert gid, page
    group = f"{c.space}/groups/{gid.group(1)}"
    sam = re.search(r'value="([^"]+)">Sam Student', page)
    assert sam, page
    assert (
        post(c.teacher, f"{group}/members", {"user_id": sam.group(1)}, page=c.space).status_code
        == 303
    )
    assert "Team Red" in student.get(c.space).text
    assert (
        post(c.teacher, f"{group}/rename", {"name": "Team Blue"}, page=c.space).status_code == 303
    )
    assert "Team Blue" in c.teacher.get(c.space).text
    assert post(student, f"{group}/delete").status_code == 403
    assert post(c.teacher, f"{group}/delete", page=c.space).status_code == 303
    assert "Team Blue" not in c.teacher.get(c.space).text


def test_teacher_changes_roles_and_removes_members():
    c = Course()
    student = c.join_student()
    page = c.teacher.get(c.space).text
    uid = re.search(r"/members/([A-Za-z0-9_-]+)/role", page)
    assert uid
    sam_id = re.findall(r"/members/([A-Za-z0-9_-]+)/role", page)[-1]
    assert (
        post(
            c.teacher, f"{c.space}/members/{sam_id}/role", {"role": "assistant"}, page=c.space
        ).status_code
        == 303
    )
    assert "Create invite link" in student.get(c.space).text  # assistants may invite
    assert post(c.teacher, f"{c.space}/members/{sam_id}/remove", page=c.space).status_code == 303
    assert student.get(c.space).status_code == 404


def test_the_invite_secret_is_shown_once():
    c = Course()
    c.invite_link()
    again = c.teacher.get(c.space).text
    assert "/join/" not in again


def test_the_policy_can_require_a_verified_email_to_create_an_organization():
    h = make_harness(policy=VerificationPolicy(frozenset({Action.CREATE_ORGANIZATION})))
    signup(h.client, "tina@x.fi", "Tina Teacher")
    r = post(h.client, "/orgs", {"name": "School", "preset": "education"})
    assert r.status_code == 403
    assert "Verify your email" in r.text and "/account" in r.text
