import re

from tests.integration.test_calls_web import create_call, submit_text
from tests.integration.test_rubrics_web import add, make_rubric
from tests.integration.test_tenancy_web import Course, post, signup

TEXT = "The quick brown fox jumps over the lazy dog"


def find(pattern: str, text: str) -> str:
    found = re.search(pattern, text)
    assert found, pattern
    return found.group(1)


class Setup:
    """A course with a rubric, an essay by Sam, and Sue assigned to review it."""

    def __init__(self, group=False):
        self.c = Course()
        self.sam = self.c.join_student("sam@x.fi", "Sam")
        self.sue = self.c.join_student("sue@x.fi", "Sue")
        self.pat = self.c.join_student("pat@x.fi", "Pat")
        rubric = make_rubric(self.c)
        add(
            self.c,
            rubric,
            type_key="numeric",
            title="Clarity",
            cfg_min="1",
            cfg_max="5",
            required="on",
        )
        add(self.c, rubric, type_key="text", title="Comment", cfg_max_length="200", required="")
        self.call = create_call(self.c, "Essay")
        post(self.c.teacher, f"{self.call}/rubric", {"rubric_id": rubric.rsplit("/", 1)[1]},
             page=self.call)  # fmt: skip
        self.sub = submit_text(self.sam, self.call, "On foxes", TEXT).headers["location"]
        post(self.c.teacher, f"{self.call}/rounds", {"per_submission": "1", "strategy": "manual",
             "anonymity": "reviewers_hidden"}, page=f"{self.call}/rounds")  # fmt: skip
        page = self.c.teacher.get(f"{self.call}/rounds").text
        self.round = find(r"/rounds/(\w+)/edit", page)
        sub_id = find(r'<option value="(\w+)">On foxes', page)
        if group:
            post(self.c.teacher, f"{self.c.space}/groups", {"name": "Reviewers"}, page=self.c.space)
            space = self.c.teacher.get(self.c.space).text
            gid = find(r"/groups/([A-Za-z0-9_-]+)/members", space)
            for who in ("Sue", "Pat"):
                uid = find(r'value="([^"]+)">' + who, space)
                post(self.c.teacher, f"{self.c.space}/groups/{gid}/members", {"user_id": uid},
                     page=self.c.space)  # fmt: skip
            page = self.c.teacher.get(f"{self.call}/rounds").text
            reviewer = find(r'<option value="(group:\w+)">Reviewers', page)
        else:
            reviewer = find(r'<option value="(user:\w+)">Sue', page)
        data = {"submission_id": sub_id, "reviewer": reviewer}
        post(self.c.teacher, f"/rounds/{self.round}/tasks", data, page=f"{self.call}/rounds")
        self.task = find(r'href="(/tasks/\w+)"', self.sue.get(f"{self.c.space}/reviews").text)
        self.page = self.sue.get(self.task).text
        self.clarity = find(r'name="(criterion-\w+)"[^>]*min="1"', self.page)
        self.comment = find(r'<textarea name="(criterion-\w+)"', self.page)

    def save(self, client=None, intent="draft", version="0", **fields):
        data = {"intent": intent, "version": version, **fields}
        return post(client or self.sue, self.task, data, page="/spaces")


def test_the_reviewer_sees_the_work_beside_the_form():
    s = Setup()
    assert TEXT in s.page and "Clarity" in s.page and "Comment" in s.page
    assert "Sam" not in s.page.split("<main")[1]  # the author is not named (anonymity default)
    assert 'hx-post="' + s.task + '/autosave"' in s.page


def test_draft_then_submit_with_required_answers():
    s = Setup()
    r = s.save(**{s.clarity: "3"})
    assert r.status_code == 303 and "saved=1" in r.headers["location"]
    again = s.sue.get(s.task).text
    assert 'value="3"' in again and 'name="version" value="1"' in again
    bad = s.save(intent="submit", version="1", **{s.comment: "just a note"})
    assert bad.status_code == 400 and "required" in bad.text and "Clarity" in bad.text
    ok = s.save(intent="submit", version="1", **{s.clarity: "4", s.comment: "Nice"})
    assert ok.status_code == 303 and "submitted=1" in ok.headers["location"]
    assert "Review submitted" in s.sue.get(ok.headers["location"]).text


def test_bad_answers_keep_what_was_typed_and_explain():
    s = Setup()
    r = s.save(**{s.clarity: "9", s.comment: "my words"})
    assert r.status_code == 400 and "between 1 and 5" in r.text
    assert 'value="9"' in r.text and "my words" in r.text


def test_autosave_answers_with_a_status_fragment_and_the_next_version():
    s = Setup()
    r = post(s.sue, f"{s.task}/autosave", {"version": "0", s.clarity: "2"}, page="/spaces")
    assert r.status_code == 200 and "Saved" in r.text and 'id="version"' in r.text
    assert 'value="1"' in r.text
    bad = post(s.sue, f"{s.task}/autosave", {"version": "1", s.clarity: "99"}, page="/spaces")
    assert "Not saved yet" in bad.text and 'id="version"' not in bad.text
    assert 'value="2"' in s.sue.get(s.task).text  # the bad one changed nothing


def test_group_mates_see_each_others_conflicts():
    s = Setup(group=True)
    s.save(**{s.clarity: "2"})  # Sue saves version 1
    page = s.sue.get(s.task).text
    assert "Group review by Reviewers" in page and "Who saved" in page
    stale_auto = post(s.pat, f"{s.task}/autosave", {"version": "0", s.clarity: "5"}, page="/spaces")
    assert "someone changed" in stale_auto.text and 'id="version"' not in stale_auto.text
    r = s.save(s.pat, version="0", **{s.clarity: "5"})
    assert r.status_code == 409 and "Someone else saved" in r.text and 'value="5"' in r.text
    assert 'name="version" value="1"' in r.text  # saving again from here replaces Sue's save
    ok = s.save(s.pat, version="1", **{s.clarity: "5"})
    assert ok.status_code == 303
    assert "Pat" in s.sue.get(s.task).text  # the trail names who saved


def test_comments_are_pinned_to_selected_text_and_deleted():
    s = Setup()
    start = TEXT.index("quick")
    r = post(
        s.sue,
        f"{s.task}/annotations",
        {"quote": "quick", "start": str(start), "end": str(start + 5), "body": "Vivid word"},
        page=s.task,
    )
    assert r.status_code == 303
    page = s.sue.get(s.task).text
    assert "Vivid word" in page and "quick" in page
    bad = post(
        s.sue,
        f"{s.task}/annotations",
        {"quote": "slow", "start": str(start), "end": str(start + 4), "body": "x"},
        page=s.task,
    )
    assert bad.status_code == 400 and "Select some text" in bad.text
    aid = find(r"/annotations/(\w+)/delete", page)
    post(s.sue, f"{s.task}/annotations/{aid}/delete", {}, page=s.task)
    assert "Vivid word" not in s.sue.get(s.task).text


def test_the_raw_revision_is_served_to_the_reviewer_only():
    s = Setup()
    r = s.sue.get(f"{s.task}/raw")
    assert r.status_code == 200 and r.text == TEXT
    assert r.headers["x-content-type-options"] == "nosniff"
    assert s.pat.get(f"{s.task}/raw").status_code == 404
    assert s.sam.get(f"{s.task}/raw").status_code == 404


def test_others_cannot_open_or_write_the_review():
    s = Setup()
    for other in (s.sam, s.pat):  # the author and another student
        assert other.get(s.task).status_code == 404
        assert s.save(other, **{s.clarity: "1"}).status_code == 404
    stranger = s.c.h.new_client()
    signup(stranger, "zed@x.fi", "Zed")
    assert stranger.get(s.task).status_code == 404


def test_the_teacher_reads_the_review_but_cannot_edit_it():
    s = Setup()
    s.save(**{s.clarity: "4"})
    page = s.c.teacher.get(s.task).text
    assert 'value="4"' in page and "only the reviewer can edit" in page
    assert "Save draft" not in page and "Add comment" not in page
    assert s.save(s.c.teacher, **{s.clarity: "1"}, version="1").status_code == 403


def test_the_round_page_and_my_reviews_show_progress():
    s = Setup()
    assert "not started" in s.c.teacher.get(f"{s.call}/rounds").text
    s.save(**{s.clarity: "4"})
    assert "draft" in s.c.teacher.get(f"{s.call}/rounds").text
    assert "draft" in s.sue.get(f"{s.c.space}/reviews").text
    s.save(intent="submit", version="1", **{s.clarity: "4"})
    assert "submitted" in s.c.teacher.get(f"{s.call}/rounds").text


def test_a_round_with_reviews_refuses_reallocation_and_deletion():
    s = Setup()
    s.save(**{s.clarity: "4"})
    r = post(s.c.teacher, f"/rounds/{s.round}/delete", {}, page=f"{s.call}/rounds")
    assert r.status_code == 400 and "Reviews have been written" in r.text
