import re

from fastapi.testclient import TestClient

from previewit.domain.policy import Action, VerificationPolicy
from tests.integration.test_tenancy_web import Course, post, signup
from tests.integration.web_fakes import csrf_token, make_harness

PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


def create_call(c: Course, title="Essay", kind="text", **extra) -> str:
    data = {"title": title, "artifact_type": kind, "published": "on", **extra}
    r = post(c.teacher, f"{c.space}/calls", data, page=f"{c.space}/calls")
    assert r.status_code == 303, r.text
    return r.headers["location"]  # /calls/<id>


def submit_text(client: TestClient, call: str, title="My essay", text="Hello world"):
    return post(client, f"{call}/submissions", {"title": title, "text": text}, page="/spaces")


def test_the_whole_flow_for_a_text_call():
    c = Course()
    sam = c.join_student()
    call = create_call(c, "Essay one")
    assert "Essay one" in sam.get(f"{c.space}/calls").text
    page = sam.get(call)
    assert page.status_code == 200 and 'name="text"' in page.text

    r = submit_text(sam, call, text="First <b>draft</b>")
    assert r.status_code == 303
    sub = r.headers["location"]
    shown = sam.get(sub).text
    assert "&lt;b&gt;draft&lt;/b&gt;" in shown and "<b>draft</b>" not in shown  # escaped

    r = post(sam, f"{sub}/revisions", {"text": "Second draft"}, page=sub)
    assert r.status_code == 303
    latest = sam.get(sub).text
    assert "Second draft" in latest and "Revision 2 of 2" in latest
    old = sam.get(f"{sub}?rev=1").text
    assert "First" in old and "Revision 1 of 2" in old
    assert sam.get(f"{sub}/revisions/1/raw").text == "First <b>draft</b>"


def test_the_teacher_sees_all_work_and_a_student_does_not():
    c = Course()
    sam = c.join_student()
    sue = c.join_student("sue@x.fi", "Sue Student")
    call = create_call(c)
    sub = submit_text(sam, call, "Sam's essay").headers["location"]
    submit_text(sue, call, "Sue's essay")
    teacher_view = c.teacher.get(call).text
    assert "Sam&#39;s essay" in teacher_view and "Sue&#39;s essay" in teacher_view
    assert "Sam&#39;s essay" not in sue.get(call).text
    assert sue.get(sub).status_code == 404 and c.teacher.get(sub).status_code == 200


def test_students_cannot_manage_calls_and_outsiders_see_nothing():
    c = Course()
    sam = c.join_student()
    r = post(sam, f"{c.space}/calls", {"title": "X", "artifact_type": "text"}, page="/spaces")
    assert r.status_code == 403
    call = create_call(c)
    stranger = c.h.new_client()
    signup(stranger, "zed@x.fi", "Zed")
    assert stranger.get(call).status_code == 404
    assert stranger.get(f"{c.space}/calls").status_code == 404


def test_a_draft_call_is_hidden_from_students():
    c = Course()
    sam = c.join_student()
    r = post(
        c.teacher,
        f"{c.space}/calls",
        {"title": "Secret", "artifact_type": "text"},
        page=f"{c.space}/calls",
    )
    draft = r.headers["location"]
    assert sam.get(draft).status_code == 404
    assert "Secret" not in sam.get(f"{c.space}/calls").text
    assert "draft" in c.teacher.get(f"{c.space}/calls").text


def test_pdf_calls_take_files_and_reject_everything_else():
    c = Course()
    sam = c.join_student()
    call = create_call(c, "Paper", "pdf")
    assert 'type="file"' in sam.get(call).text
    token = csrf_token(sam, call)

    def upload(content: bytes, name="paper.pdf"):
        return sam.post(
            f"{call}/submissions",
            data={"csrf": token, "title": "Paper"},
            files={"file": (name, content, "application/pdf")},
        )

    bad = upload(b"GIF89a not a pdf")
    assert bad.status_code == 400 and "not a PDF" in bad.text
    ok = upload(PDF)
    assert ok.status_code == 303
    sub = ok.headers["location"]
    assert "<object" in sam.get(sub).text
    raw = sam.get(f"{sub}/revisions/1/raw")
    assert raw.content == PDF and raw.headers["content-type"] == "application/pdf"
    assert raw.headers["x-content-type-options"] == "nosniff"
    assert "paper.pdf" in raw.headers["content-disposition"]


def test_an_empty_submission_is_refused_with_a_message():
    c = Course()
    sam = c.join_student()
    call = create_call(c)
    r = submit_text(sam, call, text="   ")
    assert r.status_code == 400 and "Write or paste some text" in r.text
    assert submit_text(sam, call).status_code == 303
    again = submit_text(sam, call, "Again")
    assert again.status_code == 400 and "already been submitted" in again.text


def test_oversized_uploads_are_refused_before_they_are_read():
    c = Course()
    sam = c.join_student()
    call = create_call(c, "Paper", "pdf")
    token = csrf_token(sam, call)
    r = sam.post(
        f"{call}/submissions",
        data={"csrf": token, "title": "Big"},
        files={"file": ("big.pdf", b"%PDF-" + b"x" * 12_100_000, "application/pdf")},
    )
    assert r.status_code == 413


def test_group_work_is_submitted_by_the_group():
    c = Course()
    sam = c.join_student()
    sue = c.join_student("sue@x.fi", "Sue Student")
    pat = c.join_student("pat@x.fi", "Pat Student")
    post(c.teacher, f"{c.space}/groups", {"name": "Team Rocket"}, page=c.space)
    page = c.teacher.get(c.space).text
    group = re.search(r"/groups/([^/]+)/rename", page)
    assert group
    for name in ("Sam", "Sue"):
        option = re.search(rf'<option value="([^"]+)">{name} Student</option>', page)
        assert option
        r = post(
            c.teacher,
            f"{c.space}/groups/{group.group(1)}/members",
            {"user_id": option.group(1)},
            page=c.space,
        )
        assert r.status_code == 303

    call = create_call(c, "Project", group_work="on")
    assert "Submit for Team Rocket" in sam.get(call).text
    assert "not in a group" in pat.get(call).text
    r = post(pat, f"{call}/submissions", {"title": "x", "text": "y"}, page="/spaces")
    assert r.status_code == 403

    sub = submit_text(sam, call, "Our project", "v1").headers["location"]
    assert "Team Rocket" in sue.get(sub).text  # a teammate sees the group's work
    assert post(sue, f"{sub}/revisions", {"text": "v2 by Sue"}, page=sub).status_code == 303
    assert "v2 by Sue" in sam.get(sub).text
    assert pat.get(sub).status_code == 404
    assert 'href="/submissions/' in sue.get(call).text  # and finds it from the call page
    assert "Submit for" not in sue.get(call).text  # the group has already submitted


def test_the_policy_can_require_a_verified_email_to_submit():
    h = make_harness(policy=VerificationPolicy(frozenset({Action.SUBMIT})))
    teacher = h.client
    signup(teacher, "tina@x.fi", "Tina")
    org = post(teacher, "/orgs", {"name": "S", "preset": "education"}).headers["location"]
    space = post(teacher, f"{org}/spaces", {"name": "C"}, page=org).headers["location"]
    call = post(
        teacher,
        f"{space}/calls",
        {"title": "E", "artifact_type": "text", "published": "on"},
        page=f"{space}/calls",
    ).headers["location"]
    r = post(teacher, f"{call}/submissions", {"title": "x", "text": "y"}, page=call)
    assert r.status_code == 403 and "Verify your email" in r.text


# --- review by link ---------------------------------------------------------------------------


def share_link(client: TestClient, target: str) -> str:
    r = post(client, f"{target}/shares", page=target)
    assert r.status_code == 200, r.text
    match = re.search(r"/s/[A-Za-z0-9_-]+", r.text)
    assert match, r.text
    return match.group(0)


def test_a_reviewer_opens_a_shared_submission_with_minimal_sign_up():
    c = Course()
    sam = c.join_student()
    call = create_call(c)
    sub = submit_text(sam, call, "Sam's essay", "Please review me").headers["location"]
    link = share_link(sam, sub)

    reviewer = c.h.new_client()
    landing = reviewer.get(link)
    assert landing.status_code == 200 and "Sam Student shared this work" in landing.text
    assert f"/signup?next={link}" in landing.text
    signup(reviewer, "rita@x.fi", "Rita Reviewer", next_=link)
    opened = post(reviewer, link, page=link)
    assert opened.status_code == 303 and opened.headers["location"] == sub

    page = reviewer.get(sub).text
    assert "Please review me" in page and "through a share link" in page
    assert "Add a new revision" not in page and "Create share link" not in page
    assert "Sam&#39;s essay" in reviewer.get("/shared").text
    assert reviewer.get(call).status_code == 404  # the call itself stays closed
    assert reviewer.get(f"{c.space}/calls").status_code == 404


def test_a_shared_call_is_visible_but_cannot_be_submitted_to():
    c = Course()
    call = create_call(c, "Open call")
    link = share_link(c.teacher, call)
    guest = c.h.new_client()
    signup(guest, "gus@x.fi", "Gus Guest", next_=link)
    assert post(guest, link, page=link).headers["location"] == call
    page = guest.get(call).text
    assert "Open call" in page and 'name="text"' not in page
    r = post(guest, f"{call}/submissions", {"title": "x", "text": "y"}, page="/spaces")
    assert r.status_code == 403


def test_revoked_and_bogus_links_show_a_clear_page():
    c = Course()
    call = create_call(c)
    link = share_link(c.teacher, call)
    c.teacher.get(call)
    page = c.teacher.get(call).text
    link_id = re.search(r"/shares/([0-9a-f]{64})/revoke", page)
    assert link_id
    r = post(c.teacher, f"{call}/shares/{link_id.group(1)}/revoke", page=call)
    assert r.status_code == 303
    stranger = c.h.new_client()
    gone = stranger.get(link)
    assert gone.status_code == 404 and "Link not valid" in gone.text
    assert stranger.get("/s/not-a-real-token").status_code == 404


def test_pages_require_login():
    client = make_harness().client
    for path in ("/calls/x", "/submissions/x", "/shared", "/spaces/x/calls"):
        r = client.get(path)
        assert r.status_code == 303 and r.headers["location"].startswith("/login")
